#!/usr/bin/env python3
"""OCR a scanned PDF into page-anchored text, using only what macOS ships.

Usage:
    python3 ocr_scanned_pdf.py BOOK [--out FILE] [--dpi 250] [--force]

Why this exists: `extract_book_text.py` reads a PDF's *text layer*. A scanned
book has none, so it returns almost nothing — and the failure is quiet, not
loud (every page just comes back empty). This is the fallback: render each
page to an image, run Apple's Vision OCR over it, and emit the same
`<<<PDFPAGE n>>>` anchors so notes can still cite a page.

Nothing needs installing. Vision is part of macOS; the only build step is
compiling the bundled `vision_ocr.swift` once into a cache directory.

Measured 2026-10: 216 pages at 250 dpi render in ~16s and OCR in ~53s
(Apple silicon, zh-Hans + en-US). 350 dpi bought no accuracy over 250.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SWIFT_SRC = HERE / "vision_ocr.swift"
CACHE = Path(os.environ.get("READ_A_BOOK_CACHE", Path.home() / ".cache" / "read-a-book"))

CHUNK = 40          # pages per OCR invocation: bounds argv length and peak memory
PROBE_PAGES = 12    # how many pages to sample when deciding "does it have text?"
MIN_CHARS_PER_PAGE = 50   # below this, assume the text layer is absent or useless


def die(msg: str, code: int = 2):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def probe_text_layer(path: Path) -> tuple[int, int, float]:
    """Return (pages, sampled, chars-per-page). No fitz -> cannot judge."""
    try:
        import fitz
    except ImportError:
        die("需要 PyMuPDF（fitz）来渲染页面：python3 -m pip install pymupdf")
    with fitz.open(path) as doc:
        pages = doc.page_count
        sampled = min(PROBE_PAGES, pages)
        total = sum(len(doc[i].get_text().strip()) for i in range(sampled))
    return pages, sampled, (total / sampled if sampled else 0.0)


def build_ocr_tool() -> Path:
    """Compile the bundled Swift source once; reuse the binary afterwards."""
    exe = CACHE / "bin" / "vision_ocr"
    if exe.exists() and exe.stat().st_mtime >= SWIFT_SRC.stat().st_mtime:
        return exe
    if not SWIFT_SRC.exists():
        die(f"找不到 {SWIFT_SRC}")
    exe.parent.mkdir(parents=True, exist_ok=True)
    print("首次使用，正在编译 Vision OCR 小工具…", file=sys.stderr)
    r = subprocess.run(["swiftc", "-O", str(SWIFT_SRC), "-o", str(exe)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die(f"swiftc 编译失败：\n{r.stderr.strip()}\n"
            "（需要 Xcode Command Line Tools：xcode-select --install）")
    return exe


def render_pages(path: Path, outdir: Path, dpi: int, pages: int) -> list[Path]:
    import fitz
    outdir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    made: list[Path] = []
    with fitz.open(path) as doc:
        for i in range(pages):
            png = outdir / f"p{i + 1:04d}.png"
            # Grayscale: the OCR does not use colour, and this halves the bytes.
            pix = doc[i].get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            pix.save(png)
            made.append(png)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description="把扫描版 PDF 用 macOS Vision OCR 成带页锚的文本")
    ap.add_argument("book", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dpi", type=int, default=250)
    ap.add_argument("--force", action="store_true",
                    help="即使检测到文字层也照样 OCR")
    ap.add_argument("--probe-only", action="store_true",
                    help="只报告文字层情况，不做 OCR")
    args = ap.parse_args()

    book: Path = args.book
    if not book.exists():
        die(f"文件不存在：{book}")
    if sys.platform != "darwin":
        die("这条路子依赖 macOS 的 Vision 框架；其他平台请用 tesseract/ocrmypdf")

    pages, sampled, cpp = probe_text_layer(book)
    print(f"文字层探测：{pages} 页，抽样 {sampled} 页，平均 {cpp:.0f} 字/页")
    if args.probe_only:
        print("结论：" + ("疑似扫描件，需要 OCR" if cpp < MIN_CHARS_PER_PAGE else "有文字层，走 extract_book_text.py"))
        return 0
    if cpp >= MIN_CHARS_PER_PAGE and not args.force:
        print(f"这份 PDF 看起来有文字层（{cpp:.0f} 字/页 ≥ {MIN_CHARS_PER_PAGE}）。"
              "先跑 extract_book_text.py；确实要 OCR 就加 --force。")
        return 0

    out = args.out or book.with_suffix(".ocr.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    exe = build_ocr_tool()

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ocr-pages-") as tmp:
        tmpdir = Path(tmp)
        print(f"渲染 {pages} 页 @ {args.dpi}dpi…", file=sys.stderr)
        imgs = render_pages(book, tmpdir, args.dpi, pages)
        print(f"  渲染完成 {time.monotonic() - t0:.0f}s", file=sys.stderr)

        chunks: list[Path] = []
        ocr_start = time.monotonic()
        for start in range(0, len(imgs), CHUNK):
            batch = imgs[start:start + CHUNK]
            cf = tmpdir / f"ocr_{start // CHUNK:03d}.txt"
            r = subprocess.run([str(exe), str(cf), str(start + 1)] + [str(p) for p in batch],
                               capture_output=True, text=True)
            if r.returncode != 0:
                die(f"OCR 第 {start + 1}–{start + len(batch)} 页失败：{r.stderr.strip()}")
            chunks.append(cf)
            print(f"  OCR {start + len(batch)}/{pages}", file=sys.stderr)

        text = "".join(cf.read_text(encoding="utf-8") for cf in chunks)

    out.write_text(text, encoding="utf-8")
    print(f"已写出 {out}（{len(text)} 字，{text.count(chr(10)) + 1} 行；"
          f"渲染 {ocr_start - t0:.0f}s + OCR {time.monotonic() - ocr_start:.0f}s）")
    print("下一步：用 read-a-book 的读法通读；引用按 <<<PDFPAGE n>>> 定位。")
    print("提示：页眉页脚（书名／数字页码）会混进正文，读到时要自行忽略。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
