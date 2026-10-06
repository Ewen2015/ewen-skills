#!/usr/bin/env python3
"""Extract page-anchored text and a table of contents from a book file.

Usage:
    python3 extract_book_text.py BOOK [--out FILE] [--toc-only]

BOOK is a .pdf or .epub file. The extracted text is written with `===PAGE n===`
anchors so notes and quotes can cite a location and the reader can go back to
it. The table of contents is printed to stdout.

For PDF it uses PyMuPDF when available, otherwise poppler's `pdftotext`. For a
scanned PDF with no text layer the output is nearly empty; run
`ocr_scanned_pdf.py` (same directory) instead — it probes the text layer first and
falls back to Apple Vision OCR, emitting the same `<<<PDFPAGE n>>>` page anchors.
"""

import argparse
import html
import posixpath
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

PAGE_ANCHOR = "===PAGE {n}==="


def extract_pdf(path):
    """Return (toc, pages). toc entries are (level, title, page)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return extract_pdf_poppler(path)

    fitz.TOOLS.mupdf_display_errors(False)
    with fitz.open(path) as doc:
        toc = [
            (level, title.strip(), page)
            for level, title, page in doc.get_toc()
        ]
        pages = [page.get_text() for page in doc]
    return toc, pages


def extract_pdf_poppler(path):
    exe = shutil.which("pdftotext")
    if not exe:
        sys.exit(
            "No PDF text extractor available. Install PyMuPDF "
            "(`pip install pymupdf`) or poppler (`brew install poppler`), "
            "or run ocr_scanned_pdf.py (Apple Vision OCR fallback)."
        )
    result = subprocess.run(
        [exe, "-layout", "-enc", "UTF-8", str(path), "-"],
        capture_output=True,
    )
    if result.returncode != 0:
        sys.exit(f"pdftotext failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    pages = result.stdout.decode("utf-8", "replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return [], pages


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def extract_epub(path):
    """Return ([], sections). Sections follow the EPUB spine order."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        opf_path = _find_opf(archive)
        base = posixpath.dirname(opf_path)
        root = ET.fromstring(archive.read(opf_path))

        manifest = {
            element.get("id"): element.get("href")
            for element in root.iter()
            if _local_name(element.tag) == "item"
        }
        order = []
        for element in root.iter():
            if _local_name(element.tag) != "itemref":
                continue
            href = manifest.get(element.get("idref"))
            if href:
                resolved = posixpath.normpath(posixpath.join(base, href))
                if resolved in names:
                    order.append(resolved)

        sections = [
            _html_to_text(archive.read(name).decode("utf-8", "replace"))
            for name in order
        ]
    return [], sections


def _find_opf(archive):
    try:
        container = archive.read("META-INF/container.xml").decode("utf-8", "replace")
    except KeyError:
        sys.exit("Not a valid EPUB: META-INF/container.xml is missing.")
    match = re.search(r'full-path="([^"]+)"', container)
    if not match:
        sys.exit("Not a valid EPUB: no rootfile listed in container.xml.")
    return match.group(1)


def _html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(
        r"(?i)</?(p|div|br|li|h[1-6]|tr|section|article|blockquote)[^>]*>",
        "\n",
        raw,
    )
    raw = re.sub(r"(?s)<[^>]+>", "", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("book", help="path to a .pdf or .epub file")
    parser.add_argument("--out", help="where to write the text (default: <book>.txt)")
    parser.add_argument(
        "--toc-only", action="store_true", help="print the table of contents only"
    )
    args = parser.parse_args()

    path = Path(args.book).expanduser()
    if not path.is_file():
        sys.exit(f"No such file: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        toc, sections = extract_pdf(path)
        unit = "pages"
    elif suffix == ".epub":
        toc, sections = extract_epub(path)
        unit = "sections"
    else:
        sys.exit(f"Unsupported format: {suffix} (expected .pdf or .epub)")

    if toc:
        print(f"Table of contents ({len(toc)} entries)")
        for level, title, page in toc:
            indent = "  " * max(level - 1, 0)
            location = f"  [p.{page}]" if page else ""
            print(f"{indent}{title}{location}")
    else:
        print("Table of contents: none available for this file")

    if args.toc_only:
        return

    out_path = Path(args.out).expanduser() if args.out else path.with_suffix(".txt")
    body = "\n\n".join(
        f"{PAGE_ANCHOR.format(n=index)}\n{text.strip()}"
        for index, text in enumerate(sections, 1)
    )
    out_path.write_text(body, encoding="utf-8")

    total = sum(len(text) for text in sections)
    print(f"\nWrote {out_path} ({len(sections)} {unit}, {total} chars)")
    if suffix == ".pdf" and sections and total / len(sections) < 50:
        print(
            "Warning: very little text per page. This PDF is probably a scan "
            "with no text layer; run ocr_scanned_pdf.py instead.",
            file=sys.stderr,
        )
    if suffix == ".epub":
        print("Note: EPUB anchors follow spine order, not printed page numbers.")


if __name__ == "__main__":
    main()
