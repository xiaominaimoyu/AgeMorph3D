"""Native PyTorch replacement for SAM's JIT-compiled ``upfirdn2d``.

Upstream ``models/stylegan2/op/upfirdn2d.py`` compiles a CUDA extension at import
time. This module implements the same operator with zero-stuffing, constant
padding, a depthwise ``conv2d`` and decimation, which matches the original
upsample/downsample/blur call sites without nvcc.

Only inference is exercised here. The implementation is differentiable, but it
is not a throughput replacement for the CUDA kernel.

Research-only workaround; it does not change weights or licenses.
"""

from torch.nn import functional as F


def upfirdn2d(input, kernel, up=1, down=1, pad=(0, 0)):
    if input.ndim != 4 or kernel.ndim != 2:
        raise ValueError("upfirdn2d expects (N, C, H, W) input and a 2-D kernel.")
    if type(up) is not int or type(down) is not int or up < 1 or down < 1:
        raise ValueError("up and down must be positive integers.")
    if len(pad) != 2 or any(type(value) is not int for value in pad):
        raise ValueError("pad must be a pair of integers.")

    if up != 1:
        batch, channel, height, width = input.shape
        stuffed = input.new_zeros((batch, channel, height * up, width * up))
        stuffed[:, :, ::up, ::up] = input
        input = stuffed

    if pad != (0, 0):
        left, right = max(pad[0], 0), max(pad[1], 0)
        input = F.pad(input, (left, right, left, right))
        crop_left, crop_right = max(-pad[0], 0), max(-pad[1], 0)
        if crop_left or crop_right:
            height, width = input.shape[2:]
            input = input[
                :,
                :,
                crop_left : height - crop_right,
                crop_left : width - crop_right,
            ]

    channel = input.shape[1]
    weight = kernel.flip((0, 1)).reshape(1, 1, *kernel.shape)
    weight = weight.repeat(channel, 1, 1, 1)
    out = F.conv2d(input, weight, groups=channel)

    if down != 1:
        out = out[:, :, ::down, ::down]
    return out
