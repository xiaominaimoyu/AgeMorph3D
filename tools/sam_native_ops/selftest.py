"""Numeric self-test for the native StyleGAN2 op shims.

The CUDA extensions cannot be compiled on this host, so the replacement ops are
checked against a slow explicit-loop reference instead. Run inside the isolated
SAM environment:

    python tools/sam_native_ops/selftest.py
"""

from __future__ import annotations

import torch
from fused_act import fused_leaky_relu
from torch.nn import functional as F
from upfirdn2d import upfirdn2d


def _reference_upfirdn2d(input, kernel, up, down, pad):
    batch, channel, height, width = input.shape
    if up != 1:
        stuffed = input.new_zeros((batch, channel, height * up, width * up))
        stuffed[:, :, ::up, ::up] = input
        input = stuffed
    if pad != (0, 0):
        left, right = max(pad[0], 0), max(pad[1], 0)
        input = F.pad(input, (left, right, left, right))
        crop_left, crop_right = max(-pad[0], 0), max(-pad[1], 0)
        if crop_left or crop_right:
            padded_h, padded_w = input.shape[2:]
            input = input[
                :,
                :,
                crop_left : padded_h - crop_right,
                crop_left : padded_w - crop_right,
            ]
    _, _, padded_h, padded_w = input.shape
    kernel_h, kernel_w = kernel.shape
    out_h = padded_h - kernel_h + 1
    out_w = padded_w - kernel_w + 1
    out = input.new_zeros((batch, channel, out_h, out_w))
    flipped = kernel.flip((0, 1))
    for y in range(out_h):
        for x in range(out_w):
            patch = input[:, :, y : y + kernel_h, x : x + kernel_w]
            out[:, :, y, x] = (patch * flipped).sum(dim=(2, 3))
    return out[:, :, ::down, ::down]


def main() -> int:
    torch.manual_seed(0)
    failures = []

    x = torch.randn(2, 3, 7, 5)
    bias = torch.randn(3)
    expected = F.leaky_relu(x + bias.reshape(1, 3, 1, 1), 0.2) * (2**0.5)
    actual = fused_leaky_relu(x, bias)
    error = (actual - expected).abs().max().item()
    print(f"fused_leaky_relu max_abs_error={error:.3e}")
    if error > 1e-6:
        failures.append("fused_leaky_relu")

    cases = [
        ((1, 2, 5, 5), 4, 2, 1, (2, 1)),
        ((2, 3, 6, 4), 3, 1, 2, (1, 0)),
        ((1, 4, 8, 8), 4, 1, 1, (1, 1)),
        ((2, 1, 3, 7), 6, 3, 1, (2, 3)),
        ((2, 2, 7, 5), 3, 1, 2, (-1, 2)),
    ]
    for shape, size, up, down, pad in cases:
        input = torch.randn(*shape)
        kernel = torch.randn(size, size)
        expected = _reference_upfirdn2d(input, kernel, up, down, pad)
        actual = upfirdn2d(input, kernel, up=up, down=down, pad=pad)
        if actual.shape != expected.shape:
            print(
                f"upfirdn2d shape={shape} up={up} down={down} pad={pad}: "
                f"{actual.shape} != {expected.shape}"
            )
            failures.append(f"upfirdn2d-shape-{shape}")
            continue
        error = (actual - expected).abs().max().item()
        print(
            f"upfirdn2d shape={shape} k={size} up={up} down={down} pad={pad} "
            f"max_abs_error={error:.3e}"
        )
        if error > 1e-5:
            failures.append(f"upfirdn2d-value-{shape}")

    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
