# -*- coding: utf-8 -*-
"""素材预处理：把大尺寸 logo / 小鹿 压到出图够用的尺寸，避免每张图重复解码几十 MB。

用法：
    python prepare_assets.py            # 处理 assets/logo 与 assets/deer
换素材后重跑一次即可。原图不动。
"""
import os
import sys
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shrink(path, max_h, max_w=None):
    im = Image.open(path)
    im = im.convert("RGBA") if im.mode != "RGBA" else im
    w, h = im.size
    ratio = min(max_h / h, (max_w / w) if max_w else 99)
    if ratio < 1:
        im = im.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.LANCZOS)
    im.save(path, "PNG", optimize=True)
    return im.size, os.path.getsize(path) // 1024


def main():
    for d, h, w in ((os.path.join(BASE, "assets", "logo"), 220, 1400),
                    (os.path.join(BASE, "assets", "deer"), 760, 900)):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.lower().endswith(".png"):
                continue
            p = os.path.join(d, f)
            try:
                size, kb = shrink(p, h, w)
                print(f"OK   {f:22s} {size[0]}x{size[1]}  {kb}KB")
            except Exception as e:
                print(f"FAIL {f}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
