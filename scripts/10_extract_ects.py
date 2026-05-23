#!/usr/bin/env python3
"""Extract per-component ECTS from NAQA-downloaded syllabus PDFs.

Walks paper/data/naqa/data/downloads/{case_id}/components/<component_dir>/*.pdf,
runs pdftotext, and looks for the canonical "Kilkist kredytiv" (Number of
ECTS credits) field that Ukrainian university syllabi expose in their
front-matter. Aggregates credits per case by the same five-category scheme
as 08_populate_opp.py (subject / pedagogy / practicum / statutory / other).

Outputs paper/tables/tbl_opp_ects_analysis.tex and prints per-case totals
to stdout. Components with no extractable ECTS are reported separately;
the analysis runs on whatever fraction of the 755 syllabi yield a value.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "naqa" / "data" / "raw"
DOWN = ROOT / "data" / "naqa" / "data" / "downloads"
OUT = ROOT / "tables" / "tbl_opp_ects_analysis.tex"
OCR_CACHE = ROOT / "data" / "naqa" / "ocr_extraction.json"


def load_ocr_cache():
    """Load OCR-extracted ECTS values (produced by 12_ocr_pass.py).

    Returns a dict keyed by (case_id, component_dir) -> ects float.
    Missing cache file -> empty dict.
    """
    if not OCR_CACHE.exists():
        return {}
    try:
        records = json.loads(OCR_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for r in records:
        if r.get("ects") is not None:
            out[(r["case_id"], r["component_dir"])] = r["ects"]
    return out


_OCR_CACHE = None


def ocr_lookup(case_id: str, component_dir_name: str):
    global _OCR_CACHE
    if _OCR_CACHE is None:
        _OCR_CACHE = load_ocr_cache()
    return _OCR_CACHE.get((case_id, component_dir_name))

# Categorisation regex (mirror of 08_populate_opp.py for consistency)
PEDAGOGY = re.compile(r"\b(педагог|психолог|методик|дидакт|курсова|підсумков|атестац)", re.IGNORECASE)
PRACTICUM = re.compile(r"\b(практик|стаж)", re.IGNORECASE)
STATUTORY = re.compile(
    r"\b(БЖД|корекц|охорон.{1,8}прац|анти.?коруп|військов|"
    r"громадянськ\sзахист|надзвичайн.{0,15}ситуац|"
    r"інклюзивн.{0,15}освіт)",
    re.IGNORECASE,
)

# Generic shorthand: "ECTS" in Latin OR "ЄКТС" in Cyrillic
_E = r"(?:ECTS|ЄКТС|EКTC)"
_SEP = r"[\s_:\-–]+"

# ECTS extraction patterns: handles several common Ukrainian syllabus formats.
# Order matters: most specific first. Number can be int or decimal (3, 3.0, 4,5).
ECTS_PATTERNS = [
    # "Кількість кредитів ECTS: 3" or "Кількість кредитів ЄКТС  4"
    re.compile(rf"К[іи]льк[іи]сть\s*кредит[іи]в{_SEP}{_E}{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    # "Загальна кількість кредитів: 3"
    re.compile(rf"Загальн(?:а|ий)\s*к[іи]льк[іи]сть\s*кредит[іи]в{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    # "Кількість кредитів: 3" or "Кількість кредитів_3"
    re.compile(rf"К[іи]льк[іи]сть\s*кредит[іи]в{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    # "Кредитів ECTS: 3" or "Кредити ЄКТС: 3"
    re.compile(rf"Кредит[иі]в?\s*{_E}{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    # "ECTS кредитів: 3"
    re.compile(rf"{_E}\s*кредит[іи]в?{_SEP}(\d+(?:[.,]\d+)?)", re.IGNORECASE),
    # "Обсяг ... становить 10 кред." or "Обсяг 3 кредит"
    re.compile(r"Обсяг.{0,40}?(\d+(?:[.,]\d+)?)\s*кред", re.IGNORECASE),
    # "10 кред. ЄКТС"
    re.compile(rf"(\d+(?:[.,]\d+)?)\s*кред[\.\s]+{_E}", re.IGNORECASE),
    # Parenthesized "(4 кредити ECTS (120 годин))" - case 16344
    re.compile(rf"\((\d+(?:[.,]\d+)?)\s*кредит[іи]?\s*{_E}", re.IGNORECASE),
    # "3 кредитів \ 90 год" - backslash-separated case 16344
    re.compile(r"(\d+(?:[.,]\d+)?)\s*кредит[іи]в?\s*\\\s*\d+\s*год", re.IGNORECASE),
    # "X год. / Y кредит" -> take Y
    re.compile(r"\d+\s*год[\.\s]*/\s*(\d+(?:[.,]\d+)?)\s*кредит", re.IGNORECASE),
    # "Тривалість ... N кредити – M годин" -> take N
    re.compile(r"(\d+(?:[.,]\d+)?)\s*кредит[іи]?[вао]?\s*[\-–]\s*\d+\s*годин", re.IGNORECASE),
    # "Кількість часу на вивчення – N кредитів" (Hlukhiv NPU)
    re.compile(r"К[іи]льк[іи]сть\s+часу.{0,40}?[\-–]\s*(\d+(?:[.,]\d+)?)\s*кредит", re.IGNORECASE),
    # "90/3 кр." or "90 / 3 кр." - hours/credits combined cell (Melitopol)
    re.compile(r"\d+\s*/\s*(\d+(?:[.,]\d+)?)\s*кр\.", re.IGNORECASE),
    # "9 / 270 год." - credits/hours combined cell (Berdyansk style)
    re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*\d+\s*год\.", re.IGNORECASE),
    # Multi-line table: "ЄКТС  годин ..." header, then data row "6  180" (case 16176)
    # First number is credits (1-30), second is hours (3-digit).
    re.compile(rf"{_E}\s+годин.{{0,300}}?\b(\d+(?:[.,]\d+)?)\s+\d{{3}}\b",
               re.IGNORECASE | re.DOTALL),
    # "3 кр." or "3 кр" abbreviated form (Melitopol-style)
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s*кр\.", re.IGNORECASE),
    # Trailing fallback: "3 кредити" or "3 кред." within first page (less reliable)
    re.compile(r"\b(\d+(?:[.,]\d+)?)\s*кред[итьаів\.]{0,8}\b", re.IGNORECASE),
]


def categorise(name: str) -> str:
    n = name or ""
    if PRACTICUM.search(n):
        return "practicum"
    if STATUTORY.search(n):
        return "statutory"
    if PEDAGOGY.search(n):
        return "pedagogy"
    return "subject"


def extract_ects(pdf_path: Path) -> float | None:
    """Extract first plausible ECTS value (1-30) from PDF.

    Searches the first 5 pages (some Melitopol-style syllabi place the credit
    field after a multi-page front-matter / SDG block). Falls back to the
    full text if the first 5 pages yield nothing.
    """
    for page_limit in (5, None):
        cmd = ["pdftotext", "-layout"]
        if page_limit:
            cmd += ["-f", "1", "-l", str(page_limit)]
        cmd += [str(pdf_path), "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        text = out.stdout
        if not text:
            continue
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


def institution_short(case: dict) -> str:
    fs = case.get("form_se") or {}
    if not fs.get("tabs"):
        return "—"
    fields = fs["tabs"][0].get("all_fields", {}) or {}
    name = fields.get("Реєстраційний номер ЗВО у ЄДЕБО") or ""
    UA = {"а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ye","ж":"zh","з":"z",
          "и":"y","і":"i","ї":"yi","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p",
          "р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch",
          "ь":"","ю":"yu","я":"ya","'":"'","А":"A","Б":"B","В":"V","Г":"H","Ґ":"G","Д":"D",
          "Е":"E","Є":"Ye","Ж":"Zh","З":"Z","И":"Y","І":"I","Ї":"Yi","Й":"Y","К":"K","Л":"L",
          "М":"M","Н":"N","О":"O","П":"P","Р":"R","С":"S","Т":"T","У":"U","Ф":"F","Х":"Kh",
          "Ц":"Ts","Ч":"Ch","Ш":"Sh","Щ":"Shch","Ь":"","Ю":"Yu","Я":"Ya"}
    n = "".join(UA.get(c, c if ord(c) < 128 else "?") for c in name)
    n = n.replace("Natsionalnyy universytet", "NU")
    n = re.sub(r"imeni\s+|im\.\s*", "", n)
    n = re.sub(r"\s+", " ", n).strip().rstrip(' "\'').replace('"', "")
    return (n[:30] + "...") if len(n) > 32 else n


def process_case(case_id: str, comps: list) -> dict:
    """Walk the case's downloads/components/ subdirectories and total ECTS by category."""
    case_dir = DOWN / case_id / "components"
    totals = {"subject": 0.0, "pedagogy": 0.0, "practicum": 0.0,
              "statutory": 0.0, "other": 0.0}
    counts = {"subject": 0, "pedagogy": 0, "practicum": 0,
              "statutory": 0, "other": 0}  # extracted-component counts per category
    per_component = []  # list of (category, ects) tuples with extractions
    found = 0
    missing = 0
    if not case_dir.exists():
        return {"totals": totals, "found": 0, "missing": len(comps)}

    # Components are in subdirectories; map by component_name (best-effort).
    component_dirs = sorted(case_dir.iterdir())
    for comp in comps:
        name = comp.get("component_name", "") or ""
        cat = categorise(name)
        # Find a matching subdirectory by partial name (component_dir prefix
        # is "NNN_OK_X._<name>_..." -- name often appears verbatim).
        # Simplest: scan all PDFs and pick the first that contains the name.
        # We instead match by directory if possible.
        match_dir = None
        for d in component_dirs:
            if not d.is_dir():
                continue
            # rough match: any tokens from name that are 5+ chars
            tokens = [t for t in re.findall(r"\w{5,}", name)]
            if tokens and any(t in d.name for t in tokens[:3]):
                match_dir = d
                break
        ects = None
        if match_dir:
            for pdf in match_dir.glob("*.pdf"):
                ects = extract_ects(pdf)
                if ects:
                    break
            # Fallback to OCR cache if pdftotext extraction failed
            if ects is None:
                ects = ocr_lookup(case_id, match_dir.name)
        if ects:
            totals[cat] += ects
            counts[cat] += 1
            per_component.append((cat, ects))
            found += 1
        else:
            missing += 1
    return {"totals": totals, "counts": counts, "found": found,
            "missing": missing, "per_component": per_component}


