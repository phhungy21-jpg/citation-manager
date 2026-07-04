#!/usr/bin/env python3
"""
pdf_to_md.py — Convert a published paper's PDF to Markdown for claim extraction.

Standalone port of Toolbox/convert_pdf_to_md.py's core logic (pymupdf4llm
extraction + academic-paper header/footer cleanup), vendored here so
citation-pipeline has no dependency on the Toolbox/doctools package — keeps
this repo self-contained for the GitHub push.

Usage:
    python pdf_to_md.py paper.pdf                    # writes paper.md next to it
    python pdf_to_md.py paper.pdf --output out.md
    python pdf_to_md.py paper.pdf --out-dir data/manuscripts/
"""

import argparse
import re
import sys
from pathlib import Path


def clean_markdown(text: str) -> str:
    """Strip repeated running headers/footers and lone page numbers."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(?m)^\s*\d{1,4}\s*$', '', text)
    lines = text.split('\n')
    line_counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if 2 <= len(stripped) <= 80:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1
    repeated = {line for line, count in line_counts.items() if count >= 3}
    cleaned_lines = [line for line in lines if line.strip() not in repeated]
    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def pdf_to_markdown(pdf_path: Path) -> str:
    """Extract text from a PDF as Markdown via pymupdf4llm, then clean it."""
    import pymupdf4llm
    raw = pymupdf4llm.to_markdown(
        str(pdf_path),
        show_progress=False,
        write_images=False,
        embed_images=False,
        page_chunks=False,
        margins=0,
    )
    return clean_markdown(raw)


def convert(pdf_path: Path, out_path: Path, overwrite: bool = False) -> Path:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a .pdf file, got '{pdf_path.suffix}'")
    if out_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists (use --overwrite): {out_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = pdf_to_markdown(pdf_path)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", help="Path to the input PDF")
    parser.add_argument("--output", default=None, help="Explicit output .md path")
    parser.add_argument("--out-dir", default=None, help="Directory to write <stem>.md into")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)

    if args.output:
        out_path = Path(args.output)
    elif args.out_dir:
        out_path = Path(args.out_dir) / (pdf_path.stem + ".md")
    else:
        out_path = pdf_path.with_suffix(".md")

    print(f"Converting: {pdf_path.name}")
    try:
        convert(pdf_path, out_path, overwrite=args.overwrite)
    except (FileNotFoundError, ValueError, FileExistsError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    size_kb = out_path.stat().st_size / 1024
    line_count = out_path.read_text(encoding="utf-8").count("\n")
    print(f"Done.\nOutput : {out_path}\nSize   : {size_kb:.1f} KB\nLines  : {line_count:,}")


if __name__ == "__main__":
    main()
