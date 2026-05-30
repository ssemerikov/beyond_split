#!/usr/bin/env python3
"""Fetch NAQA accreditation *expert-case* records for the dual-subject candidate set.

Unlike 07_fetch_naqa.py (Playwright scrape of the Form SE self-evaluation + syllabi),
this script targets the **expert-case** materials -- the Expert-Group report, the
Sectoral-Expert-Council (ГЕР) conclusion, and the National-Agency (NAQA) decision --
which the round-table co-author asked to mine for remarks on the distribution of
educational components between the primary (основна) and additional (додаткова)
subject specialities.

Discovery showed these live in the portal's public JSON API, as structured text
(no Playwright, no PDF, no OCR):

    GET /api/v2/SelfEstimation/{folderId}/Get   -> .general.accreditationId
    GET /api/v2/Accreditation/{accId}/Get       -> full expert-case record

Key fields in the Accreditation record:
    esSummary{conclusions,strengths,weaknesses}      Expert-Group summary
    esAnalysis{criterionN_*, weaknessesN, reasonN}   Expert-Group per-criterion analysis (~96 keys)
    besRecommendations{besCriterionN}                ГЕР recommendations
    besResultEvaluation{...}                         ГЕР per-criterion evaluation
    remark / branchAnswers                           University responses (to EG / to ГЕР)
    naqaDecision / naqaDecisionData / accreditationDecision / votingResults   NAQA decision
    accreditationRequest.programDesc                 "<name>\\n<Бакалавр|Магістр>\\n<galuz>\\n<014 ...>"
    stageId == 2700                                  completed / archived

Output (under beyond_split/data/naqa/expert/):
    acc_{accId}.json    full Accreditation record (cached; skipped if present unless --force)
    se_{folderId}.json  trimmed SelfEstimation metadata (general block + status)
    index.csv           one row per candidate (triage + decision codes + dual guess)

Usage:
    python3 scripts/14_fetch_expert_cases.py            # all 57 candidates, resume-safe
    python3 scripts/14_fetch_expert_cases.py --force    # re-download even if cached
    python3 scripts/14_fetch_expert_cases.py --only 15430 11882
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

API = "https://public.naqa.gov.ua/api"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "naqa" / "expert"

# 57 candidate folder ids supplied by the main author (round-table 2026-05-27).
CANDIDATES = [
    "16632", "16462", "16425", "16332", "16310", "16286", "16262", "16105", "16086", "15944",
    "15840", "15818", "15783", "15601", "15556", "15520", "15471", "15430", "15311", "15214",
    "15181", "14245", "14138", "14064", "13991", "13945", "13868", "13852", "13823", "13755",
    "13718", "14464", "14413", "14410", "13942", "12766", "12686", "12667", "12364", "12361",
    "12352", "12309", "12270", "12248", "12244", "12237", "12171", "12170", "12110", "12109",
    "12084", "12017", "12010", "11980", "11955", "11886", "11882",
]

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get_json(path, retries=3, backoff=2.0, timeout=60):
    """GET API path as JSON with retry/backoff. Returns dict or raises."""
    url = API + path
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(backoff * (attempt + 1))
    raise last


def degree_of(desc):
    if "Бакалавр" in desc:
        return "BA"
    if "Магістр" in desc:
        return "MA"
    return "?"


def specialty_of(desc):
    m = re.search(r"\b(\d{3})\s", desc)
    return m.group(1) if m else "?"


def dual_guess(program_name):
    """Tentative dual-subject flag from the 'Середня освіта (...)' parenthetical.

    Heuristic only -- the two predметні спеціальності are usually separated by '.'
    (e.g. 'Біологія та здоров'я людини. Географія') or by ' та ' joining two
    'мова і література (...)' clauses. Flagged rows are manually validated in the
    coding phase (16_code_remarks.py); this is a starting point, not ground truth.
    """
    m = re.search(r"\((.*)\)\s*$", (program_name or "").strip())
    inner = m.group(1) if m else (program_name or "")
    # strip nested language qualifiers so their internal 'і'/'та' don't mislead
    stripped = re.sub(r"\([^)]*\)", "", inner)
    if "." in stripped:
        return True
    # two language-pair clauses: "... (німецька) та ... (англійська)"
    if inner.count("(") >= 2 and " та " in inner:
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="Re-download even if acc_*.json cached.")
    ap.add_argument("--only", nargs="*", default=None, help="Subset of candidate folder ids.")
    ap.add_argument("--delay", type=float, default=0.4, help="Polite delay between requests (s).")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    cands = args.only if args.only else CANDIDATES

    rows = []
    for i, fid in enumerate(cands, 1):
        rec = {"candidate_id": fid, "accreditation_id": "", "university": "", "program_name": "",
               "degree": "?", "specialty": "?", "stage_id": "", "completed": False,
               "dual_guess": False, "accreditation_decision": "", "naqa_decision": "",
               "possible_solution": "", "has_es_summary": False, "has_ger": False,
               "has_naqa_decision": False, "se_status": "", "error": ""}
        try:
            se = get_json(f"/v2/SelfEstimation/{fid}/Get")
            g = se.get("general") or {}
            rec["university"] = g.get("universityName") or ""
            rec["program_name"] = g.get("programName") or ""
            rec["se_status"] = (se.get("status") or {}).get("name", "")
            acc_id = g.get("accreditationId")
            # cache trimmed SE metadata
            (OUT / f"se_{fid}.json").write_text(
                json.dumps({"id": se.get("id"), "status": se.get("status"), "general": g},
                           ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(args.delay)

            if acc_id:
                rec["accreditation_id"] = acc_id
                cache = OUT / f"acc_{acc_id}.json"
                if cache.exists() and not args.force:
                    acc = json.loads(cache.read_text(encoding="utf-8"))
                else:
                    acc = get_json(f"/v2/Accreditation/{acc_id}/Get")
                    cache.write_text(json.dumps(acc, ensure_ascii=False, indent=1), encoding="utf-8")
                    time.sleep(args.delay)

                ar = acc.get("accreditationRequest") or {}
                desc = ar.get("programDesc") or ""
                pname = ar.get("programName") or rec["program_name"]
                rec["program_name"] = pname
                rec["degree"] = degree_of(desc)
                rec["specialty"] = specialty_of(desc)
                rec["dual_guess"] = dual_guess(pname)
                rec["stage_id"] = acc.get("stageId")
                rec["completed"] = (acc.get("stageId") == 2700)
                rec["accreditation_decision"] = acc.get("accreditationDecision")
                nd = acc.get("naqaDecision") or {}
                rec["naqa_decision"] = nd.get("decision") if isinstance(nd, dict) else ""
                rec["possible_solution"] = nd.get("possibleSolution") if isinstance(nd, dict) else ""
                es = acc.get("esSummary") or {}
                rec["has_es_summary"] = bool((es.get("conclusions") or es.get("weaknesses") or "").strip())
                rec["has_ger"] = bool(acc.get("besRecommendations") or acc.get("besResultEvaluation"))
                rec["has_naqa_decision"] = bool(nd)
        except Exception as e:
            rec["error"] = str(e)[:80]
        rows.append(rec)
        print(f"[{i:>2}/{len(cands)}] {fid} acc={rec['accreditation_id']} "
              f"stage={rec['stage_id']} {rec['degree']}/{rec['specialty']} "
              f"completed={rec['completed']} dual?={rec['dual_guess']}  {rec['error']}")

    # write index
    cols = list(rows[0].keys())
    with open(OUT / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    completed = [r for r in rows if r["completed"]]
    print(f"\nSaved {len(rows)} rows to {OUT/'index.csv'}")
    print(f"  completed (stage 2700): {len(completed)}  "
          f"[BA={sum(r['degree']=='BA' for r in completed)}, MA={sum(r['degree']=='MA' for r in completed)}]")
    print(f"  dual-subject guess among completed: {sum(r['dual_guess'] for r in completed)}")
    print(f"  specialty 014: {sum(r['specialty']=='014' for r in rows)}")


if __name__ == "__main__":
    sys.exit(main())
