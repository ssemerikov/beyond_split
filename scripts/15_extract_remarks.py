#!/usr/bin/env python3
"""Assemble a normalised accreditation-remarks corpus from cached Accreditation JSON.

Reads data/naqa/expert/index.csv + acc_{accId}.json (produced by 14_fetch_expert_cases.py)
and, for each COMPLETED case (stageId 2700), extracts the remark text from the four sources
the round-table co-author asked about:

  * Expert Group (ЕГ):  esSummary{conclusions,strengths,weaknesses} + esAnalysis per criterion
                        (criterionN_*, strengthsN, weaknessesN, reasonN, lvlN)
  * Sectoral Expert Council (ГЕР):  besRecommendations{besCriterionN} + besResultEvaluation
  * University responses:  remark.remark, expertRemark.remark, branchAnswers
  * NAQA decision:  accreditationDecision / possibleSolution / naqaDecision rationale

Outputs (data/naqa/remarks/):
  case_{candidate}.md       human/LLM-readable dossier per case (input for the Sonnet deep-read)
  remarks_corpus.json       machine-readable sections per case (input for 16_code_remarks.py)

No PDF download / OCR: every field above is structured text in the API record.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERT = ROOT / "data" / "naqa" / "expert"
OUT = ROOT / "data" / "naqa" / "remarks"

# NAQA final-decision code mapping is verified by the Sonnet read; provisional here.
DECISION = {5: "accredited", 6: "exemplary", 2: "conditional", 1: "refused"}
POSSIBLE = {1: "accredit", 2: "conditional/deferred", 3: "refuse"}


def s(v):
    """Coerce any JSON value to a stripped string (skip empties)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float, bool)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def eg_criteria(es_analysis):
    """Group esAnalysis flat keys (criterionN_M, strengthsN, weaknessesN, reasonN, lvlN) by criterion."""
    crit = {}
    for k, v in (es_analysis or {}).items():
        m = None
        for prefix, field in (("criterion", "body"), ("strengths", "strengths"),
                              ("weaknesses", "weaknesses"), ("reason", "reason"), ("lvl", "lvl")):
            if k.startswith(prefix):
                rest = k[len(prefix):]
                num = rest.split("_")[0]
                if num.isdigit():
                    m = (int(num), field)
                break
        if not m:
            continue
        n, field = m
        crit.setdefault(n, {"body": [], "strengths": "", "weaknesses": "", "reason": "", "lvl": ""})
        if field == "body":
            if s(v):
                crit[n]["body"].append(s(v))
        else:
            if s(v):
                crit[n][field] = s(v)
    return dict(sorted(crit.items()))


