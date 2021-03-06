import os.path as osp

import torch
from torch.nn import Sequential as Seq, Linear as Lin, ReLU, BatchNorm1d as BN
from torch_geometric.nn import PointConv, fps, radius, global_max_pool

from . network_config import network_config, str2bool

#
# The 3D convolution method for 2D images is very, very slow.
# Much faster to use 2D convolutions 3 times

class PointNetFlags(network_config):

    def __init__(self):
        network_config.__init__(self)
        self._name = "pointnet"
        self._help = "PointNet Architecture with extra linear layers for multi-key classification"

    def build_parser(self, network_parser):
        # this_parser = network_parser
        this_parser = network_parser.add_parser(self._name, help=self._help)

        # this_parser.add_argument("--n-initial-filters",
        #     type    = int,
        #     default = 2,
        #     help    = "Number of filters applied, per plane, for the initial convolution")





class SAModule(torch.nn.Module):
    def __init__(self, ratio, r, nn):
        super(SAModule, self).__init__()
        self.ratio = ratio
        self.r = r
        self.conv = PointConv(nn)

    def forward(self, x, pos, batch):
        idx = fps(pos, batch, ratio=self.ratio)
        print("idx.shape: ", idx.shape)
        row, col = radius(pos, pos[idx], self.r, batch, batch[idx],
                          max_num_neighbors=64)
        print("row.shape: ", row.shape)
        edge_index = torch.stack([col, row], dim=0)
        print("edge_index.shape: ", edge_index.shape)
        x = self.conv(x, (pos, pos[idx]), edge_index)
        print("x.shape: ", x.shape)

        pos, batch = pos[idx], batch[idx]
        return x, pos, batch


class GlobalSAModule(torch.nn.Module):
    def __init__(self, nn):
        super(GlobalSAModule, self).__init__()
        self.nn = nn

    def forward(self, x, pos, batch):
        x = self.nn(torch.cat([x, pos], dim=1))
        x = global_max_pool(x, batch)
        pos = pos.new_zeros((x.size(0), 3))
        batch = torch.arange(x.size(0), device=batch.device)
        return x, pos, batch


def MLP(channels, batch_norm=True):
    return Seq(*[
        Seq(Lin(channels[i - 1], channels[i]), ReLU(), BN(channels[i]))
        for i in range(1, len(channels))
    ])


class PointNet(torch.nn.Module):
    def __init__(self, output_shape, args):
        torch.nn.Module.__init__(self)

        self.sa1_module = SAModule(0.5, 0.2, MLP([3, 64, 64, 128]))
        self.sa2_module = SAModule(0.25, 0.4, MLP([128 + 3, 128, 128, 256]))
        self.sa3_module = GlobalSAModule(MLP([256 + 3, 256, 512, 1024]))

        self.lin1 = Lin(1024, 512)
        self.lin2 = Lin(512, 256)

        self.lin3  = { key : Lin(256, 10) for key in output_shape }
    

        for key in self.lin3:
            self.add_module("lin3_{}".format(key), self.lin3[key])


    def forward(self, data):
        print("entered")
        sa0_out = (data.x, data.pos, data.batch)
        print("sa0")
        print("data.x.shape: ", data.x.shape)
        print("data.pos.shape: ", data.pos.shape)
        print("data.batch.shape: ", data.batch.shape)
        sa1_out = self.sa1_module(*sa0_out)
        print("sa1")
        sa2_out = self.sa2_module(*sa1_out)
        print("sa2")
        sa3_out = self.sa3_module(*sa2_out)
        print("sa3")
        x, pos, batch = sa3_out

        x = torch.functional.relu(self.lin1(x))
        x = torch.functional.dropout(x, p=0.5, training=self.training)
        x = torch.functional.relu(self.lin2(x))
        x = torch.functional.dropout(x, p=0.5, training=self.training)
        
        print(x)

        # x = self.lin3(x)
        output = {}
        for key in self.lin3:
            # Apply the final block:
            output[key] = self.lin3[key](x)

        return output
