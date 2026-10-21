# -*- coding: utf-8 -*-
"""素材解析：PDF / 图片 → raw_text.md + facts.draft.json + pages/*.png

用法：
    python extract_facts.py --input "素材.pdf" --out output/xxx
    python extract_facts.py --input "图片目录" --out output/xxx
    python extract_facts.py --input "a.jpg" --out output/xxx --dpi 200

说明：
  - 有文本层的 PDF 直接抽文字，同时仍导出页面图供人工核对表格
  - 扫描件（平均每页 <20 字）标记 need_vision=true，必须逐张 Read 读图
  - facts.draft.json 是「候选事实」，level/type 为机器初判，AI 必须逐条复核后改名 facts.json
"""
import argparse
import json
import os
import re
import shutil
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    import pymupdf
except ImportError:  # 兼容旧版
    import fitz as pymupdf

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

MUST_KW = ["报名", "笔试", "面试", "招录", "招聘", "人数", "条件", "学历", "专业",
           "年龄", "资格", "截止", "时间", "职位", "岗位", "计划", "要求"]
DATE_PAT = re.compile(r"(20\d{2}\s*年|\d{1,2}\s*月|\d{1,2}\s*日|\d{1,2}:\d{2})")
NUM_PAT = re.compile(r"\d+(?:\.\d+)?%?")
SENT_SPLIT = re.compile(r"(?<=[。！？；!?;，,])\s*|\n+")
NOISE = re.compile(
    r"^(中公教育|给人改变未来的力量|OFFCN.*|.*EDUCATION.*|\d{1,3}|P\d{1,2}|第\s*\d+\s*页|扫码.*|关注.*)$",
    re.I)
NOISE_CONTAINS = re.compile(r"中公教育\s*·|第\s*\d+\s*页|O\s*F\s*F\s*C\s*N|给人改变未来的力量|关注公众号|扫码")
RULE_PAT = re.compile(r"不得|仅限|必须|可以|需要|须|不包括|除.{0,6}外")


def despace(s):
    """处理 PDF 里字距被拉开的标题：'2 0 2 7' -> '2027'"""
    if not s:
        return s
    if s.count(" ") > max(2, len(s) * 0.3):
        return s.replace(" ", "")
    return s


def merge_lines(text):
    """把因排版换行而断裂的句子拼回去。"""
    out, buf = [], ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            continue
        buf = (buf + line) if buf else line
        if re.search(r"[。！？；!?;]$", buf) or len(buf) > 120:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def safe_slug(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", name)[:60] or "material"


def clean_line(s):
    s = re.sub(r"[ \t\u3000]+", " ", s).strip()
    s = re.sub(r"(?i)https?://\S+", "", s)
    return despace(s).strip()


def guess_type(text):
    if DATE_PAT.search(text):
        return "date"
    if re.search(r"条件|要求|学历|专业|年龄|资格|限|不得|可以", text):
        return "rule"
    if NUM_PAT.search(text):
        return "number"
    if re.search(r"建议|最好|可以先|注意|推荐", text):
        return "advice"
    if re.search(r"因此|说明|意味着|总体|可见|结论", text):
        return "conclusion"
    return "name"


def guess_level(text):
    return "must" if any(k in text for k in MUST_KW) else "should"


def extract_numbers(text):
    nums = set(NUM_PAT.findall(text))
    for m in DATE_PAT.findall(text):
        nums.update(NUM_PAT.findall(m))
    return sorted(nums, key=lambda x: (len(x), x))


def score_sentence(s):
    sc = 0
    if NUM_PAT.search(s):
        sc += 3
    if DATE_PAT.search(s):
        sc += 2
    if any(k in s for k in MUST_KW):
        sc += 2
    if RULE_PAT.search(s):
        sc += 2
    if 15 <= len(s) <= 80:
        sc += 1
    if len(s) > 120:
        sc -= 1
    return sc


def build_facts(sentences, max_facts=60):
    pool, seen = [], set()
    for order, (sent, src) in enumerate(sentences):
        s = clean_line(sent)
        if len(s) < 8 or len(s) > 160:
            continue
        if NOISE.match(s) or NOISE_CONTAINS.search(s):
            continue
        key = re.sub(r"\s", "", s)
        if key in seen:
            continue
        seen.add(key)
        pool.append((score_sentence(s), order, s, src))

    # 高分优先，但按原文顺序输出，保留叙事线
    keep = sorted(pool, key=lambda x: (-x[0], x[1]))[:max_facts]
    keep.sort(key=lambda x: x[1])

    facts = []
    for _, _, s, src in keep:
        fid = f"F{len(facts) + 1:02d}"
        facts.append({
            "id": fid,
            "type": guess_type(s),
            "level": guess_level(s),
            "statement": s,
            "source": src,
            "numbers": extract_numbers(s),
            "note": "",
        })
    return facts


def handle_pdf(path, out_dir, dpi):
    doc = pymupdf.open(path)
    pages, total_chars = [], 0
    for i, page in enumerate(doc, 1):
        text = page.get_text("text") or ""
        total_chars += len(text.strip())
        pages.append((i, text))
    avg = total_chars / max(1, len(pages))
    need_vision = avg < 20

    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)
    for i, _ in pages:
        pix = doc[i - 1].get_pixmap(dpi=dpi)
        pix.save(os.path.join(out_dir, "pages", f"p{i:02d}.png"))
    doc.close()

    sentences, page_texts = [], []
    for i, text in pages:
        merged = merge_lines(text)
        page_texts.append((i, merged))
        for line in merged:
            for chunk in SENT_SPLIT.split(line):
                chunk = (chunk or "").strip()
                if not chunk:
                    continue
                while len(chunk) > 90:  # 缺标点的长块硬切
                    cut = max(chunk.rfind("，", 30, 90), chunk.rfind("、", 30, 90))
                    if cut < 30:
                        cut = 80
                    sentences.append((chunk[:cut + 1].strip(), f"第 {i} 页"))
                    chunk = chunk[cut + 1:].strip()
                if chunk:
                    sentences.append((chunk, f"第 {i} 页"))
    return sentences, page_texts, need_vision, len(pages), avg


