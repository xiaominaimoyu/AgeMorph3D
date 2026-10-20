"""Native PyTorch replacement for SAM's JIT-compiled ``fused_bias_act``.

Upstream ``models/stylegan2/op/fused_act.py`` calls ``torch.utils.cpp_extension.load``
at import time, which needs nvcc and a compatible MSVC toolchain. This module keeps
the public names (``FusedLeakyReLU``, ``fused_leaky_relu``) and the ``bias``
parameter name so the official checkpoint loads unchanged, but evaluates
``leaky_relu(x + bias) * scale`` with ATen kernels.

It is a research-only workaround, not a service asset: it does not change weights,
does not add downloads and does not grant any license.
"""

import torch
from torch import nn
from torch.nn import functional as F


class FusedLeakyReLU(nn.Module):
    def __init__(self, channel, negative_slope=0.2, scale=2**0.5):
        super().__init__()
        self.bias = nn.Parameter(torch.zeros(channel))
        self.negative_slope = negative_slope
        self.scale = scale

    def forward(self, input):
        return fused_leaky_relu(input, self.bias, self.negative_slope, self.scale)


def fused_leaky_relu(input, bias, negative_slope=0.2, scale=2**0.5):
    if input.ndim < 2 or bias.ndim != 1 or bias.shape[0] != input.shape[1]:
        raise ValueError("fused_leaky_relu expects (N, C, ...) input and a C-length bias.")
    bias = bias.reshape(1, -1, *([1] * (input.ndim - 2)))
    return F.leaky_relu(input + bias, negative_slope) * scale
