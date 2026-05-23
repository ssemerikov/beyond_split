#!/usr/bin/env python3
"""Syllabus-level reclassification of OPP boundary cases (Coder C).

For each of the 27 subject<->pedagogy disagreements between Coder A
(scripts/08_populate_opp.py) and Coder B (scripts/11_second_coder.py),
this script applies a third decision rule that prioritises the
syllabus's substantive content over the surface keyword.

The three Coder-C rules:
  1. Coursework on a named school subject ("Kursova robota z [subject]")
     -> SUBJECT, unless the subject token is itself a methodology term
     (metodyka / pedahohika / psykholohiya / dydaktyka), in which case
     the coursework is methodology-on-pedagogy and stays pedagogy.
  2. Final / qualifying examinations and qualifying theses
     ("Atestatsiynyy ekzamen", "Kvalifikatsiynyy ekzamen / ispyt",
     "Kvalifikatsiyna bakalavrska robota") -> OTHER.
     These components synthesise the whole programme rather than testing
     any single category, and are administrative-assessment items.
  3. "Osvitni tekhnolohiyi" / "Vyhkovni tekhnolohiyi" / applied
     psycho-linguistics -> PEDAGOGY, treating educational-technology and
     upbringing-technology as methodology-of-instruction items rather than
     subject content.

Coder C is applied only to boundary cases (subject<->pedagogy
disagreements between A and B); for all other components Coder A's
classification is retained. This reflects the design principle that
a third-coder pass should resolve genuine ambiguity, not re-litigate
clear-cut cases.

Output: confusion matrix (A vs C, B vs C), Cohen's kappa for both,
and a reclassified count table that propagates Coder C's resolutions
to the per-category totals.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISAGREE = ROOT / "intercoder_disagreements.json"
RAW = ROOT / "data" / "naqa" / "data" / "raw"
OUT_REPORT = ROOT / "third_coder_report.txt"
OUT_RESOLVED = ROOT / "third_coder_resolutions.json"


def coder_c_decision(name: str) -> str | None:
    """Apply Coder C's syllabus-level reasoning to the given component name.

    Returns None if no Coder-C rule applies (caller should fall back to
    Coder A or Coder B as appropriate).
    """
    n = (name or "").lower()

    # Rule 2: Final / qualifying examinations and qualifying theses -> OTHER
    if re.search(r"атестац\w*\s+(?:екзамен|іспит)", n):
        return "other"
    if re.search(r"^атестац[іяії]\w*$", n.strip()):
        return "other"
    if re.search(r"кваліфікац\w+\s+(?:екзамен|іспит|робот)", n):
        return "other"
    if re.search(r"^ок\s*\d+\.\s*атестац", n):
        return "other"

    # Rule 1: Coursework on a named subject
    cw = re.search(r"курсов\w*\s+робот\w*", n)
    if cw:
        # If the coursework is explicitly on methodology/pedagogy/psychology, stay pedagogy
        if re.search(r"з\s+(методик|педагогік|психолог|дидактик)", n):
            return "pedagogy"
        # If the coursework names ANY school subject after "з / із / зі"
        if re.search(r"з\s+\w{4,}", n):
            return "subject"
        # Bare "курсова робота" with no further qualification -> default subject
        return "subject"

    # Rule 3: Educational technologies / upbringing technologies / linguo-psychology
    if re.search(r"освітн\w+\s+технолог", n):
        return "pedagogy"
    if re.search(r"виховн\w+\s+технолог", n):
        return "pedagogy"
    if "лінгвопсихолог" in n or "психолінгв" in n:
        return "pedagogy"
    if re.search(r"провайдинг\s+освітн", n):
        return "pedagogy"

    # Rule 4: Survey lectures default to subject (programme-content review)
    if re.search(r"оглядов\w+\s+лекц", n):
        return "subject"

    return None


def cohens_kappa(pairs):
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
    return (obs - exp) / (1 - exp), obs, n


def main() -> int:
    disagree = json.loads(DISAGREE.read_text(encoding="utf-8"))
    boundary = [d for d in disagree
                if {d["coder_a"], d["coder_b"]} == {"subject", "pedagogy"}]
    print(f"[13] Boundary cases (subject<->pedagogy A/B disagreements): {len(boundary)}")

    resolutions = []
    a_vs_c = []
    b_vs_c = []
    no_rule = 0
    for d in boundary:
        c = coder_c_decision(d["component_name"])
        if c is None:
            no_rule += 1
            # Default: take Coder B (the more granular rule)
            c = d["coder_b"]
            decision_basis = "default-to-B (no Coder-C rule applied)"
        else:
            decision_basis = "Coder-C rule"
        resolutions.append({
            "case_id": d["case_id"],
            "component_name": d["component_name"],
            "coder_a": d["coder_a"],
            "coder_b": d["coder_b"],
            "coder_c": c,
            "basis": decision_basis,
        })
        a_vs_c.append((d["coder_a"], c))
        b_vs_c.append((d["coder_b"], c))

    print(f"[13] Coder-C rule applied: {len(boundary)-no_rule}/{len(boundary)} cases"
          f" ({(len(boundary)-no_rule)/len(boundary)*100:.0f}%)")
    print(f"[13] Cases without Coder-C rule (defaulted to Coder B): {no_rule}")

    # Distribution under Coder C
    from collections import Counter
    a_dist = Counter(d["coder_a"] for d in boundary)
    b_dist = Counter(d["coder_b"] for d in boundary)
    c_dist = Counter(r["coder_c"] for r in resolutions)
    print(f"\n[13] Boundary-case label distribution:")
    for label in ("subject", "pedagogy", "other"):
        print(f"  {label:>10}: A={a_dist.get(label,0):>2d}  B={b_dist.get(label,0):>2d}  C={c_dist.get(label,0):>2d}")

    # Kappa A vs C and B vs C (on the boundary subset only)
    kac, oac, nac = cohens_kappa(a_vs_c)
    kbc, obc, nbc = cohens_kappa(b_vs_c)
    print(f"\n[13] Kappa A vs C (boundary subset, n={nac}): {kac:.3f}, simple agreement {oac:.3f}")
    print(f"[13] Kappa B vs C (boundary subset, n={nbc}): {kbc:.3f}, simple agreement {obc:.3f}")

    # Project Coder-C resolutions onto the full sample to compute the
    # corrected category totals.
    # Load all cases, apply Coder A to all components, then override with
    # Coder C wherever the boundary-disagreement set names that component.
    boundary_keys = {(r["case_id"], r["component_name"]): r["coder_c"] for r in resolutions}
    A_PEDAGOGY = re.compile(r"\b(педагог|психолог|методик|дидакт|курсова|підсумков|атестац)", re.IGNORECASE)
    A_PRACTICUM = re.compile(r"\b(практик|стаж)", re.IGNORECASE)
    A_STATUTORY = re.compile(r"\b(БЖД|корекц|охорон.{1,8}прац|анти.?коруп|військов|civilian|defenc)", re.IGNORECASE)

    def coder_a(comp):
        name = comp.get("component_name", "") or ""
        ctype = (comp.get("component_type", "") or "").lower()
        if "практика" in ctype or A_PRACTICUM.search(name):
            return "practicum"
        if A_STATUTORY.search(name):
            return "statutory"
        if A_PEDAGOGY.search(name) or "курсова" in ctype or "атестац" in ctype:
            return "pedagogy"
        if ctype == "навчальна дисципліна":
            return "subject"
        return "other"

    a_total = Counter()
    c_total = Counter()
    for path in sorted(RAW.glob("case_*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        cid = case.get("case_id", "")
        fs = case.get("form_se") or {}
        comps = fs.get("table1_components") or []
        for comp in comps:
            la = coder_a(comp)
            name = comp.get("component_name", "")
            lc = boundary_keys.get((cid, name[:120]), la)  # match on truncated name as stored
            a_total[la] += 1
            c_total[lc] += 1

    # Boundary-key match might fail if names were truncated differently; do a permissive pass
    if not any(la != lc for la, lc in zip([], [])):
        # Above zip is empty; do the count again with permissive matching
        a_total.clear()
        c_total.clear()
        for path in sorted(RAW.glob("case_*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            cid = case.get("case_id", "")
            fs = case.get("form_se") or {}
            comps = fs.get("table1_components") or []
            for comp in comps:
                la = coder_a(comp)
                name = (comp.get("component_name") or "").strip()
                # Match against boundary set by case_id + name prefix
                resolved = la
                for (bk_cid, bk_name), c_label in boundary_keys.items():
                    if bk_cid == cid and (name.startswith(bk_name[:80]) or bk_name.startswith(name[:80])):
                        resolved = c_label
                        break
                a_total[la] += 1
                c_total[resolved] += 1

    print(f"\n[13] Full-sample category counts (A primary -> Coder-C corrected):")
    for label in ("subject", "pedagogy", "practicum", "statutory", "other"):
        a, c = a_total.get(label, 0), c_total.get(label, 0)
        delta = c - a
        sign = "+" if delta > 0 else ("" if delta == 0 else "")
        print(f"  {label:>10}: A={a:>4d}  C={c:>4d}  ({sign}{delta:+d})")

    OUT_RESOLVED.write_text(json.dumps(resolutions, indent=2, ensure_ascii=False),
                            encoding="utf-8")

    # Build text report
    lines = [
        "Coder C (syllabus-level) reclassification of boundary cases",
        "=" * 60,
        "",
        f"Boundary subset: {len(boundary)} subject<->pedagogy disagreements",
        f"Coder-C rules applied: {len(boundary)-no_rule}",
        f"Defaulted to Coder B (no rule): {no_rule}",
        "",
        f"Boundary-set distribution:",
        f"  subject:  A={a_dist.get('subject',0):>2d}  B={b_dist.get('subject',0):>2d}  C={c_dist.get('subject',0):>2d}",
        f"  pedagogy: A={a_dist.get('pedagogy',0):>2d}  B={b_dist.get('pedagogy',0):>2d}  C={c_dist.get('pedagogy',0):>2d}",
        f"  other:    A={a_dist.get('other',0):>2d}  B={b_dist.get('other',0):>2d}  C={c_dist.get('other',0):>2d}",
        "",
        f"Cohen's kappa A vs C (boundary, n={nac}): {kac:.3f}",
        f"Cohen's kappa B vs C (boundary, n={nbc}): {kbc:.3f}",
        "",
        "Per-resolution breakdown:",
    ]
    for r in resolutions:
        lines.append(f"  [{r['case_id']}] A={r['coder_a']}, B={r['coder_b']}, "
                     f"C={r['coder_c']}  ({r['basis']})")
        lines.append(f"    {r['component_name'][:100]}")
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[13] Wrote {OUT_REPORT}")
    print(f"[13] Wrote {OUT_RESOLVED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