def handle_images(path, out_dir):
    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)
    files = []
    if os.path.isdir(path):
        for f in sorted(os.listdir(path)):
            if os.path.splitext(f)[1].lower() in IMG_EXT:
                files.append(os.path.join(path, f))
    elif os.path.splitext(path)[1].lower() in IMG_EXT:
        files = [path]
    else:
        raise SystemExit(f"不支持的输入：{path}")
    if not files:
        raise SystemExit(f"目录内没有图片：{path}")

    for i, f in enumerate(files, 1):
        ext = os.path.splitext(f)[1].lower()
        shutil.copy(f, os.path.join(out_dir, "pages", f"p{i:02d}{ext}"))
    return [], [], True, len(files), 0


def assess_quality(sentences):
    """碎片率：能不能切出像样的整句。设计型 PDF 常把标题、编号、正文混排，导致碎片率高。"""
    if not sentences:
        return 0.0
    good = sum(1 for s, _ in sentences if len(s) >= 15 and re.search(r"[。！？；]$", s))
    return round(good / len(sentences), 3)


def write_raw_text(out_dir, source, page_texts, need_vision, n_pages, avg, mode, quality):
    lines = [f"# 素材原文：{os.path.basename(source)}", "",
             f"> 来源：{source}",
             f"> 页数：{n_pages}｜抽取方式：{mode}｜平均每页字数：{avg:.0f}",
             f"> 整句率：{quality:.0%}（低于 50% 说明排版把句子切碎了，事实卡需对照原图核对）",
             f"> 需视觉读图：{'是（文字层不足，必须逐张 Read pages/）' if need_vision else '否（建议仍抽查表格页）'}", ""]
    if need_vision:
        lines += ["> ⚠️ 本素材文字层不足，以下为空。请逐张 Read `pages/*.png`，",
                  "> 把表格、数字、条件转写到本文件 `## 视觉转写` 小节，再抽事实卡。", "",
                  "## 视觉转写", "", "（待 AI 填写）", ""]
    else:
        if quality < 0.5:
            lines += ["> ⚠️ 整句率偏低：`facts.draft.json` 仅供参考，",
                      "> 关键数字/条件请对照 `pages/*.png` 原图确认后再定稿。", ""]
        for i, merged in page_texts:
            lines += ["", f"## 第 {i} 页", ""]
            lines.extend(merged)
        lines.append("")
    with open(os.path.join(out_dir, "raw_text.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="PDF / 图片素材解析")
    ap.add_argument("--input", required=True, help="PDF 路径、图片路径或图片目录")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--dpi", type=int, default=150, help="页面导出分辨率，默认 150")
    ap.add_argument("--max-facts", type=int, default=60, help="候选事实上限，默认 60")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"输入不存在：{args.input}")
    os.makedirs(args.out, exist_ok=True)

    ext = os.path.splitext(args.input)[1].lower()
    if ext == ".pdf":
        sentences, page_texts, need_vision, n_pages, avg = handle_pdf(args.input, args.out, args.dpi)
        mode = "text-layer" if not need_vision else "scan/vision"
    else:
        sentences, page_texts, need_vision, n_pages, avg = handle_images(args.input, args.out)
        mode = "vision"

    quality = assess_quality(sentences)
    # 排版型 PDF：有文字层但整句率太低，仍然建议读图
    recommend_vision = need_vision or quality < 0.5

    facts = build_facts(sentences, args.max_facts) if sentences else []
    write_raw_text(args.out, args.input, page_texts, need_vision, n_pages, avg, mode, quality)

    draft = {
        "source": args.input,
        "mode": mode,
        "need_vision": need_vision,
        "recommend_vision": recommend_vision,
        "sentence_quality": quality,
        "pages": n_pages,
        "avg_chars_per_page": round(avg, 1),
        "facts": facts,
        "_hint": "draft 仅机器初判。请 AI 逐条复核 type/level/statement，补 note，另存为 facts.json",
    }
    with open(os.path.join(args.out, "facts.draft.json"), "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    must = sum(1 for x in facts if x["level"] == "must")
    print(json.dumps({
        "ok": True,
        "mode": mode,
        "need_vision": need_vision,
        "recommend_vision": recommend_vision,
        "sentence_quality": quality,
        "pages": n_pages,
        "avg_chars_per_page": round(avg, 1),
        "draft_facts": len(facts),
        "draft_must": must,
        "raw_text": os.path.join(args.out, "raw_text.md"),
        "facts_draft": os.path.join(args.out, "facts.draft.json"),
        "pages_dir": os.path.join(args.out, "pages"),
        "next": "recommend_vision=true 时先逐张读图核对数字，再定稿 facts.json",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
