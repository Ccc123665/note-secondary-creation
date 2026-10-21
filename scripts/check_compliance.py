# -*- coding: utf-8 -*-
"""合规闸门：扫文案与图片，BLOCK 级命中即失败。

用法：
    python check_compliance.py --copy 文案.md --images 图片/
    python check_compliance.py --copy output/xxx --strict
    python check_compliance.py --copy 文案.md --sensitive 敏感词库.json

退出码：0 通过 / 1 有 BLOCK / 2 仅有 WARN
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEXT_EXT = {".md", ".txt", ".json"}

# ---------- BLOCK ----------
BLOCK = [
    ("引流-网址", re.compile(r"(?:https?://|www\.)[^\s)）\"']+|[\w-]+\.(?:com|cn|net|org)(?:/|\b)", re.I), "删除网址"),
    ("引流-手机号", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "删除手机号"),
    ("引流-社交号", re.compile(r"微信|VX|vx|威信|QQ号|扣扣|加我|加V|私信|戳我|滴滴我|㈱|薇信"), "删除联系方式与私信引导"),
    ("引流-二维码", re.compile(r"二维码|扫码|扫一扫|长按识别"), "删除扫码引导"),
    ("引流-导流动作", re.compile(r"主页|评论区|领取|免费领|回复.{0,4}领|点击链接|阅读原文|关注我|点赞收藏|扣\s*1"), "删除导流动作"),
    ("机构名", re.compile(r"华图|粉笔|腰果|纵横|导氮|京佳|上岸鸭|格燃|步知|大树教育|优路|半月谈"), "删除其他机构名"),
    ("广告法-承诺", re.compile(r"保过|包过|必过|保分|保录|包就业|保上岸|协议班"), "删除结果承诺"),
    ("广告法-押题", re.compile(r"押题|命中|泄题|原题|内部资料|绝密|命题组|官方指定"), "删除押题/内部信息表述"),
    ("广告法-绝对", re.compile(r"100\s*%|百分之百|百分百|全国第一|全省第一|第一品牌|唯一指定"), "删除绝对化表述"),
    ("AI标识", re.compile(r"AI\s*生成|AI生成|AI\s*创作|由\s*AI|人工智能生成|AIGC|ChatGPT|大模型生成|本文由\s*AI", re.I), "删除 AI 生成标识"),
]

# ---------- WARN ----------
WARN = [
    ("极限词", re.compile(r"最好|最佳|最强|最优|最高级|顶级|国家级|世界级|绝对|独家|首发|史上|前所未有|(?:全国|全省|全市|行业|排名|销量)\s*第一|第一品牌"), "改口语化表述"),
    ("促销诱导", re.compile(r"秒杀|疯抢|最后\s*\d+\s*个|限时特价"), "删除促销诱导"),
    ("品牌用语", re.compile(r"资料|真题|上岸"), "内部规范：资料→课件、真题→历年试题、上岸→成功入围"),
]

EDU_PAT = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,6})教育")
EDU_OK = {"中公教育", "教育局", "教育部", "教育考试院", "教育部门", "教育阶段", "教育类", "学历教育"}
EDU_SUFFIX_OK = ("局", "厅", "部", "考试院", "部门", "阶段", "类", "事业", "学院")

# 数据型百分比：讲岗位事实（学历/体检/占比/人数）而非效果承诺，不算绝对化广告
DATA_CTX = re.compile(r"本科|专科|硕士|学历|岗位|专业|人数|占比|体检|色弱|色盲|禁忌|应届|往届|条件|口径")
PROMISE_CTX = re.compile(r"通过|上岸|录取|入职|就业|满意|提分|涨分|包|命中|押中")


def is_data_percent(match, line):
    return match.replace(" ", "").startswith("100%") and bool(DATA_CTX.search(line)) \
        and not PROMISE_CTX.search(line)


def iter_text_files(path):
    if os.path.isfile(path):
        yield path
        return
    for root, _, files in os.walk(path):
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in TEXT_EXT:
                yield os.path.join(root, f)


def scan_text(path, sensitive_words):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    hits = []
    for i, line in enumerate(lines, 1):
        for cat, pat, fix in BLOCK:
            for m in pat.finditer(line):
                if is_data_percent(m.group(0), line):
                    continue
                hits.append({"level": "BLOCK", "cat": cat, "match": m.group(0),
                             "line": i, "context": line.strip()[:60], "fix": fix})
        for m in EDU_PAT.finditer(line):
            full = m.group(0)
            tail = line[m.end():m.end() + 4]
            if full in EDU_OK or any(full.endswith(s) for s in EDU_SUFFIX_OK) or tail.startswith(EDU_SUFFIX_OK):
                continue
            hits.append({"level": "BLOCK", "cat": "机构名", "match": full,
                         "line": i, "context": line.strip()[:60], "fix": "删除其他机构名"})
        for cat, pat, fix in WARN:
            for m in pat.finditer(line):
                hits.append({"level": "WARN", "cat": cat, "match": m.group(0),
                             "line": i, "context": line.strip()[:60], "fix": fix})
        for w in sensitive_words:
            if w and w in line:
                hits.append({"level": "BLOCK", "cat": "敏感词", "match": w,
                             "line": i, "context": line.strip()[:60], "fix": "删除/改写"})
    # 同一行同类别的短匹配若被长匹配包含，去掉，减少噪音
    kept = []
    for h in hits:
        contained = any(o is not h and o["line"] == h["line"] and o["cat"] == h["cat"]
                        and len(o["match"]) > len(h["match"]) and h["match"] in o["match"]
                        for o in hits)
        if not contained:
            kept.append(h)
    return kept


def scan_images(path):
    from PIL import Image
    issues = []
    files = []
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path))
                 if os.path.splitext(f)[1].lower() in {".png", ".jpg", ".jpeg"}]
    elif os.path.isfile(path):
        files = [path]
    for f in files:
        try:
            im = Image.open(f)
            w, h = im.size
            # 图文 1080×1440；长图 1080 宽、高度自适应，均视为合规
            if w != 1080 or h < 1400:
                issues.append({"level": "WARN", "cat": "尺寸", "file": os.path.basename(f),
                               "detail": f"{w}x{h}，宽度应为 1080（高度 1440 为图文、更长则按长图）"})
            if im.mode == "RGBA":
                issues.append({"level": "WARN", "cat": "色彩模式", "file": os.path.basename(f),
                               "detail": "RGBA，上传前建议转 RGB"})
            if os.path.getsize(f) > 8 * 1024 * 1024:
                issues.append({"level": "WARN", "cat": "体积", "file": os.path.basename(f),
                               "detail": f"{os.path.getsize(f) // 1024 // 1024}MB，偏大"})
        except Exception as e:
            issues.append({"level": "WARN", "cat": "读取失败", "file": os.path.basename(f), "detail": str(e)})
    return issues, len(files)


def load_sensitive(path):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [str(x) for x in data]
        for key in ("words", "block", "敏感词"):
            if key in data and isinstance(data[key], list):
                return [str(x) for x in data[key]]
        return []
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description="合规扫描")
    ap.add_argument("--copy", action="append", help="文案文件或目录，可多次")
    ap.add_argument("--images", help="图片文件或目录")
    ap.add_argument("--sensitive", help="附加敏感词库 json")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败")
    ap.add_argument("--json", help="报告写入该文件")
    args = ap.parse_args()

    if not args.copy and not args.images:
        ap.error("至少提供 --copy 或 --images")

    sensitive = load_sensitive(args.sensitive)
    text_hits = []
    for p in args.copy or []:
        if not os.path.exists(p):
            raise SystemExit(f"路径不存在：{p}")
        for fp in iter_text_files(p):
            if os.path.basename(fp) == "质检报告.md":
                continue
            text_hits.extend(scan_text(fp, sensitive))

    img_hits, img_count = ([], 0)
    if args.images:
        img_hits, img_count = scan_images(args.images)

    blocks = [h for h in text_hits + img_hits if h["level"] == "BLOCK"]
    warns = [h for h in text_hits + img_hits if h["level"] == "WARN"]

    report = {
        "ok": len(blocks) == 0 and (not args.strict or len(warns) == 0),
        "text_files": sum(1 for p in (args.copy or []) if os.path.exists(p)),
        "images_checked": img_count,
        "block_count": len(blocks),
        "warn_count": len(warns),
        "blocks": blocks,
        "warns": warns[:40],
        "manual_vision_check": bool(img_count),
        "verdict": "FAIL" if blocks or (args.strict and warns) else ("WARN" if warns else "PASS"),
        "note": "图片内容需人工逐张读图确认无二维码/联系方式/其他机构水印" if img_count else "",
    }

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if blocks or (args.strict and warns):
        sys.exit(1)
    if warns:
        sys.exit(2)


if __name__ == "__main__":
    main()
