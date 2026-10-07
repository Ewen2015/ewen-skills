#!/usr/bin/env python3
"""Check a post directory against the *content* rules that render_cards.py can't see.

Usage:
    python3 check_content.py <post-dir> [--json]

render_cards.py only measures 排版（溢出／压页脚／字号下限／孤字换行）。Everything that
carries *meaning* — 半成品标记、Markdown 加粗、强调色、封面出处 — was enforced by the model
remembering to read SKILL.md, which is exactly where content drifts. This script moves the
machine-checkable subset of those rules into a gate that exits non-zero.

Rules checked (source: references/cards.md, references/copywriting.md, SKILL.md):
    1. 成品里没有半成品标记（待核实／需查证／据称…），正文与卡片一起查
    2. 正文没有 Markdown 加粗（`**字**` 在平台上会原样显示）
    3. 强调色一号是 Volvo Safety Orange #FD6408
    4. 封面素材存在、是 RGB、宽度达到交付画布下限
    5. 成品目录里只有一个标题／正文版本（没有 body-v2.txt 这类并行版本）

Not machine-checkable here, only warned about: 封面"是不是这本书真实存在的封面"——那需要
一条声明字段，见 manifest.json 的 cover.source。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HALF_BAKED = ["需查证", "待核实", "待考", "据称", "据传", "未经核对", "未逐条核对",
              "存疑", "待补", "待确认", "待定", "TODO", "TBD", "FIXME"]

ACCENT_WANT = "FD6408"
COVER_FLOOR = 900

TEXT_FILES = ["title.txt", "body.txt"]
VERSION_RE = re.compile(r"^(title|body)[-_]?v?\d+.*\.txt$", re.I)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def scan_tokens(post: Path) -> tuple[bool, str]:
    targets = [post / n for n in TEXT_FILES]
    build = post / "build"
    if build.is_dir():
        targets += sorted(build.glob("*.html"))
    hits = []
    for f in targets:
        if not f.is_file():
            continue
        txt = read(f)
        for i, line in enumerate(txt.splitlines(), 1):
            for tok in HALF_BAKED:
                if tok in line:
                    hits.append(f"{f.name}:{i} 「{tok}」")
    if hits:
        return False, "；".join(hits[:4])
    return True, f"{len([t for t in targets if t.is_file()])} 个文本文件干净"


def scan_bold(post: Path) -> tuple[bool, str]:
    hits = []
    for n in TEXT_FILES:
        txt = read(post / n)
        if "**" in txt:
            hits.append(n)
    if hits:
        return False, "、".join(hits) + " 里有 `**`（平台原样显示，不渲染加粗）"
    return True, ""


def scan_accent(post: Path) -> tuple[bool, str]:
    build = post / "build"
    css = [p for p in ([build / "card.css"] if build.is_dir() else [])
           + (sorted(build.glob("*.css")) if build.is_dir() else [])]
    css = list(dict.fromkeys(css))
    seen = []
    for f in css:
        if not f.is_file():
            continue
        for m in re.finditer(r"--accent\s*:\s*(#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3})", read(f)):
            seen.append((f.name, m.group(1).lstrip("#").upper()))
    if not seen:
        return False, "build/ 里找不到 --accent 定义，强调色没验过"
    bad = [f"{n}={v}" for n, v in seen if v != ACCENT_WANT]
    if bad:
        return False, f"强调色不是 #{ACCENT_WANT}（{'、'.join(bad)}）——不要用绿色或别的色"
    return True, f"# {ACCENT_WANT}（{seen[0][0]}）"


def png_size(path: Path) -> tuple[int, int, str] | None:
    try:
        head = path.read_bytes()[:33]
    except OSError:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w = int.from_bytes(head[16:20], "big")
    h = int.from_bytes(head[20:24], "big")
    ctype = head[25]
    kind = {0: "gray", 2: "RGB", 3: "palette", 4: "gray+alpha", 6: "RGBA"}.get(ctype, f"type{ctype}")
    return w, h, kind


def image_probe(path: Path) -> tuple[int | None, str | None]:
    png = png_size(path)
    if png:
        return png[0], png[2]
    try:
        from PIL import Image
    except ImportError:
        return None, None
    try:
        with Image.open(path) as im:
            return im.width, im.mode
    except Exception:
        return None, None


def scan_cover(post: Path, manifest: dict) -> tuple[bool, str, str | None]:
    assets = post / "assets"
    cands = [assets / "cover-src.png", assets / "subject.png",
             assets / "cover.png", assets / "cover.jpg"]
    src = next((c for c in cands if c.is_file()), None)
    if src is None:
        return False, "assets/ 里没有封面素材（cover-src.png / subject.png）", None
    w, mode = image_probe(src)
    if w is None:
        return False, f"{src.name} 读不出尺寸或格式不认", None
    m = (mode or "").upper()
    if m and (m in ("RGBA", "LA", "PA", "CMYK", "P", "PALETTE") or "ALPHA" in m):
        return False, f"{src.name} 是 {mode}，封面要 RGB（不要 alpha／CMYK）", None
    if w < COVER_FLOOR:
        return False, f"{src.name} 宽 {w}px，低于交付画布下限 {COVER_FLOOR}px", None
    note = None
    cov = manifest.get("cover") if isinstance(manifest, dict) else None
    if not (isinstance(cov, dict) and str(cov.get("source") or "").strip()):
        note = 'manifest.json 没有 cover.source——封面"是不是真封面"没法自动判，补一条声明'
    return True, f"{src.name} {w}px {mode}", note


def scan_versions(post: Path) -> tuple[bool, str]:
    extra = [f.name for f in post.iterdir()
             if f.is_file() and f.suffix.lower() == ".txt"
             and VERSION_RE.match(f.name)]
    if extra:
        return False, "有并行版本：" + "、".join(sorted(extra)) + "（只留一个版本）"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("post", help="成品目录（含 title.txt/body.txt/build/）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    post = Path(args.post).expanduser().resolve()
    if not post.is_dir():
        print(f"没有这个目录：{post}", file=sys.stderr)
        return 2

    manifest = {}
    mf = post / "manifest.json"
    if mf.is_file():
        try:
            manifest = json.loads(read(mf))
        except json.JSONDecodeError:
            manifest = {}

    checks: list[dict] = []
    warns: list[str] = []

    def add(name: str, ok: bool, detail: str = ""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("成品无半成品标记", *scan_tokens(post))
    add("正文无 Markdown 加粗", *scan_bold(post))
    add("强调色是 #FD6408", *scan_accent(post))
    ok, detail, note = scan_cover(post, manifest)
    add("封面素材可用（RGB／宽度）", ok, detail)
    if note:
        warns.append(note)
    add("只有一个版本", *scan_versions(post))

    passed = all(c["ok"] for c in checks)
    rep = {"post": str(post), "pass": passed, "checks": checks, "warnings": warns}

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        for c in checks:
            print(f"{'✓' if c['ok'] else '✗'} {c['name']}" + (f" —— {c['detail']}" if c["detail"] else ""))
        for w in warns:
            print(f"⚠ {w}")
        print("内容合规：全过" if passed else "内容合规：有不过的")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
