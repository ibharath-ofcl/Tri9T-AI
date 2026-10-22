#!/usr/bin/env python3
"""Diagnostic PDF inspection utility for CT-200 manuals.

Reports page counts, font metadata, character/word statistics,
table detections (with phantom filtering flags), and extraction health.

Usage:
    python -m scripts.inspect_manual data/ct200_manual.pdf
    python scripts/inspect_manual.py data/ct200_manual_v2.pdf
"""

import sys
import json
from pathlib import Path
from typing import Any, Dict, List
import pdfplumber
from pypdf import PdfReader


def is_phantom_table(table_data: List[List[Any]]) -> bool:
    """Assess if a detected table is likely a phantom/cell fragment.

    Criteria:
      - Less than 2 rows
      - Only 1 column
      - Extreme sparsity (more than 50% None/empty cells)
    """
    if not table_data or len(table_data) < 2:
        return True
    
    col_counts = [len(row) for row in table_data if row]
    if not col_counts or max(col_counts) < 2:
        return True

    total_cells = sum(len(row) for row in table_data)
    if total_cells == 0:
        return True
    empty_cells = sum(1 for row in table_data for c in row if c is None or str(c).strip() == "")
    if empty_cells / total_cells > 0.6:
        return True

    return False


def inspect_pdf(file_path: Path) -> Dict[str, Any]:
    """Inspect a PDF manual and extract diagnostic metadata."""
    if not file_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {file_path}")

    # Basic pypdf metadata check
    reader = PdfReader(str(file_path))
    pypdf_page_count = len(reader.pages)
    metadata = {k: str(v) for k, v in (reader.metadata or {}).items()}

    pages_report = []
    total_characters = 0
    total_words = 0
    all_fonts_seen = set()
    warnings = []

    with pdfplumber.open(file_path) as pdf:
        plumber_page_count = len(pdf.pages)

        for idx, page in enumerate(pdf.pages):
            pnum = idx + 1
            raw_text = page.extract_text() or ""
            chars = page.chars
            words = page.extract_words(extra_attrs=["fontname", "size"])

            char_count = len(chars)
            word_count = len(words)
            text_length = len(raw_text)

            total_characters += char_count
            total_words += word_count

            # Font breakdown for this page
            page_fonts: Dict[str, int] = {}
            for c in chars:
                fname = c.get("fontname", "unknown")
                fsize = round(c.get("size", 0), 1)
                key = f"{fname}@{fsize}pt"
                page_fonts[key] = page_fonts.get(key, 0) + 1
                all_fonts_seen.add(key)

            # Sort top fonts
            sorted_fonts = sorted(page_fonts.items(), key=lambda x: x[1], reverse=True)

            # Table candidates detection
            raw_tables = page.find_tables()
            table_candidates = []
            for t_idx, t in enumerate(raw_tables):
                t_data = t.extract()
                rows = len(t_data) if t_data else 0
                cols = max(len(r) for r in t_data) if (t_data and rows > 0) else 0
                phantom = is_phantom_table(t_data)
                table_candidates.append({
                    "table_index": t_idx + 1,
                    "rows": rows,
                    "columns": cols,
                    "bbox": [round(b, 1) for b in t.bbox],
                    "is_likely_phantom": phantom,
                    "preview": [t_data[0]] if t_data else [],
                })

            # Check for suspicious low-text page
            is_usable = text_length > 20
            is_suspiciously_low = 0 < text_length < 120
            if is_suspiciously_low:
                warnings.append(
                    f"Page {pnum} has suspiciously low text length ({text_length} chars). "
                    "May be an overflow or trailing fragment."
                )
            elif not is_usable:
                warnings.append(
                    f"Page {pnum} contains negligible or unextractable text ({text_length} chars). "
                    "May be blank or require OCR inspection."
                )

            pages_report.append({
                "page_number": pnum,
                "character_count": char_count,
                "word_count": word_count,
                "text_length": text_length,
                "has_usable_text": is_usable,
                "is_suspicious_low_text": is_suspiciously_low,
                "fonts": sorted_fonts[:5],
                "tables_detected_count": len(raw_tables),
                "table_candidates": table_candidates,
                "text_preview": raw_text[:160].replace("\n", " ").strip() + ("..." if len(raw_text) > 160 else "")
            })

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "file_size_bytes": file_path.stat().st_size,
        "pypdf_page_count": pypdf_page_count,
        "pdfplumber_page_count": plumber_page_count,
        "total_characters": total_characters,
        "total_words": total_words,
        "unique_fonts": sorted(list(all_fonts_seen)),
        "metadata": metadata,
        "warnings": warnings,
        "pages": pages_report,
    }


def print_summary(report: Dict[str, Any]) -> None:
    """Print human-readable summary of the inspection."""
    print("=" * 70)
    print(f"CT-200 MANUAL INSPECTION: {report['file_name']}")
    print(f"Path: {report['file_path']} ({report['file_size_bytes']} bytes)")
    print(f"Pages: {report['pdfplumber_page_count']} | Chars: {report['total_characters']} | Words: {report['total_words']}")
    print("=" * 70)

    print("\n--- PER-PAGE SUMMARY ---")
    for p in report["pages"]:
        status = "OK" if p["has_usable_text"] and not p["is_suspicious_low_text"] else "FLAGGED"
        print(f"Page {p['page_number']:2d}: [{status:7s}] chars={p['character_count']:4d}, words={p['word_count']:3d}, tables={p['tables_detected_count']}")
        if p["fonts"]:
            font_str = ", ".join(f"{f[0]} ({f[1]})" for f in p["fonts"][:2])
            print(f"         Primary fonts: {font_str}")
        if p["table_candidates"]:
            for t in p["table_candidates"]:
                ph = " (LIKELY PHANTOM)" if t["is_likely_phantom"] else " (VALID CANDIDATE)"
                print(f"         Table {t['table_index']}: {t['rows']}x{t['columns']}{ph} at bbox {t['bbox']}")
        print(f"         Preview: \"{p['text_preview']}\"")

    if report["warnings"]:
        print("\n--- WARNINGS & ANOMALIES ---")
        for w in report["warnings"]:
            print(f"  * {w}")
    else:
        print("\n--- NO PAGE-LEVEL WARNINGS ---")

    print("\n" + "=" * 70)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.inspect_manual <path-to-pdf>")
        sys.exit(1)

    target_path = Path(sys.argv[1])
    try:
        report = inspect_pdf(target_path)
        print_summary(report)
    except Exception as e:
        print(f"Error inspecting PDF {target_path}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
