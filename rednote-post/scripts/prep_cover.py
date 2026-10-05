#!/usr/bin/env python3
"""把手机拍的实体书封面，处理成卡片可用的封面图。

两个子命令，对应手动流程的两步：

  grid <photo>                 在照片上叠坐标网格，用来读四角坐标（省得靠猜）
  flat <photo> --corners ...   透视校正 + 裁边 + 压色 + 混纸色，输出 PNG

为什么需要它：实体书照片通常有倾斜、透视、手指入镜、背景杂乱。
直接贴进卡片会显得脏；裁又裁不干净。这里做的是「把书那一块取出来摊平」。

依赖只有 Pillow（本机系统 Python 自带）。透视解算用纯 Python 高斯消元——
不要引入 numpy，本机没有。
"""
from __future__ import annotations

import argparse
import sys

try:
    from PIL import Image, ImageDraw, ImageEnhance
except ImportError:  # pragma: no cover
    sys.exit("需要 Pillow：python3 -m pip install pillow")


# ---------- 透视变换 ----------

def _solve(A: list[list[float]], B: list[float]) -> list[float]:
    n = len(A)
    M = [row[:] + [B[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            raise ValueError("四点共线或退化，无法解出透视系数；请重新标定四角")
        M[c], M[p] = M[p], M[c]
        pv = M[c][c]
        for j in range(c, n + 1):
            M[c][j] /= pv
        for r in range(n):
            if r != c and M[r][c] != 0:
                f = M[r][c]
                for j in range(c, n + 1):
                    M[r][j] -= f * M[c][j]
    return [M[i][n] for i in range(n)]


def _coeffs(dst, src):
    A, B = [], []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); B.append(X)
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y]); B.append(Y)
    return _solve(A, B)


def _parse_corners(s: str):
    parts = [p for p in s.replace(" ", "").split(",") if p]
    if len(parts) != 8:
        raise argparse.ArgumentTypeError(
            "四角要 8 个数：TLx,TLy,TRx,TRy,BRx,BRy,BLx,BLy（顺序：左上/右上/右下/左下）")
    v = [float(p) for p in parts]
    return [(v[0], v[1]), (v[2], v[3]), (v[4], v[5]), (v[6], v[7])]


# ---------- 子命令 ----------

def cmd_grid(args) -> int:
    im = Image.open(args.photo)
    try:
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im = im.convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    step = args.step
    for x in range(0, W, step):
        d.line([(x, 0), (x, H)], fill=(255, 0, 0), width=1)
        d.text((x + 3, 6), str(x), fill=(255, 0, 0))
    for y in range(0, H, step):
        d.line([(0, y), (W, y)], fill=(0, 170, 0), width=1)
        d.text((4, y + 3), str(y), fill=(0, 140, 0))
    im.save(args.out)
    print(f"已输出坐标网格：{args.out}（{W}×{H}，每 {step}px 一格）")
    print("看图读四角的像素坐标，再跑：")
    print(f"  {sys.argv[0]} flat {args.photo} "
          "--corners TLx,TLy,TRx,TRy,BRx,BRy,BLx,BLy --out <post-dir>/assets/cover.png")
    return 0


def cmd_flat(args) -> int:
    im = Image.open(args.photo)
    try:
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    im = im.convert("RGB")

    W = args.width
    src_h = ((max(args.corners[2][1], args.corners[3][1]) - min(args.corners[0][1], args.corners[1][1]))
             + (max(args.corners[2][0], args.corners[3][0]) - min(args.corners[0][0], args.corners[1][0])))
    # 用两条对边的平均长估算高宽比，避免直接写死
    top = ((args.corners[1][0] - args.corners[0][0]) ** 2 + (args.corners[1][1] - args.corners[0][1]) ** 2) ** .5
    bottom = ((args.corners[2][0] - args.corners[3][0]) ** 2 + (args.corners[2][1] - args.corners[3][1]) ** 2) ** .5
    left = ((args.corners[3][0] - args.corners[0][0]) ** 2 + (args.corners[3][1] - args.corners[0][1]) ** 2) ** .5
    right = ((args.corners[2][0] - args.corners[1][0]) ** 2 + (args.corners[2][1] - args.corners[1][1]) ** 2) ** .5
    rw, rh = (top + bottom) / 2, (left + right) / 2
    H = int(round(W * rh / rw))

    dst = [(0, 0), (W, 0), (W, H), (0, H)]
    out = im.transform((W, H), Image.PERSPECTIVE, _coeffs(dst, args.corners), Image.BICUBIC)

    if args.inset:
        n = args.inset
        out = out.crop((n, n, W - n, H - n))

    if args.saturate != 1.0:
        out = ImageEnhance.Color(out).enhance(args.saturate)
    if args.contrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(args.contrast)
    if args.brightness != 1.0:
        out = ImageEnhance.Brightness(out).enhance(args.brightness)
    if args.blend:
        rgb = tuple(int(args.paper[i:i + 2], 16) for i in (0, 2, 4))
        out = Image.blend(out, Image.new("RGB", out.size, rgb), args.blend)

    out.save(args.out)
    print(f"已输出摊平后的封面：{args.out}（{out.size[0]}×{out.size[1]}）")
    print("下一步：确认方向与内容清晰，再把这张图的绝对路径贴给用户看一眼。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把实体书照片处理成卡片封面图")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("grid", help="叠坐标网格，用来读四角")
    p.add_argument("photo")
    p.add_argument("--out", default="/tmp/cover-grid.png")
    p.add_argument("--step", type=int, default=64)
    p.set_defaults(fn=cmd_grid)

    p = sub.add_parser("flat", help="透视校正并输出封面 PNG")
    p.add_argument("photo")
    p.add_argument("--corners", required=True, type=_parse_corners,
                   help="TLx,TLy,TRx,TRy,BRx,BRy,BLx,BLy")
    p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=1240, help="输出宽度，默认 1240")
    p.add_argument("--inset", type=int, default=12, help="四边各裁掉几像素，默认 12")
    p.add_argument("--saturate", type=float, default=0.88)
    p.add_argument("--contrast", type=float, default=1.04)
    p.add_argument("--brightness", type=float, default=1.02)
    p.add_argument("--blend", type=float, default=0.06, help="往纸色混合的比例，默认 0.06")
    p.add_argument("--paper", default="F3EEE5")
    p.set_defaults(fn=cmd_flat)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
