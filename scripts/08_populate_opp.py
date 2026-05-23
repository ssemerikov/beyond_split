#!/usr/bin/env python3
"""Populate the empirical-OPP-content-analysis table from NAQA case JSONs.

Reads paper/data/naqa/data/raw/case_*.json (produced by 07_fetch_naqa.py)
and writes paper/tables/tbl_opp_content_analysis.tex with one row per
case, plus mean/range summary.

Each NAQA case JSON has 16 form-SE tabs; tab~0 ('Загальні відомості')
contains the institution and programme metadata; the
`form_se.table1_components` array contains the educational components.
Per-component ECTS values are usually blank in the JSON (they live inside
the syllabus PDFs); this script reports component COUNTS by type:

  - subject content      (heuristic: discipline whose name does NOT match a
                          pedagogy/practicum/statutory keyword regex)
  - pedagogy/psychology  (regex: педагогі|психолог|методик|дидакти)
  - practicum            (component_type contains 'практика')
  - statutory            (regex: БЖД|корекц|охорон.{1,5}прац|анти.?коруп|військов)
  - other / electives    (everything else, incl. final assessment, course
                          work that doesn't fit the categories)

The output is a count table, NOT an ECTS-allocation table. A note in the
caption (and in §5.5 of the manuscript) marks the limitation. Adding the
ECTS column requires PDF parsing of the syllabi -- a future-work task.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "naqa" / "data" / "raw"
OUT = ROOT / "tables" / "tbl_opp_content_analysis.tex"

PEDAGOGY = re.compile(r"\b(педагог|психолог|методик|дидакт|курсова|підсумков|атестац)", re.IGNORECASE)
PRACTICUM = re.compile(r"\b(практик|стаж)", re.IGNORECASE)
STATUTORY = re.compile(r"\b(БЖД|корекц|охорон.{1,8}прац|анти.?коруп|військов|civilian|defenc)", re.IGNORECASE)


def institution(case: dict) -> str:
    """The first field on tab 0 is mis-labelled `Реєстраційний номер ЗВО у ЄДЕБО`
    but actually carries the institution name."""
    fs = case.get("form_se") or {}
    if not fs.get("tabs"):
        return "—"
    fields = fs["tabs"][0].get("all_fields", {}) or {}
    name = fields.get("Реєстраційний номер ЗВО у ЄДЕБО") or ""
    if "академі" in name or "університет" in name or "інститут" in name or "коледж" in name:
        return short_inst(name)
    return short_inst(name) if name else "—"


def short_inst(name: str) -> str:
    if not name:
        return "—"
    n = name.replace("Національний університет", "NU")
    n = n.replace("обласна гуманітарно-педагогічна академія", "OGPA")
    n = re.sub(r"імені|ім\.\s*", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = (n[:30] + "...") if len(n) > 32 else n
    # Strip dangling quote characters left over after truncation.
    return n.rstrip(' "\'').replace('"', '')


def programme(case: dict) -> str:
    fs = case.get("form_se") or {}
    if not fs.get("tabs"):
        return "—"
    fields = fs["tabs"][0].get("all_fields", {}) or {}
    pn = fields.get("ID освітньої програми в ЄДЕБО", "").strip()
    if pn and pn != "-":
        return (pn[:30] + "...") if len(pn) > 32 else pn
    pn = case.get("program_name", "")
    if pn and pn != "Документи акредитаційної справи":
        return (pn[:30] + "...") if len(pn) > 32 else pn
    return "(unspecified)"


def categorise(component: dict) -> str:
    name = component.get("component_name", "") or ""
    ctype = (component.get("component_type", "") or "").lower()

    if "практика" in ctype or PRACTICUM.search(name):
        return "practicum"
    if STATUTORY.search(name):
        return "statutory"
    if PEDAGOGY.search(name) or "курсова" in ctype or "атестац" in ctype:
        return "pedagogy"
    if ctype == "навчальна дисципліна":
        return "subject"
    return "other"


def latex_escape(s) -> str:
    if s is None:
        return "--"
    s = str(s)
    repl = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return "".join(c for c in s if ord(c) < 128 or 0x0400 <= ord(c) <= 0x04FF)


def main():
    cases = sorted(RAW.glob("case_*.json"))
    print(f"[08] Found {len(cases)} case JSONs in {RAW}")

    rows = []
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        fs = case.get("form_se") or {}
        comps = fs.get("table1_components") or []
        if not comps:
            continue
        counts = {"subject": 0, "pedagogy": 0, "practicum": 0,
                  "statutory": 0, "other": 0}
        for c in comps:
            counts[categorise(c)] += 1
        rows.append({
            "case_id": case.get("case_id", ""),
            "institution": institution(case),
            "programme": programme(case),
            "total": len(comps),
            **counts,
        })

    # Aggregate stats
    if rows:
        keys = ["total", "subject", "pedagogy", "practicum", "statutory", "other"]
        means = {k: sum(r[k] for r in rows) / len(rows) for k in keys}
        ranges = {k: (min(r[k] for r in rows), max(r[k] for r in rows)) for k in keys}
    else:
        means = {}; ranges = {}

    # Transliterate Cyrillic to Latin (LaTeX encoding has T1 only, not T2A)
    # ISO 9 simplified for Ukrainian.
    UA_TRANSLIT = {
        "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e",
        "є": "ye", "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "yi", "й": "y",
        "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
        "ш": "sh", "щ": "shch", "ь": "", "ю": "yu", "я": "ya", "'": "'",
        "А": "A", "Б": "B", "В": "V", "Г": "H", "Ґ": "G", "Д": "D", "Е": "E",
        "Є": "Ye", "Ж": "Zh", "З": "Z", "И": "Y", "І": "I", "Ї": "Yi", "Й": "Y",
        "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O", "П": "P", "Р": "R",
        "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch",
        "Ш": "Sh", "Щ": "Shch", "Ь": "", "Ю": "Yu", "Я": "Ya",
    }

    def ascii_only(s):
        return "".join(UA_TRANSLIT.get(c, c if ord(c) < 128 else "?") for c in s)

    lines = [
        "% Auto-generated by scripts/08_populate_opp.py from NAQA case JSONs.",
        "% NOTE: per-component ECTS are not in the form-SE JSON (they live in",
        "% syllabus PDFs). The columns below are component COUNTS, not credits.",
        r"\begin{table}[!t]",
        r"  \centering",
        r"  \caption{Empirical breakdown of educational components in NAQA-accredited "
        r"speciality 014 Bachelor programmes. Counts are component cardinalities by "
        r"category; per-component ECTS are not exposed in the NAQA Form SE JSON and "
        r"would require parsing the syllabi in a follow-up extraction. Sample drawn "
        r"from the public NAQA accreditation portal, retrieved May 2026.}",
        r"  \label{tab:opp-analysis}",
        r"  \footnotesize",
        r"  \begin{tabular}{llrrrrrr}",
        r"    \toprule",
        r"    Case & Institution & Total & Subj. & Ped. & Prac. & Stat. & Oth. \\",
        r"    \midrule",
    ]
    for r in rows:
        lines.append(
            "    {cid} & {inst} & {t} & {s} & {p} & {pr} & {st} & {o} \\\\".format(
                cid=latex_escape(r["case_id"]),
                inst=latex_escape(ascii_only(r["institution"])),
                t=r["total"], s=r["subject"], p=r["pedagogy"],
                pr=r["practicum"], st=r["statutory"], o=r["other"]
            )
        )
    if rows:
        lines.append(r"    \midrule")
        lines.append(
            "    \\textit{{Mean}} & --- & {t:.1f} & {s:.1f} & {p:.1f} & {pr:.1f} & {st:.1f} & {o:.1f} \\\\".format(
                t=means["total"], s=means["subject"], p=means["pedagogy"],
                pr=means["practicum"], st=means["statutory"], o=means["other"]
            )
        )
        lines.append(
            "    \\textit{{Range}} & --- & {t} & {s} & {p} & {pr} & {st} & {o} \\\\".format(
                t=f"{ranges['total'][0]}--{ranges['total'][1]}",
                s=f"{ranges['subject'][0]}--{ranges['subject'][1]}",
                p=f"{ranges['pedagogy'][0]}--{ranges['pedagogy'][1]}",
                pr=f"{ranges['practicum'][0]}--{ranges['practicum'][1]}",
                st=f"{ranges['statutory'][0]}--{ranges['statutory'][1]}",
                o=f"{ranges['other'][0]}--{ranges['other'][1]}",
            )
        )
    lines += [
        r"    \bottomrule",
        r"  \end{tabular}",
        r"\end{table}",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[08] Wrote {OUT} with {len(rows)} programme rows")


if __name__ == "__main__":
    main()