def build(acc, meta):
    """Return (markdown, sections_dict) for one case."""
    es = acc.get("esSummary") or {}
    crit = eg_criteria(acc.get("esAnalysis") or {})
    bes_rec = acc.get("besRecommendations") or {}
    bes_eval = acc.get("besResultEvaluation") or {}
    remark = (acc.get("remark") or {}).get("remark", "") if isinstance(acc.get("remark"), dict) else ""
    exrem = (acc.get("expertRemark") or {}).get("remark", "") if isinstance(acc.get("expertRemark"), dict) else ""
    nd = acc.get("naqaDecision") or {}
    naqa_rationale = {k: s(v) for k, v in nd.items() if k.startswith("naqaCriteriaRationale") and s(v)}
    branch_ans = []
    for ba in (acc.get("branchAnswers") or []):
        if isinstance(ba, dict):
            for k, v in ba.items():
                if isinstance(v, str) and len(v.strip()) > 30:
                    branch_ans.append(v.strip())

    sections = {
        "eg_conclusions": s(es.get("conclusions")),
        "eg_strengths": s(es.get("strengths")),
        "eg_weaknesses": s(es.get("weaknesses")),
        "eg_criteria": crit,
        "ger_recommendations": {k: s(v) for k, v in bes_rec.items() if s(v)},
        "ger_evaluation": {k: s(v) for k, v in bes_eval.items() if isinstance(v, str) and s(v)},
        "univ_response_to_eg": remark,
        "univ_analysis_draft_eg": exrem,
        "univ_answer_to_ger": branch_ans,
        "naqa_rationale": naqa_rationale,
    }

    # markdown
    L = []
    L.append(f"# Case {meta['candidate_id']} — {meta['program_name']}")
    L.append(f"- accreditation_id: {meta['accreditation_id']}  |  {meta['degree']} / specialty {meta['specialty']}")
    L.append(f"- university: {meta['university']}")
    dec = acc.get("accreditationDecision")
    ps = (nd.get("possibleSolution") if isinstance(nd, dict) else None)
    L.append(f"- DECISION (provisional): accreditationDecision={dec} ({DECISION.get(dec,'?')}); "
             f"possibleSolution={ps} ({POSSIBLE.get(ps,'?')}); naqaDecision.decision={nd.get('decision')}; "
             f"protocol={nd.get('protocolNumber')}; date={s(nd.get('decisionDate'))[:10]}")
    L.append("")
    L.append("## Expert Group (ЕГ) — overall")
    L.append("### Conclusions\n" + sections["eg_conclusions"])
    L.append("### Strengths\n" + sections["eg_strengths"])
    L.append("### Weaknesses / recommendations\n" + sections["eg_weaknesses"])
    L.append("\n## Expert Group — per criterion")
    for n, c in crit.items():
        L.append(f"### Criterion {n}  (level: {c['lvl'] or '-'})")
        if c["body"]:
            L.append("\n".join(c["body"]))
        if c["strengths"]:
            L.append(f"**Strengths:** {c['strengths']}")
        if c["weaknesses"]:
            L.append(f"**Weaknesses:** {c['weaknesses']}")
        if c["reason"]:
            L.append(f"**Reason:** {c['reason']}")
    if sections["ger_recommendations"]:
        L.append("\n## Sectoral Expert Council (ГЕР) — recommendations")
        for k, v in sections["ger_recommendations"].items():
            L.append(f"**{k}:** {v}")
    if sections["ger_evaluation"]:
        L.append("\n## ГЕР — evaluation")
        for k, v in sections["ger_evaluation"].items():
            L.append(f"**{k}:** {v}")
    if remark or exrem or branch_ans:
        L.append("\n## University responses")
        if exrem:
            L.append("### Analysis of draft EG report\n" + exrem)
        if remark:
            L.append("### Response to EG report\n" + remark)
        for i, b in enumerate(branch_ans):
            L.append(f"### Answer to ГЕР [{i}]\n{b}")
    if naqa_rationale:
        L.append("\n## NAQA decision — criteria rationale")
        for k, v in naqa_rationale.items():
            L.append(f"**{k}:** {v}")
    return "\n".join(L), sections


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(open(EXPERT / "index.csv", encoding="utf-8")))
    completed = [r for r in rows if r["completed"] == "True"]
    corpus = {}
    for r in completed:
        acc_path = EXPERT / f"acc_{r['accreditation_id']}.json"
        if not acc_path.exists():
            print("MISSING", acc_path); continue
        acc = json.loads(acc_path.read_text(encoding="utf-8"))
        md, sections = build(acc, r)
        (OUT / f"case_{r['candidate_id']}.md").write_text(md, encoding="utf-8")
        corpus[r["candidate_id"]] = {
            "candidate_id": r["candidate_id"],
            "accreditation_id": r["accreditation_id"],
            "program_name": r["program_name"],
            "university": r["university"],
            "degree": r["degree"],
            "specialty": r["specialty"],
            "accreditation_decision": r["accreditation_decision"],
            "possible_solution": r["possible_solution"],
            "sections": sections,
        }
    (OUT / "remarks_corpus.json").write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")
    # quick size report
    tot = 0
    for cid, c in corpus.items():
        n = len(json.dumps(c["sections"], ensure_ascii=False))
        tot += n
    print(f"Wrote {len(corpus)} case dossiers to {OUT}")
    print(f"  remarks_corpus.json sections total ~{tot:,} chars (avg {tot//max(1,len(corpus)):,}/case)")
    print(f"  per-case .md files: {len(list(OUT.glob('case_*.md')))}")


if __name__ == "__main__":
    main()
