#!/usr/bin/env python3
"""Merge 33 raw WoS BibTeX exports, deduplicate, rekey to semantic keys.

Input:  ../../data/bibliography/savedrecs*.bib  (33 files, ~6,027 entries)
Output: ../data/corpus_merged.bib
        ../data/corpus_keymap.csv  (WoS:000... -> NewKey crosswalk)

Dedup strategy: DOI exact -> title fuzzy (>=92) -> keep highest-cited.
Rekey scheme: LastName:Year:CamelDescriptor (e.g. Baumert:2010:MathKnowledge).
"""

import csv
import glob
import os
import re
import sys
from pathlib import Path

import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from rapidfuzz import fuzz

REPO_ROOT = Path(__file__).resolve().parents[2]
BIB_GLOB = str(REPO_ROOT / "data" / "bibliography" / "savedrecs*.bib")
OUT_BIB = Path(__file__).resolve().parents[1] / "data" / "corpus_merged.bib"
OUT_CSV = Path(__file__).resolve().parents[1] / "data" / "corpus_keymap.csv"

STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "and", "or", "to", "with",
    "from", "by", "as", "is", "are", "be", "this", "that", "their", "its",
    "into", "between", "among", "across", "through", "case", "study", "review",
    "analysis", "research", "investigation", "examining", "exploring",
}


def load_one(path: str):
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    parser.homogenize_fields = True
    with open(path, encoding="utf-8") as f:
        return bibtexparser.load(f, parser=parser).entries


def cite_count(e: dict) -> int:
    for k in ("times-cited", "times_cited", "Times-Cited", "wos-times-cited"):
        if k in e:
            try:
                return int(re.sub(r"[^\d]", "", e[k]) or 0)
            except ValueError:
                pass
    return 0


def norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def first_lastname(authors: str) -> str:
    if not authors:
        return "Anon"
    first = authors.split(" and ")[0].strip()
    if "," in first:
        last = first.split(",")[0]
    else:
        last = first.split()[-1] if first.split() else "Anon"
    last = re.sub(r"[^A-Za-z]", "", last) or "Anon"
    return last[:1].upper() + last[1:].lower()


def descriptor(title: str, max_words: int = 2) -> str:
    if not title:
        return "Untitled"
    words = re.findall(r"[A-Za-z]+", title)
    keep = [w for w in words if len(w) > 3 and w.lower() not in STOPWORDS]
    keep = keep[:max_words] if keep else words[:max_words]
    return "".join(w[:1].upper() + w[1:].lower() for w in keep) or "Untitled"


def make_key(entry: dict, used: set) -> str:
    last = first_lastname(entry.get("author", ""))
    year = re.sub(r"[^\d]", "", entry.get("year", "")) or "ND"
    desc = descriptor(entry.get("title", ""))
    base = f"{last}:{year}:{desc}"
    key = base
    n = 2
    while key in used:
        key = f"{base}{n}"
        n += 1
    used.add(key)
    return key


def main():
    files = sorted(glob.glob(BIB_GLOB))
    print(f"[01] Found {len(files)} input .bib files")

    all_entries = []
    for path in files:
        try:
            entries = load_one(path)
            all_entries.extend(entries)
            print(f"     {os.path.basename(path):24s}  +{len(entries):5d}  total={len(all_entries):5d}")
        except Exception as exc:
            print(f"     {os.path.basename(path):24s}  ERROR: {exc}", file=sys.stderr)

    print(f"[01] Loaded {len(all_entries)} entries total (raw)")

    # Pass 1: dedup by DOI
    by_doi = {}
    no_doi = []
    for e in all_entries:
        doi = (e.get("doi") or "").strip().lower()
        if doi:
            cur = by_doi.get(doi)
            if cur is None or cite_count(e) > cite_count(cur):
                by_doi[doi] = e
        else:
            no_doi.append(e)
    print(f"[01] After DOI dedup: {len(by_doi)} unique-DOI + {len(no_doi)} no-DOI")

    # Pass 2: among no-DOI entries, dedup by fuzzy title (and reconcile against DOI'd entries)
    doi_titles = [(norm_title(e.get("title", "")), e) for e in by_doi.values()]
    kept_no_doi = []
    for e in no_doi:
        t = norm_title(e.get("title", ""))
        if not t:
            kept_no_doi.append(e)
            continue
        # against existing DOI'd entries: skip if a near-duplicate exists
        if any(fuzz.token_set_ratio(t, t2) >= 92 for t2, _ in doi_titles):
            continue
        # against already-kept no-DOI entries
        merged = False
        for i, ke in enumerate(kept_no_doi):
            if fuzz.token_set_ratio(t, norm_title(ke.get("title", ""))) >= 92:
                if cite_count(e) > cite_count(ke):
                    kept_no_doi[i] = e
                merged = True
                break
        if not merged:
            kept_no_doi.append(e)

    final = list(by_doi.values()) + kept_no_doi
    print(f"[01] After title fuzzy dedup: {len(final)} unique entries")

    # Rekey
    used_keys: set = set()
    keymap_rows = []
    for e in final:
        old = e.get("ID", "")
        new = make_key(e, used_keys)
        keymap_rows.append((old, new, e.get("year", ""), e.get("author", "").split(" and ")[0],
                            (e.get("title", "") or "")[:120]))
        e["ID"] = new

    OUT_BIB.parent.mkdir(parents=True, exist_ok=True)

    # Sort entries by ID for stable output
    final.sort(key=lambda x: x.get("ID", ""))

    db = bibtexparser.bibdatabase.BibDatabase()
    db.entries = final
    writer = BibTexWriter()
    writer.indent = "  "
    writer.add_trailing_comma = True
    with open(OUT_BIB, "w", encoding="utf-8") as fh:
        fh.write(writer.write(db))
    print(f"[01] Wrote {OUT_BIB} ({len(final)} entries)")

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["wos_key", "new_key", "year", "first_author", "title_truncated"])
        w.writerows(keymap_rows)
    print(f"[01] Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
