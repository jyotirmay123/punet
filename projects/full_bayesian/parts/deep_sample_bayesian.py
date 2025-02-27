"""Quicknat architecture"""
import numpy as np
import torch
import torch.nn as nn
from nn_common_modules import modules as sm
from squeeze_and_excitation import squeeze_and_excitation as se


class DeepSampleBayesianQuickNat(nn.Module):
    """
    A PyTorch implementation of QuickNAT

    """

    def __init__(self, params):
        """

        :param params: {'num_channels':1,
                        'num_filters':64,
                        'kernel_h':5,
                        'kernel_w':5,
                        'stride_conv':1,
                        'pool':2,
                        'stride_pool':2,
                        'num_classes':28
                        'se_block': False,
                        'drop_out':0.2}
        """
        super(DeepSampleBayesianQuickNat, self).__init__()

        params['num_channels'] = 1
        self.encode1 = sm.TimeDistributed(sm.FullBayesianEncoderBlock(params, se_block_type=se.SELayer.NONE))
        params['num_channels'] = 64
        self.encode2 = sm.TimeDistributed(sm.FullBayesianEncoderBlock(params, se_block_type=se.SELayer.NONE))
        self.encode3 = sm.TimeDistributed(sm.FullBayesianEncoderBlock(params, se_block_type=se.SELayer.NONE))
        self.encode4 = sm.TimeDistributed(sm.FullBayesianEncoderBlock(params, se_block_type=se.SELayer.NONE))
        self.bottleneck = sm.TimeDistributed(sm.FullBayesianDenseBlock(params, se_block_type=se.SELayer.NONE))
        params['num_channels'] = 128
        self.decode1 = sm.TimeDistributed(sm.FullBayesianDecoderBlock(params, se_block_type=se.SELayer.NONE))
        self.decode2 = sm.TimeDistributed(sm.FullBayesianDecoderBlock(params, se_block_type=se.SELayer.NONE))
        self.decode3 = sm.TimeDistributed(sm.FullBayesianDecoderBlock(params, se_block_type=se.SELayer.NONE))
        self.decode4 = sm.TimeDistributed(sm.FullBayesianDecoderBlock(params, se_block_type=se.SELayer.NONE))
        params['num_channels'] = 64
        self.classifier = sm.TimeDistributed(sm.ClassifierBlock(params))

        self.is_training = True

    def forward(self, input, gt=None):
        """

        :param input: X
        :return: probabiliy map
        """
        # if not self.is_training:
        #    self.enable_test_dropout()
        e1, out1, ind1, kl_e1 = self.encode1.forward(input)
        e2, out2, ind2, kl_e2 = self.encode2.forward(e1)
        e3, out3, ind3, kl_e3 = self.encode3.forward(e2)
        e4, out4, ind4, kl_e4 = self.encode4.forward(e3)

        bn, kl_bn = self.bottleneck.forward(e4)

        d4, kl_d4 = self.decode4.forward(bn, out4, ind4)
        d3, kl_d3 = self.decode3.forward(d4, out3, ind3)
        d2, kl_d2 = self.decode2.forward(d3, out2, ind2)
        d1, kl_d1 = self.decode1.forward(d2, out1, ind1)
        prob = self.classifier.forward(d1)

        kl_loss = 0.1 * (kl_e1 + kl_e2 + kl_e3 + kl_e4 + kl_bn + kl_d4 + kl_d3 + kl_d2 + kl_d1)
        return None, kl_loss, prob
        # return None, None, prob

    def set_is_training(self, is_training):
        self.is_training = is_training

    def enable_test_dropout(self):
        """
        Enables test time drop out for uncertainity
        :return:
        """
        attr_dict = self.__dict__['_modules']
        for i in range(1, 5):
            encode_block, decode_block = attr_dict['encode' + str(i)], attr_dict['decode' + str(i)]
            encode_block.drop_out = encode_block.drop_out.apply(nn.Module.train)
            decode_block.drop_out = decode_block.drop_out.apply(nn.Module.train)

    @property
    def is_cuda(self):
        """
        Check if saved_models parameters are allocated on the GPU.
        """
        return next(self.parameters()).is_cuda

    def save(self, path):
        """
        Save saved_models with its parameters to the given path. Conventionally the
        path should end with '*.saved_models'.

        Inputs:
        - path: path string
        """
        print('Saving saved_models... %s' % path)
        torch.save(self, path)

    def predict(self, X, device=0, enable_dropout=False, forward_out=False):
        """
        Predicts the outout after the saved_models is trained.
        Inputs:
        - X: Volume to be predicted
        """
        self.eval()

        if type(X) is np.ndarray:
            X = torch.tensor(X, requires_grad=False).type(torch.FloatTensor).cuda(device, non_blocking=True)
        elif type(X) is torch.Tensor and not X.is_cuda:
            X = X.type(torch.FloatTensor).cuda(device, non_blocking=True)

        if enable_dropout:
            self.enable_test_dropout()

        with torch.no_grad():
            X = X.unsqueeze(dim=0)
            X = X.repeat(2, 1, 1, 1, 1)
            out = self.forward(X)
            outs = out[2]

        if forward_out:
            return out
        else:
            prediction = []
            for out in outs:
                out = out.squeeze()
                max_val, idx = torch.max(out, 1)
                idx = idx.data.cpu().numpy()
                prediction.append(np.squeeze(idx))
                del out, idx, max_val
            return prediction
