#!/usr/bin/env python3
"""Quality-filter the merged corpus per the screening rules from plan3.

Tier 1 (KEEP):
  * any peer-reviewed journal @article (regardless of citations)
  * any entry with times-cited >= 10
  * any entry from year >= 2020
  * any review/meta-analysis (heuristic: 'review' in title or doc-type=Review)

Tier 3 (DROP):
  * pre-2020 @inproceedings/@incollection with 0 citations and no abstract
  * editorials, corrections, errata, subject indexes (heuristic on title)

Input:  ../data/corpus_merged.bib
Output: ../data/corpus_filtered.bib
"""

import re
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

ROOT = Path(__file__).resolve().parents[1]
IN_BIB = ROOT / "data" / "corpus_merged.bib"
OUT_BIB = ROOT / "data" / "corpus_filtered.bib"

JUNK_TITLE_PAT = re.compile(
    r"^(subject\s+index|author\s+index|table\s+of\s+contents|"
    r"editorial|corrigendum|erratum|correction|preface|"
    r"front\s+matter|back\s+matter|book\s+review|in\s+memoriam)\b",
    re.IGNORECASE,
)


def cite_count(e: dict) -> int:
    for k in ("times-cited", "times_cited", "Times-Cited", "wos-times-cited"):
        v = e.get(k, "")
        if v:
            try:
                return int(re.sub(r"[^\d]", "", v) or 0)
            except ValueError:
                pass
    return 0


def year(e: dict) -> int:
    y = re.sub(r"[^\d]", "", e.get("year", "") or "")
    return int(y) if y else 0


def is_review(e: dict) -> bool:
    if "review" in (e.get("type", "") or "").lower():
        return True
    title = (e.get("title", "") or "").lower()
    return "systematic review" in title or "meta-analysis" in title or "meta analysis" in title


def keep(e: dict) -> tuple[bool, str]:
    title = (e.get("title", "") or "").strip()
    if JUNK_TITLE_PAT.match(title):
        return False, "junk-title"

    abstract = (e.get("abstract", "") or "").strip()
    et = e.get("ENTRYTYPE", "").lower()
    y = year(e)
    cc = cite_count(e)

    # Tier 1 — keep
    if et == "article":
        return True, "article"
    if cc >= 10:
        return True, f"cites>={cc}"
    if y >= 2020:
        return True, f"year={y}"
    if is_review(e):
        return True, "review"

    # Tier 3 — drop pre-2020 proceedings/chapters with 0 citations and no abstract
    if et in ("inproceedings", "incollection", "proceedings", "inbook"):
        if cc == 0 and not abstract:
            return False, f"weak-{et}"
        if cc < 2 and y < 2015:
            return False, f"old-weak-{et}"

    # Default: keep if has abstract or any citations
    if abstract or cc > 0:
        return True, "default-ok"
    return False, "no-abstract-no-cites"


def main():
    parser = BibTexParser(common_strings=True)
    parser.homogenize_fields = True
    with open(IN_BIB, encoding="utf-8") as f:
        db = bibtexparser.load(f, parser=parser)

    print(f"[02] Loaded {len(db.entries)} entries")

    kept = []
    reasons: dict[str, int] = {}
    for e in db.entries:
        ok, why = keep(e)
        reasons[why] = reasons.get(why, 0) + 1
        if ok:
            kept.append(e)

    print("[02] Decision breakdown:")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        action = "KEEP" if not why.startswith(("junk", "weak", "old-weak", "no-abstract")) else "DROP"
        print(f"     {action:4s} {why:25s} {n:5d}")

    out_db = bibtexparser.bibdatabase.BibDatabase()
    out_db.entries = kept
    writer = BibTexWriter()
    writer.indent = "  "
    writer.add_trailing_comma = True
    with open(OUT_BIB, "w", encoding="utf-8") as fh:
        fh.write(writer.write(out_db))
    print(f"[02] Wrote {OUT_BIB} ({len(kept)} entries; dropped {len(db.entries) - len(kept)})")


if __name__ == "__main__":
    main()
