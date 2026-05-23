#!/usr/bin/env python3
"""OCR pass on scanned syllabus PDFs to recover ECTS values not extractable
by direct pdftotext.

Identifies syllabus PDFs in paper/data/naqa/data/downloads/ that contain
no machine-readable text (lines<5 from `pdftotext`). For each such PDF,
rasterises the first 3 pages with pdftoppm at 200 dpi and runs tesseract
with the Ukrainian language pack (-l ukr). Applies the same fifteen
ECTS-disclosure regular-expression patterns as 10_extract_ects.py and
records the result.

Output: appends to paper/data/naqa/ocr_extraction.json with one record
per OCR'd component:
  {"case_id": "...", "component_dir": "...", "pdf": "...",
   "ocr_text_excerpt": "...", "ects": float|null}

Stats are printed to stdout. Run after 10_extract_ects.py.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWN = ROOT / "data" / "naqa" / "data" / "downloads"
OUT = ROOT / "data" / "naqa" / "ocr_extraction.json"

# Same patterns as 10_extract_ects.py
_E = r"(?:ECTS|ЄКТС|EКTC|EKTC)"
_SEP = r"[\s_:\-–]+"
ECTS_PATTERNS = [
    re.compile(rf"К[іи]льк[іи]сть\s*кредит[іи]в{_SEP}{_E}{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(rf"Загальн(?:а|ий)\s*к[іи]льк[іи]сть\s*кредит[іи]в{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(rf"К[іи]льк[іи]сть\s*кредит[іи]в{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(rf"Кредит[иі]в?\s*{_E}{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(rf"{_E}\s*кредит[іи]в?{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    re.compile(r"Обсяг.{0,40}?(\d+(?:[.,]\d+)?)\s*кред", re.IGNORECASE),
    re.compile(rf"(\d+(?:[.,]\d+)?)\s*кред[\.\s]+{_E}", re.IGNORECASE),
    re.compile(rf"\((\d+(?:[.,]\d+)?)\s*кредит[іи]?\s*{_E}", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*кредит[іи]в?\s*\\\s*\d+\s*год", re.IGNORECASE),
    re.compile(r"\d+\s*год[\.\s]*/\s*(\d+(?:[.,]\d+)?)\s*кредит", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*кредит[іи]?[вао]?\s*[\-–]\s*\d+\s*годин", re.IGNORECASE),
    re.compile(r"\d+\s*/\s*(\d+(?:[.,]\d+)?)\s*кр\.", re.IGNORECASE),
    re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*\d+\s*год\.", re.IGNORECASE),
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s*кр\.", re.IGNORECASE),
    re.compile(rf"{_E}\s+годин.{{0,300}}?\b(\d+(?:[.,]\d+)?)\s+\d{{3}}\b",
               re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s*кред[итьаів\.]{0,8}\b", re.IGNORECASE),
]


def is_scanned(pdf: Path, threshold: int = 5) -> bool:
    """A PDF is treated as scanned (image-only) if pdftotext yields fewer
    than `threshold` non-empty lines."""
    try:
        out = subprocess.run(
            ["pdftotext", str(pdf), "-"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    lines = [ln for ln in out.splitlines() if ln.strip()]
    return len(lines) < threshold


def ocr_pdf(pdf: Path, pages: int = 3, dpi: int = 200) -> str:
    """OCR the first `pages` pages of `pdf` via pdftoppm + tesseract -l ukr."""
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        # Rasterise
        try:
            subprocess.run(
                ["pdftoppm", "-r", str(dpi), "-f", "1", "-l", str(pages),
                 str(pdf), str(td_p / "p")],
                capture_output=True, timeout=60, check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        # OCR each page
        text_parts = []
        for ppm in sorted(td_p.glob("p-*.ppm")):
            try:
                r = subprocess.run(
                    ["tesseract", str(ppm), "-", "-l", "ukr"],
                    capture_output=True, text=True, timeout=90, check=False,
                )
                text_parts.append(r.stdout)
            except subprocess.TimeoutExpired:
                continue
        return "\n".join(text_parts)


def extract_ects(text: str):
    for pat in ECTS_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                v = float(m.group(1).replace(",", "."))
                if 0.5 <= v <= 30:
                    return v
            except ValueError:
                continue
    return None


def main() -> int:
    cases = sorted(DOWN.iterdir())
    scanned = []
    for case_dir in cases:
        if not case_dir.is_dir():
            continue
        comps_dir = case_dir / "components"
        if not comps_dir.exists():
            continue
        for pdf in comps_dir.rglob("*.pdf"):
            if is_scanned(pdf):
                scanned.append((case_dir.name, pdf))

    print(f"[12] Found {len(scanned)} scanned PDFs across all cases")
    by_case = {}
    for cid, _ in scanned:
        by_case[cid] = by_case.get(cid, 0) + 1
    for cid, n in sorted(by_case.items()):
        print(f"[12]   case {cid}: {n} scanned PDFs")

    results = []
    extracted = 0
    for i, (case_id, pdf) in enumerate(scanned, 1):
        comp_dir = pdf.parent.name
        sys.stdout.write(f"\r[12] OCR {i:>3d}/{len(scanned)}: {case_id}/{comp_dir[:50]}")
        sys.stdout.flush()
        text = ocr_pdf(pdf, pages=3)
        ects = extract_ects(text) if text else None
        results.append({
            "case_id": case_id,
            "component_dir": comp_dir,
            "pdf": str(pdf.relative_to(ROOT)),
            "ocr_chars": len(text or ""),
            "ects": ects,
            "ocr_excerpt": (text[:300] if text else "")
                           .replace("\n", " ").strip(),
        })
        if ects is not None:
            extracted += 1
    print()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"[12] Extracted ECTS from {extracted}/{len(scanned)} scanned PDFs"
          f" ({100*extracted/max(1,len(scanned)):.1f}%)")
    print(f"[12] Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
