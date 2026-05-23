#!/usr/bin/env python3
"""Inter-coder reliability simulation for OPP component categorisation.

Coder A is the regex-based classifier in scripts/08_populate_opp.py:
  practicum -> statutory -> pedagogy -> subject (fallthrough)
with a coarse Ukrainian keyword set.

Coder B (this script) uses a different, more granular decision rule:
  * statutory uses an expanded keyword set (BZhD + civil-defence + integrity
    + foreign-language statutory minimum + inclusive education law)
  * pedagogy distinguishes (a) generic pedagogy/psychology, (b) subject-
    specific methodology (Fachdidaktik), and (c) coursework with explicit
    methodology framing -- all of which roll up to "pedagogy" for the
    inter-coder agreement comparison
  * practicum requires either explicit 'praktyk' / 'stazh' in the name
    OR component_type containing 'praktyka'
  * subject is the residual: anything that names a school subject or
    discipline AND does not match the prior three categories

Output: confusion matrix, simple agreement, Cohen's kappa,
       per-category precision/recall against Coder A, and the
       disagreement list saved to JSON for inspection.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "naqa" / "data" / "raw"
OUT_REPORT = ROOT / "intercoder_reliability_report.txt"
OUT_DISAGREE = ROOT / "intercoder_disagreements.json"

# -- Coder A (replicates 08_populate_opp.py) ------------------------------
A_PEDAGOGY = re.compile(r"\b(педагог|психолог|методик|дидакт|курсова|підсумков|атестац)", re.IGNORECASE)
A_PRACTICUM = re.compile(r"\b(практик|стаж)", re.IGNORECASE)
A_STATUTORY = re.compile(r"\b(БЖД|корекц|охорон.{1,8}прац|анти.?коруп|військов|civilian|defenc)", re.IGNORECASE)


def coder_a(component: dict) -> str:
    name = component.get("component_name", "") or ""
    ctype = (component.get("component_type", "") or "").lower()
    if "практика" in ctype or A_PRACTICUM.search(name):
        return "practicum"
    if A_STATUTORY.search(name):
        return "statutory"
    if A_PEDAGOGY.search(name) or "курсова" in ctype or "атестац" in ctype:
        return "pedagogy"
    if ctype == "навчальна дисципліна":
        return "subject"
    return "other"


# -- Coder B: differently-framed decision rule ---------------------------
B_PRACTICUM = re.compile(r"\b(практик|стаж|польов\s+практ)", re.IGNORECASE)
B_STATUTORY_LAW = re.compile(
    r"(БЖД\b|безпек\w*\s+життєдіяльност|охорон\w{0,4}\s+прац|"
    r"цивільн\w{0,3}\s+захист|надзвичайн\w{0,4}\s+ситуац|"
    r"анти.?коруп|доброчесн|"
    r"інклюз\w{0,4}\s+освіт|корекційн\w{0,4}\s+(?:педагог|освіт)|"
    r"оборон\w*|військов\w*|національн\w{0,3}\s+безпек)",
    re.IGNORECASE,
)
B_PEDAGOGY_GENERIC = re.compile(
    r"(педагог|психолог|вихов\w{0,3}\s+робот|"
    r"теор\w{0,3}\s+навчанн|"
    r"інноваційн\w{0,5}\s+(?:педагог|освіт|навчанн)|"
    r"освітн\w{0,3}\s+технолог|"
    r"професійн\w{0,5}\s+становленн)",
    re.IGNORECASE,
)
B_PEDAGOGY_SUBJECT_METHOD = re.compile(r"методик|дидактик|fachdidakt", re.IGNORECASE)
B_PEDAGOGY_COURSEWORK = re.compile(
    r"(курсов\w*\s+(?:робот\w*|проєкт\w*|проект\w*).*(?:методик|дидактик|педагог|психолог)|"
    r"атестац\w*\s+\(.*методик|"
    r"кваліфікаційн\w*\s+ек(?:замен|с)\w*\s+з\s+методик)",
    re.IGNORECASE,
)
B_FINAL_EXAM = re.compile(r"(підсумков\w+\s+атестац|атестац\w+\s+\(п|комплексн\w+\s+кваліфікаційн)", re.IGNORECASE)


def coder_b(component: dict) -> str:
    name = (component.get("component_name", "") or "").strip()
    n_low = name.lower()
    ctype = (component.get("component_type", "") or "").lower()

    # 1) Practicum
    if "практика" in ctype or "стажування" in ctype:
        return "practicum"
    if B_PRACTICUM.search(n_low):
        return "practicum"

    # 2) Statutory (legal/regulatory courses with statutory anchor)
    if B_STATUTORY_LAW.search(n_low):
        return "statutory"

    # 3) Pedagogy (generic, subject-specific methodology, methodology coursework)
    if B_PEDAGOGY_GENERIC.search(n_low):
        return "pedagogy"
    if B_PEDAGOGY_SUBJECT_METHOD.search(n_low):
        return "pedagogy"
    if B_PEDAGOGY_COURSEWORK.search(n_low):
        return "pedagogy"
    if B_FINAL_EXAM.search(n_low):
        # final certification with methodology component -> pedagogy
        if "методик" in n_low or "педагог" in n_low or "психолог" in n_low:
            return "pedagogy"
        # otherwise treat as 'other' (administrative)
        return "other"

    # 4) Generic coursework that isn't methodology-flagged but ctype suggests pedagogy
    if "курсова" in ctype and not any(w in n_low for w in ("методик", "педагог", "психолог")):
        # Coursework on a subject -> classify as subject content
        return "subject"

    # 5) Subject content (residual): everything else
    return "subject"


# -- Cohen's kappa --------------------------------------------------------
def cohens_kappa(pairs):
    """pairs: iterable of (a_label, b_label). Returns (kappa, simple_agreement, n)."""
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return 0.0, 0.0, 0
    labels = sorted({l for p in pairs for l in p})
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)
    cm = [[0] * k for _ in range(k)]
    for a, b in pairs:
        cm[idx[a]][idx[b]] += 1
    obs = sum(cm[i][i] for i in range(k)) / n
    a_marg = [sum(cm[i]) / n for i in range(k)]
    b_marg = [sum(cm[i][j] for i in range(k)) / n for j in range(k)]
    exp = sum(a_marg[i] * b_marg[i] for i in range(k))
    if exp >= 1.0:
        return 1.0, obs, n
    kappa = (obs - exp) / (1 - exp)
    return kappa, obs, n


def main() -> int:
    cases = sorted(RAW.glob("case_*.json"))
    pairs = []
    by_case = {}
    disagreements = []
    for path in cases:
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = case.get("case_id", "?")
        fs = case.get("form_se") or {}
        comps = fs.get("table1_components") or []
        if not comps:
            continue
        case_pairs = []
        for c in comps:
            a = coder_a(c)
            b = coder_b(c)
            pairs.append((a, b))
            case_pairs.append((a, b))
            if a != b:
                disagreements.append({
                    "case_id": case_id,
                    "component_name": c.get("component_name", "")[:120],
                    "component_type": c.get("component_type", "")[:60],
                    "coder_a": a,
                    "coder_b": b,
                })
        kappa_c, obs_c, n_c = cohens_kappa(case_pairs)
        by_case[case_id] = {"n": n_c, "agreement": obs_c, "kappa": kappa_c}

    kappa, obs, n = cohens_kappa(pairs)
    cnt_a = Counter(a for a, _ in pairs)
    cnt_b = Counter(b for _, b in pairs)

    # Confusion matrix
    labels = sorted(set(cnt_a) | set(cnt_b))
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)
    cm = [[0] * k for _ in range(k)]
    for a, b in pairs:
        cm[idx[a]][idx[b]] += 1

    lines = [
        "Inter-coder reliability report: OPP component categorisation",
        "=" * 60,
        "",
        f"Overall n = {n} components across {len(by_case)} cases",
        f"Simple agreement (proportion identical): {obs:.3f} ({obs*100:.1f}%)",
        f"Cohen's kappa (chance-corrected agreement): {kappa:.3f}",
        "",
        "Confusion matrix (rows = Coder A; columns = Coder B):",
        "  " + "  ".join(f"{l[:8]:>10}" for l in labels) + "       total",
    ]
    for i, l in enumerate(labels):
        row = [f"{cm[i][j]:>10d}" for j in range(k)]
        rsum = sum(cm[i])
        lines.append(f"  {l[:8]:>8}  " + "  ".join(row) + f"  {rsum:>6d}")
    col_totals = [sum(cm[i][j] for i in range(k)) for j in range(k)]
    lines.append("  " + " " * 8 + "  " + "  ".join(f"{t:>10d}" for t in col_totals) + f"  {n:>6d}")
    lines.append("")
    lines.append("Marginal counts:")
    lines.append(f"  Coder A: {dict(sorted(cnt_a.items()))}")
    lines.append(f"  Coder B: {dict(sorted(cnt_b.items()))}")

    # Per-category agreement (precision-flavoured: of cases A called X, how often did B agree)
    lines.append("")
    lines.append("Per-category cell agreement (A's rows; agreement = diagonal/row-total):")
    for i, l in enumerate(labels):
        row_total = sum(cm[i])
        if row_total == 0:
            continue
        agree = cm[i][i] / row_total
        lines.append(f"  {l:>10}: {cm[i][i]:>4d} / {row_total:>4d} = {agree:.3f}")

    lines.append("")
    lines.append(f"Disagreements: {len(disagreements)} components ({len(disagreements)/n*100:.1f}%) "
                 f"— see {OUT_DISAGREE.name} for the full list.")
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_DISAGREE.write_text(json.dumps(disagreements, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[11] Wrote {OUT_REPORT}")
    print(f"[11] Wrote {OUT_DISAGREE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