def latex_escape(s) -> str:
    if s is None:
        return "--"
    s = str(s)
    repl = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return "".join(c for c in s if ord(c) < 128)


def main():
    cases = sorted(RAW.glob("case_*.json"))
    print(f"[10] Found {len(cases)} case JSONs")

    rows = []
    all_components = []  # category, ects across all 23 cases
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = case.get("case_id", "")
        fs = case.get("form_se") or {}
        comps = fs.get("table1_components") or []
        if not comps:
            continue
        sys.stdout.write(f"\r[10] case {case_id}: {len(comps)} components ... ")
        sys.stdout.flush()
        result = process_case(case_id, comps)
        t = result["totals"]
        all_components.extend(result["per_component"])
        rows.append({
            "case_id": case_id,
            "institution": institution_short(case),
            "n_total": len(comps),
            "n_with_ects": result["found"],
            "subject": t["subject"],
            "pedagogy": t["pedagogy"],
            "practicum": t["practicum"],
            "statutory": t["statutory"],
            "other": t["other"],
            "n_subject_extracted": result["counts"]["subject"],
            "n_pedagogy_extracted": result["counts"]["pedagogy"],
            "n_practicum_extracted": result["counts"]["practicum"],
            "n_statutory_extracted": result["counts"]["statutory"],
            "n_other_extracted": result["counts"]["other"],
        })
        sys.stdout.write(f"found {result['found']}/{len(comps)}\n")
        sys.stdout.flush()

    if not rows:
        print("[10] No rows; exiting"); return

    # Per-row sums
    for r in rows:
        r["sum_ects"] = (r["subject"] + r["pedagogy"] + r["practicum"]
                         + r["statutory"] + r["other"])

    # Aggregates
    n = len(rows)
    means = {k: sum(r[k] for r in rows) / n
             for k in ("subject", "pedagogy", "practicum",
                       "statutory", "other", "sum_ects")}
    n_with_ects_total = sum(r["n_with_ects"] for r in rows)
    n_total = sum(r["n_total"] for r in rows)
    print(f"\n[10] Coverage: {n_with_ects_total}/{n_total} components had extractable ECTS"
          f" ({100*n_with_ects_total/n_total:.1f}%)")

    # Build table
    lines = [
        "% Auto-generated by scripts/10_extract_ects.py from NAQA syllabus PDFs.",
        r"\begin{table}[!t]",
        r"  \centering",
        r"  \caption{Per-category ECTS allocation in NAQA-accredited speciality 014 "
        r"Bachelor programmes, extracted from the syllabus PDFs of each educational "
        r"component. Coverage column reports number of components for which a "
        r"\textit{Kilkist kredytiv} (number of ECTS credits) value was successfully "
        r"extracted from the syllabus front-matter; remaining components either had "
        r"no extractable PDF or used a non-standard credit-disclosure format. "
        r"Sample of 23 NAQA-accredited speciality 014 Bachelor programmes, "
        r"retrieved May 2026 \citep{NAQA:Portal2026}.}",
        r"  \label{tab:opp-ects}",
        r"  \footnotesize",
        r"  \begin{tabular}{llrrrrrrr}",
        r"    \toprule",
        r"    Case & Institution & N\textsubscript{cov} & Subj. & Ped. & Prac. & Stat. & Oth. & $\sum$ \\",
        r"    \midrule",
    ]
    for r in rows:
        lines.append(
            f"    {r['case_id']} & {latex_escape(r['institution'])} & "
            f"{r['n_with_ects']}/{r['n_total']} & "
            f"{r['subject']:.0f} & {r['pedagogy']:.0f} & {r['practicum']:.0f} & "
            f"{r['statutory']:.0f} & {r['other']:.0f} & {r['sum_ects']:.0f} \\\\"
        )
    lines.append(r"    \midrule")
    lines.append(
        f"    \\textit{{Mean}} & --- & --- & "
        f"{means['subject']:.1f} & {means['pedagogy']:.1f} & {means['practicum']:.1f} & "
        f"{means['statutory']:.1f} & {means['other']:.1f} & {means['sum_ects']:.1f} \\\\"
    )
    lines += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[10] Wrote {OUT}")
    print(f"[10] Per-case totals (ECTS): subj={means['subject']:.1f} ped={means['pedagogy']:.1f} "
          f"prac={means['practicum']:.1f} stat={means['statutory']:.1f} sum={means['sum_ects']:.1f}")

    # Per-component statistics across all 446+ extractions: more robust to
    # coverage variance because it weights by extracted components, not by case.
    by_cat = {}
    for cat, ects in all_components:
        by_cat.setdefault(cat, []).append(ects)
    print(f"\n[10] Per-component mean ECTS (across {len(all_components)} extracted components):")
    for cat in ("subject", "pedagogy", "practicum", "statutory", "other"):
        vs = by_cat.get(cat, [])
        if vs:
            print(f"  {cat:10s}: n={len(vs):3d}  mean={sum(vs)/len(vs):4.1f}  "
                  f"min={min(vs):4.1f}  max={max(vs):4.1f}")


if __name__ == "__main__":
    main()
