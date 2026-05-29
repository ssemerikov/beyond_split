#!/usr/bin/env python3
"""Consolidate the accreditation-remarks analysis (Sonnet read + regex cross-check).

Combines two coding layers, as the round-table co-author requested ("Sonnet for deep
reading IN ADDITION to Python scripts"):
  * SEMANTIC (primary): the per-case Sonnet deep-read in data/naqa/remarks/sonnet_{id}.json
    (verbatim balance remarks, source EG/GER/NAQA, direction, subjects, design).
  * REPRODUCIBLE (cross-check): a deterministic regex flag over remarks_corpus.json.

Final accreditation outcome is derived from the NAQA decision codes (the SPA renders the
decision label client-side from these; the codes are the authoritative machine signal):
    naqaDecision.decision==4            -> accredited
    decision==2 & possibleSolution==3   -> refused
    decision==2 (otherwise)             -> conditional
This matches the Sonnet reading on 33/36 cases; the 3 differences are NAQA-override cases
(final vote != proposed solution) and are resolved to the vote.

Reads:  data/naqa/expert/index.csv, expert/acc_*.json, remarks/sonnet_*.json, remarks/remarks_corpus.json
Writes: data/naqa/remarks/analysis_dataset.csv   (one row per completed case)
        data/naqa/remarks/summary_stats.json      (headline statistics for the manuscript)
"""

import csv
import json
import re
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "data" / "naqa" / "expert"
REM = ROOT / "data" / "naqa" / "remarks"

PRESSURE = {"pressure_toward_parity", "criticises_imbalance"}
# deterministic regex flag (cross-check layer)
REGEX_BALANCE = re.compile(
    r"паритет|непаритет|рівномірн|нерівномірн|дисбаланс|диспропорц|урівноваж|збалансован|"
    r"(розподіл|співвідношенн)[^.\n]{0,45}(кредит|ЄКТС|спеціальн|предметн|фах)|"
    r"(основн|додатков|перш|друг)[а-яіїєґ]{0,4}\s+(предметн|спеціальн|фах)", re.IGNORECASE)


def derive_outcome(nd):
    dec, ps = nd.get("decision"), nd.get("possibleSolution")
    if nd.get("isRefusal"):
        return "refused"
    if dec == 4:
        return "accredited"
    if dec == 2 and ps == 3:
        return "refused"
    if dec == 2:
        return "conditional"
    return "unclear"


def flat_text(sections):
    out = []
    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            [walk(v) for v in o.values()]
        elif isinstance(o, list):
            [walk(v) for v in o]
    walk(sections)
    return "\n".join(out)


def cohen_kappa(a, b):
    """Cohen's kappa for two boolean labelings over the same items."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa_t = sum(a) / n; pb_t = sum(b) / n
    pe = pa_t * pb_t + (1 - pa_t) * (1 - pb_t)
    return (po - pe) / (1 - pe) if pe != 1 else 1.0


def main():
    idx = {r["candidate_id"]: r for r in csv.DictReader(open(EXP / "index.csv", encoding="utf-8"))}
    corpus = json.loads((REM / "remarks_corpus.json").read_text(encoding="utf-8"))
    rows = []
    for cid, r in idx.items():
        if r["completed"] != "True":
            continue
        acc = json.loads((EXP / f"acc_{r['accreditation_id']}.json").read_text(encoding="utf-8"))
        son = json.loads((REM / f"sonnet_{cid}.json").read_text(encoding="utf-8"))
        outcome = derive_outcome(acc.get("naqaDecision") or {})
        rem = son.get("balance_remarks") or []
        directions = [x.get("direction") for x in rem]
        sources = [x.get("source") for x in rem]
        regex_hit = bool(REGEX_BALANCE.search(flat_text(corpus.get(cid, {}).get("sections", {}))))
        rows.append({
            "candidate_id": cid,
            "accreditation_id": r["accreditation_id"],
            "degree": r["degree"],
            "program_name": r["program_name"],
            "primary_subject": son.get("primary_subject", ""),
            "additional_subject": son.get("additional_subject", ""),
            "design": son.get("design", ""),
            "outcome": outcome,
            "non_clean": outcome in ("conditional", "refused"),
            "sonnet_has_balance": bool(son.get("has_balance_remark")),
            "regex_has_balance": regex_hit,
            "n_balance_remarks": len(rem),
            "n_EG": sources.count("EG"),
            "n_GER": sources.count("GER"),
            "n_NAQA": sources.count("NAQA"),
            "parity_pressure": any(d in PRESSURE for d in directions),
            "asymmetry_described": "describes_asymmetry" in directions,
        })

    with open(REM / "analysis_dataset.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    N = len(rows)
    nonclean = [r for r in rows if r["non_clean"]]
    press = [r for r in rows if r["parity_pressure"]]
    nopress = [r for r in rows if not r["parity_pressure"]]
    def ncr(rs): return (sum(r["non_clean"] for r in rs), len(rs))
    # inter-method agreement (Sonnet vs regex, case-level balance flag)
    a = [r["sonnet_has_balance"] for r in rows]
    b = [r["regex_has_balance"] for r in rows]
    agree = sum(x == y for x, y in zip(a, b)) / N

    stats = {
        "n_cases": N,
        "by_degree": dict(Counter(r["degree"] for r in rows)),
        "outcome": dict(Counter(r["outcome"] for r in rows)),
        "non_clean_n": len(nonclean), "non_clean_pct": round(100 * len(nonclean) / N, 1),
        "cases_with_balance_remark_sonnet": sum(a),
        "total_balance_remarks": sum(r["n_balance_remarks"] for r in rows),
        "remarks_by_source": {"EG": sum(r["n_EG"] for r in rows), "GER": sum(r["n_GER"] for r in rows),
                              "NAQA": sum(r["n_NAQA"] for r in rows)},
        "cases_parity_pressure": len(press),
        "cases_asymmetry_described": sum(r["asymmetry_described"] for r in rows),
        "nonclean_rate_pressure": list(ncr(press)),
        "nonclean_rate_nopressure": list(ncr(nopress)),
        "intermethod_agreement_sonnet_vs_regex": round(agree, 3),
        "intermethod_kappa": round(cohen_kappa(a, b), 3),
    }
    (REM / "summary_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"\nwrote {REM/'analysis_dataset.csv'} ({N} cases) and summary_stats.json")


if __name__ == "__main__":
    main()
