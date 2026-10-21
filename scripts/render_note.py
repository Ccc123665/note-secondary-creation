# -*- coding: utf-8 -*-
"""按 variant 渲染小红书 3:4 图文（1080×1440），强制贴中公 logo。

用法：
    python render_note.py --content content.json --variant variant.json --out 图片/
    python render_note.py --content content.json --variant variant.json --out 图片/ --no-deer

content.json 结构见 references/visual-system.md
"""
import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1080, 1440
M = 80                 # 左右边距
TOP = 96
BOTTOM_SAFE = 1180     # 文字不得越过此线
LOGO_H = 52
LOGO_Y = H - 120       # 1320 -> 顶边 1276

FONT_BOLD = ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"]
FONT_REG = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]

FONT_PAIRS = {
    "yahei_bold": (FONT_BOLD, FONT_REG, 1.00),
    "hei_bold": (["C:/Windows/Fonts/simhei.ttf"], FONT_REG, 0.98),
    "yahei_only": (FONT_BOLD, FONT_BOLD, 1.04),
    "hei_only": (["C:/Windows/Fonts/simhei.ttf"], ["C:/Windows/Fonts/simhei.ttf"], 0.96),
    "mixed": (FONT_BOLD, ["C:/Windows/Fonts/simhei.ttf"], 1.02),
}

LAYOUTS = {
    "magazine": dict(card=False, grid=False, top_rule=True, side_index=True, title_scale=1.00, pad=0),
    "card":     dict(card=True,  grid=False, top_rule=False, side_index=False, title_scale=0.96, pad=48),
    "bigtype":  dict(card=False, grid=False, top_rule=False, side_index=False, title_scale=1.22, pad=0),
    "memo":     dict(card=False, grid=True,  top_rule=False, side_index=False, title_scale=0.98, pad=0),
    "data":     dict(card=False, grid=False, top_rule=True, side_index=False, title_scale=0.94, pad=0),
    "index":    dict(card=False, grid=False, top_rule=False, side_index=True, title_scale=0.96, pad=0),
}


def rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def load_json(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


class Renderer:
    def __init__(self, palette, variant, content_dir):
        self.p = palette
        self.mode = palette.get("mode", "light")
        self.bg = rgb(palette["bg"])
        self.surface = rgb(palette["surface"])
        self.ink = rgb(palette["ink"])
        self.sub = rgb(palette["sub"])
        self.accent = rgb(palette["accent"])
        self.accent2 = rgb(palette["accent2"])
        self.line = rgb(palette["line"])
        self.content_dir = content_dir
        self._font_cache = {}

        fp = variant.get("dimensions", {}).get("font_pair", {}).get("id", "yahei_bold")
        self.bold_paths, self.reg_paths, self.scale = FONT_PAIRS.get(fp, FONT_PAIRS["yahei_bold"])
        ly = variant.get("dimensions", {}).get("layout", {}).get("id", "magazine")
        self.layout = LAYOUTS.get(ly, LAYOUTS["magazine"])
        self.layout_id = ly
        self.cover_id = variant.get("dimensions", {}).get("cover", {}).get("id", "stat")
        deer = variant.get("dimensions", {}).get("deer", {}).get("id", "cheer")
        self.deer_path = os.path.join(BASE, "assets", "deer", f"{deer}.png")
        logo = "offcn_light.png" if self.mode == "dark" else "offcn_dark.png"
        self.logo_path = os.path.join(BASE, "assets", "logo", logo)

    # ---------- 基础工具 ----------
    def font(self, size, bold=False):
        size = max(12, int(size))
        key = (size, bold)
        if key in self._font_cache:
            return self._font_cache[key]
        paths = self.bold_paths if bold else self.reg_paths
        f = None
        for p in paths:
            if os.path.exists(p):
                try:
                    f = ImageFont.truetype(p, size)
                    break
                except Exception:
                    continue
        if f is None:
            f = ImageFont.load_default()
        self._font_cache[key] = f
        return f

    def wrap(self, text, font, maxw):
        lines, cur = [], ""
        for ch in str(text):
            if ch == "\n":
                lines.append(cur)
                cur = ""
                continue
            if font.getlength(cur + ch) <= maxw:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines or [""]

    def text(self, d, xy, text, font, fill, maxw=None, lh=1.55, align="left", max_lines=None):
        x, y = xy
        maxw = maxw or (W - 2 * M)
        lines = self.wrap(text, font, maxw)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:-1] + "…" if len(lines[-1]) > 1 else lines[-1]
        step = int(font.size * lh)
        for ln in lines:
            w = font.getlength(ln)
            dx = x
            if align == "center":
                dx = x + (maxw - w) / 2
            elif align == "right":
                dx = x + (maxw - w)
            d.text((dx, y), ln, font=font, fill=fill)
            y += step
        return y

    def measure(self, text, font, maxw=None):
        maxw = maxw or (W - 2 * M)
        return len(self.wrap(text, font, maxw)) * int(font.size * 1.55)

    # ---------- 装饰 ----------
    def backdrop(self, d):
        d.rectangle([0, 0, W, H], fill=self.bg)
        if self.layout["grid"]:
            for y in range(0, H, 48):
                d.line([(0, y), (W, y)], fill=self.line, width=1)
            for x in range(0, W, 48):
                d.line([(x, 0), (x, H)], fill=self.line, width=1)
        if self.layout["top_rule"]:
            d.line([(M, TOP - 26), (W - M, TOP - 26)], fill=self.line, width=3)
            d.rectangle([M, TOP - 34, M + 86, TOP - 26], fill=self.accent)

    def tape(self, d):
        if self.layout_id != "memo":
            return
        pts = [(M - 18, TOP + 8), (M + 132, TOP - 14), (M + 146, TOP + 22), (M - 4, TOP + 44)]
        d.polygon(pts, fill=self.accent2)

    def pageno(self, d, idx, total):
        if idx <= 0:
            return
        f = self.font(24)
        s = f"{idx:02d}/{total:02d}"
        d.text((W - M - f.getlength(s), 56), s, font=f, fill=self.sub)

    def paste_alpha(self, canvas, path, box_w, box_h, pos):
        if not os.path.exists(path):
            return False
        try:
            im = Image.open(path).convert("RGBA")
        except Exception:
            return False
        r = min(box_w / im.width, box_h / im.height)
        im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
        canvas.paste(im, pos, im)
        return True

    def logo(self, canvas):
        d = ImageDraw.Draw(canvas)
        if not os.path.exists(self.logo_path):
            d.rectangle([M, LOGO_Y, M + 150, LOGO_Y + LOGO_H], outline=self.accent, width=2)
            d.text((M + 8, LOGO_Y + 8), "offcn", font=self.font(26, True), fill=self.ink)
            return
        im = Image.open(self.logo_path).convert("RGBA")
        r = LOGO_H / im.height
        im = im.resize((int(im.width * r), LOGO_H), Image.LANCZOS)
        canvas.paste(im, (M, LOGO_Y), im)

    def deer(self, canvas, max_h=230, allowed=True):
        if not allowed or not os.path.exists(self.deer_path):
            return
        im = Image.open(self.deer_path).convert("RGBA")
        r = max_h / im.height
        im = im.resize((int(im.width * r), max_h), Image.LANCZOS)
        x = W - 60 - im.width
        y = LOGO_Y + LOGO_H - im.height
        canvas.paste(im, (x, y), im)

    # ---------- 页面 ----------
    def cover(self, page, idx, total):
        canvas = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(canvas)
        self.backdrop(d)
        self.tape(d)
        self.pageno(d, idx, total)

        kicker = page.get("kicker") or ""
        f_kick = self.font(28, True)
        if kicker:
            tw = f_kick.getlength(kicker)
            d.rectangle([M, TOP + 4, M + tw + 36, TOP + 52], fill=self.accent)
            d.text((M + 18, TOP + 12), kicker, font=f_kick,
                   fill=(255, 255, 255) if self.mode == "light" else self.bg)

        lines = page.get("title_lines") or [page.get("title", "")]
        n = len(lines)
        base = 104 if n <= 2 else 82
        size = int(base * self.scale)
        maxw = W - 2 * M - (60 if self.cover_id == "bigword" else 0)
        f_title = self.font(size, True)
        y = TOP + 150

        if self.cover_id == "bigword":
            y = self._cover_bigword(d, lines, f_title, y, maxw)
        elif self.cover_id == "question":
            y = self._cover_question(d, lines, f_title, y, maxw)
        elif self.cover_id == "toc":
            y = self._cover_toc(d, page, f_title, y, maxw)
        else:
            y = self._cover_stat(d, page, lines, f_title, y, maxw)

        sub = page.get("subtitle")
        if sub and self.cover_id != "toc":
            f_sub = self.font(38)
            y += 18
            y = self.text(d, (M, y), sub, f_sub, self.sub, maxw=maxw, lh=1.5)

        badge = page.get("badge")
        if badge:
            f_b = self.font(26, True)
            bw = f_b.getlength(badge) + 36
            by = min(y + 20, BOTTOM_SAFE - 260)
            d.rounded_rectangle([M, by, M + bw, by + 48], radius=24, outline=self.accent, width=2)
            d.text((M + 18, by + 9), badge, font=f_b, fill=self.accent)

        y = self._draw_stats(d, page, y)

        self.logo(canvas)
        self.deer(canvas, 250, allowed=(y < 1090))
        return canvas

    def _draw_stats(self, d, page, y):
        stats = page.get("stats") or []
        if not stats:
            return y
        n = len(stats)
        gap = 20
        cw = (W - 2 * M - gap * (n - 1)) / n
        top = max(y + 70, 720)
        top = min(top, BOTTOM_SAFE - 220)
        for i, st in enumerate(stats):
            x = M + i * (cw + gap)
            d.rounded_rectangle([x, top, x + cw, top + 168], radius=18, fill=self.surface)
            d.rectangle([x, top, x + 8, top + 168], fill=self.accent)
            d.text((x + 28, top + 30), str(st.get("value", "")),
                   font=self.font(52, True), fill=self.accent)
            d.text((x + 30, top + 104), str(st.get("label", "")),
                   font=self.font(26), fill=self.sub)
        return top + 168

    def _cover_stat(self, d, page, lines, f_title, y, maxw):
        for ln in lines:
            y = self.text(d, (M, y), ln, f_title, self.ink, maxw=maxw, lh=1.18)
            y += 6
        return y

    def _cover_bigword(self, d, lines, f_title, y, maxw):
        for i, ln in enumerate(lines):
            color = self.accent if i == 0 else self.ink
            y = self.text(d, (M, y), ln, f_title, color, maxw=maxw, lh=1.12)
        d.rectangle([M, y + 24, M + 160, y + 34], fill=self.accent2)
        return y + 54

    def _cover_question(self, d, lines, f_title, y, maxw):
        f_mark = self.font(int(120 * self.scale), True)
        d.text((M - 8, y - 40), "?", font=f_mark, fill=self.accent2)
        y += 96
        for ln in lines:
            y = self.text(d, (M, y), ln, f_title, self.ink, maxw=maxw, lh=1.2)
            y += 8
        return y

    def _cover_toc(self, d, page, f_title, y, maxw):
        y = self.text(d, (M, y), page.get("title", "目录"), f_title, self.ink, maxw=maxw, lh=1.2)
        y += 40
        items = page.get("toc") or [p.get("heading", "") for p in page.get("_siblings", [])][:6]
        f_i = self.font(36)
        f_n = self.font(30, True)
        for i, it in enumerate(items[:6], 1):
            if not it:
                continue
            d.text((M, y), f"{i:02d}", font=f_n, fill=self.accent)
            d.line([(M + 62, y + 52), (W - M, y + 52)], fill=self.line, width=2)
            d.text((M + 82, y), it, font=f_i, fill=self.ink)
            y += 78
        return y

    def _est_section(self, page, hsize, maxw):
        f_h = self.font(hsize, True)
        h = len(self.wrap(page.get("heading", ""), f_h, maxw)) * int(hsize * 1.22) + 66
        f_b = self.font(42)
        bullets = page.get("bullets") or []
        if self.layout_id == "bigtype":
            bullets = bullets[:3]
        for b in bullets:
            h += len(self.wrap(b, f_b, maxw - 34)) * int(42 * 1.7) + 30
        hl = page.get("highlight")
        if hl:
            h += len(self.wrap(hl, self.font(38, True), maxw - 60)) * int(38 * 1.5) + 60
        if page.get("note"):
            h += 44
        return h

    def section(self, page, idx, total):
        canvas = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(canvas)
        self.backdrop(d)
        self.tape(d)
        self.pageno(d, idx, total)

        bullets = page.get("bullets") or []
        if self.layout_id == "bigtype":
            bullets = bullets[:3]

        heading = page.get("heading", "")
        hsize = int(62 * self.layout["title_scale"] * self.scale)
        f_h = self.font(hsize, True)

        pad = self.layout["pad"]
        maxw = W - 2 * M - 2 * pad if self.layout["card"] else W - 2 * M
        y = TOP + 110

        # 内容偏短时把多余竖向空间匀给行距，避免整页挤在上半部
        est = self._est_section(page, hsize, maxw)
        extra = max(0, (BOTTOM_SAFE - y) - est)
        start_pad = min(52, int(extra * 0.14))
        b_gap = 30 + min(30, int(max(0, extra - start_pad) / max(len(bullets) + 1, 1)))

        if self.layout["card"]:
            bottom = min(y + start_pad - 24 + est + pad + 44, BOTTOM_SAFE - 60)
            d.rounded_rectangle([M, y - 24, W - M, bottom], radius=28, fill=self.surface)
            x0 = M + pad
        else:
            x0 = M

        y += start_pad

        idx_no = page.get("index")
        if self.layout["side_index"] and idx_no:
            f_no = self.font(96, True)
            d.text((x0 - 6, y - 26), str(idx_no), font=f_no, fill=self.accent2)
            y += 96

        y = self.text(d, (x0, y), heading, f_h, self.ink, maxw=maxw, lh=1.22)
        y += 26
        d.line([(x0, y), (x0 + min(120, maxw), y)], fill=self.accent, width=5)
        y += 40

        f_b = self.font(42)
        f_dot = self.font(38, True)
        for b in bullets:
            if y > BOTTOM_SAFE - 90:
                break
            d.ellipse([x0, y + 16, x0 + 12, y + 28], fill=self.accent)
            y2 = self.text(d, (x0 + 34, y), b, f_b, self.ink, maxw=maxw - 34, lh=1.7, max_lines=3)
            y = y2 + b_gap

        hl = page.get("highlight")
        if hl and y < BOTTOM_SAFE - 120:
            f_h2 = self.font(38, True)
            hh = self.measure(hl, f_h2, maxw - 40) + 44
            top = y + 16
            d.rectangle([x0, top, x0 + 8, top + hh], fill=self.accent)
            d.rounded_rectangle([x0 + 8, top, x0 + maxw, top + hh], radius=12, fill=self.surface)
            self.text(d, (x0 + 34, top + 20), hl, f_h2, self.ink, maxw=maxw - 60, lh=1.5, max_lines=3)
            y = top + hh + 16

        note = page.get("note")
        if note:
            f_n = self.font(26)
            self.text(d, (x0, min(y + 16, BOTTOM_SAFE - 10)), note, f_n, self.sub,
                      maxw=maxw, lh=1.4, max_lines=2)

        self.logo(canvas)
        return canvas

    def table(self, page, idx, total):
        canvas = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(canvas)
        self.backdrop(d)
        self.pageno(d, idx, total)

        y = TOP + 110
        idx_no = page.get("index")
        if self.layout["side_index"] and idx_no:
            f_no = self.font(96, True)
            d.text((M, y - 26), str(idx_no), font=f_no, fill=self.accent2)
            y += 96

        f_h = self.font(int(60 * self.layout["title_scale"] * self.scale), True)
        y = self.text(d, (M, y), page.get("heading", ""), f_h, self.ink, maxw=W - 2 * M, lh=1.22)
        y += 34

        cols = page.get("columns") or ["项目", "数值"]
        rows = page.get("rows") or []
        rows = rows[:10]
        ncol = max(1, len(cols))
        tw = W - 2 * M
        cw = tw / ncol
        # 行少时把剩余高度均给行高，避免表格只占上半屏
        _fixed = 58 + (86 if page.get("highlight") else 0) + (52 if page.get("note") else 0)
        _avail = BOTTOM_SAFE - y - _fixed
        rh = int(max(62, min(102, _avail / max(len(rows), 1))))

        f_th = self.font(30, True)
        f_td = self.font(32)
        f_num = self.font(34, True)

        d.line([(M, y), (W - M, y)], fill=self.ink, width=3)
        y += 14
        for i, c in enumerate(cols):
            x = M + i * cw + 12
            d.text((x, y), str(c), font=f_th, fill=self.sub)
        y += 44

        for r, row in enumerate(rows):
            if r % 2 == 0:
                d.rectangle([M, y - 6, W - M, y + rh - 8], fill=self.surface)
            for i, cell in enumerate(row[:ncol]):
                x = M + i * cw + 12
                val = str(cell)
                if i == 0:
                    d.text((x, y + 6), val, font=f_td, fill=self.ink)
                else:
                    is_num = bool(re.fullmatch(r"[\d.,:：%\-—]+", val))
                    if is_num:
                        w = f_num.getlength(val)
                        d.text((x + cw - 24 - w, y + 4), val, font=f_num, fill=self.accent)
                    else:
                        d.text((x, y + 6), val, font=f_td, fill=self.ink)
            y += rh
            d.line([(M, y - 8), (W - M, y - 8)], fill=self.line, width=1)

        hl = page.get("highlight")
        if hl:
            f_h2 = self.font(34, True)
            y += 6
            d.rectangle([M, y, M + 8, y + 56], fill=self.accent)
            d.text((M + 28, y + 8), hl, font=f_h2, fill=self.ink)
            y += 70

        note = page.get("note")
        if note:
            f_n = self.font(26)
            self.text(d, (M, min(y + 8, BOTTOM_SAFE - 10)), note, f_n, self.sub,
                      maxw=W - 2 * M, lh=1.4, max_lines=2)

        self.logo(canvas)
        return canvas

    def quote(self, page, idx, total):
        canvas = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(canvas)
        self.backdrop(d)
        self.pageno(d, idx, total)

        f_q = self.font(72, True)
        d.text((M - 10, 300), "“", font=f_q, fill=self.accent2)
        f = self.font(52, True)
        y = self.text(d, (M, 440), page.get("text", ""), f, self.ink, maxw=W - 2 * M, lh=1.55)
        src = page.get("from")
        if src:
            f_s = self.font(30)
            d.line([(M, y + 30), (M + 80, y + 30)], fill=self.accent, width=4)
            d.text((M, y + 52), src, font=f_s, fill=self.sub)
        self.logo(canvas)
        return canvas

    def ending(self, page, idx, total):
        canvas = Image.new("RGB", (W, H), self.bg)
        d = ImageDraw.Draw(canvas)
        self.backdrop(d)
        self.tape(d)
        self.pageno(d, idx, total)

        y = 360
        f_h = self.font(int(68 * self.layout["title_scale"] * self.scale), True)
        y = self.text(d, (M, y), page.get("heading", "划重点"), f_h, self.ink, maxw=W - 2 * M, lh=1.2)
        y += 30
        d.rectangle([M, y, M + 140, y + 8], fill=self.accent)
        y += 56

        f_b = self.font(42)
        for b in (page.get("bullets") or [])[:4]:
            d.ellipse([M + 2, y + 18, M + 16, y + 32], fill=self.accent)
            y = self.text(d, (M + 36, y), b, f_b, self.ink, maxw=W - 2 * M - 36, lh=1.7, max_lines=2)
            y += 26

        cta = page.get("cta")
        if cta and y < BOTTOM_SAFE - 100:
            f_c = self.font(38, True)
            hh = self.measure(cta, f_c, W - 2 * M - 40) + 44
            d.rounded_rectangle([M, y + 20, W - M - 220, y + 20 + hh], radius=16, fill=self.accent)
            self.text(d, (M + 30, y + 42), cta, f_c,
                      (255, 255, 255) if self.mode == "light" else self.bg,
                      maxw=W - 2 * M - 280, lh=1.5, max_lines=2)
            y += hh + 30

        self.logo(canvas)
        self.deer(canvas, 260, allowed=(y < 1000))
        return canvas


def main():
    ap = argparse.ArgumentParser(description="按 variant 渲染小红书图文")
    ap.add_argument("--content", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--palette-file", default=os.path.join(BASE, "assets", "palettes.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-deer", action="store_true")
    args = ap.parse_args()

    content = load_json(args.content)
    variant = load_json(args.variant)
    palettes = {p["id"]: p for p in load_json(args.palette_file)["palettes"]}
    pid = variant.get("dimensions", {}).get("palette", {}).get("id", "cream_orange")
    palette = palettes.get(pid)
    if not palette:
        raise SystemExit(f"未知色板 {pid}")

    os.makedirs(args.out, exist_ok=True)
    r = Renderer(palette, variant, os.path.dirname(os.path.abspath(args.content)))
    if args.no_deer:
        r.deer_path = ""

    pages = content.get("pages") or []
    if not pages:
        raise SystemExit("content.json 里没有 pages")

    total = len(pages)
    outputs = []
    headings = [p.get("heading", "") for p in pages]
    for i, page in enumerate(pages):
        ptype = page.get("type", "section")
        if ptype == "cover":
            page = dict(page)
            page["_siblings"] = [{"heading": h} for h in headings[1:] if h]
            img = r.cover(page, i, total)
        elif ptype == "data":
            img = r.table(page, i, total)
        elif ptype == "quote":
            img = r.quote(page, i, total)
        elif ptype == "ending":
            img = r.ending(page, i, total)
        else:
            img = r.section(page, i, total)
        path = os.path.join(args.out, f"{i + 1:02d}.png")
        img.convert("RGB").save(path, "PNG", optimize=True)
        outputs.append(path)

    print(json.dumps({
        "ok": True,
        "count": len(outputs),
        "palette": pid,
        "layout": r.layout_id,
        "cover": r.cover_id,
        "files": outputs,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
