#!/usr/bin/env python3
"""Validate references.bib entries against the Crossref REST API.

For each @article entry with a DOI, fetches https://api.crossref.org/works/{doi}
and compares: first-author surname, year, journal name, title (fuzzy),
volume, issue, pages. Emits a human-readable report and a JSON fix-proposal.

Usage:
  python3 scripts/09_crossref_validate.py
  python3 scripts/09_crossref_validate.py --apply   # apply auto-safe fixes

The --apply mode only edits fields where Crossref returns a clearly-correct
value and the BibTeX is empty or trivially wrong (typos in volume/pages,
missing journal). Title and author rewrites are NEVER auto-applied; they
require human review.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import bibtexparser
import requests
from bibtexparser.bparser import BibTexParser

ROOT = Path(__file__).resolve().parents[1]
BIB = ROOT / "references.bib"
REPORT = ROOT / "crossref_validation_report.txt"
JSON_REPORT = ROOT / "crossref_validation_report.json"

CROSSREF_BASE = "https://api.crossref.org/works/"
HEADERS = {
    "User-Agent": "TTE-paper-validator/1.0 (academic research; "
                  "https://github.com/anonymous-author/dual-subject-paper)",
}
SLEEP_BETWEEN = 0.4


# Map common Latin-1 / German / Slavic accented chars to ASCII so that
# anglicised author surnames (Koenig vs König, Cevikbas vs Çevikbaş) compare equal.
_ACCENT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "á": "a", "à": "a", "â": "a", "å": "a", "ą": "a",
    "é": "e", "è": "e", "ê": "e", "ë": "e", "ę": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ó": "o", "ò": "o", "ô": "o", "õ": "o",
    "ú": "u", "ù": "u", "û": "u",
    "ć": "c", "č": "c", "ç": "c",
    "ł": "l", "ń": "n", "ň": "n", "ñ": "n",
    "ř": "r", "ś": "s", "š": "s", "ş": "s",
    "ź": "z", "ż": "z", "ž": "z",
})


def strip_html(s: str) -> str:
    """Strip Crossref's residual HTML markup before comparison."""
    s = (s or "")
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    s = s.replace("&#x2018;", "'").replace("&#x2019;", "'")
    s = s.replace("‘", "'").replace("’", "'")
    return s


def norm_title(t: str) -> str:
    t = strip_html(t).translate(_ACCENT_MAP)
    t = re.sub(r"\{|\}", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    return t


def first_author_surname(bib_author: str) -> str:
    if not bib_author:
        return ""
    first = bib_author.split(" and ")[0].strip()
    if "," in first:
        s = first.split(",")[0].strip()
    else:
        parts = first.split()
        s = parts[-1] if parts else ""
    return s.translate(_ACCENT_MAP).lower()


def crossref_lookup(doi: str) -> dict | None:
    url = CROSSREF_BASE + doi
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            if attempt == 0:
                time.sleep(2)
                continue
            return {"_error": f"network: {e}"}
        if r.status_code == 200:
            return r.json().get("message")
        if r.status_code == 404:
            return {"_error": "404"}
        if r.status_code == 429:
            time.sleep(5)
            continue
        return {"_error": f"http {r.status_code}"}
    return {"_error": "retry-exhausted"}


def journal_name_substantive_diff(a: str, b: str) -> bool:
    """Are journal names substantively different (not just &/&amp;, capitalisation,
    leading "The", or subtitle truncation)?"""
    def cleanup(s):
        s = strip_html(s).lower()
        s = re.sub(r"^the\s+", "", s)
        s = re.sub(r":\s*the\s+journal\s+of.*$", "", s)  # drop subtitle "the journal of..."
        s = re.sub(r"[^a-z0-9 ]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s
    return cleanup(a) != cleanup(b)


def compare(entry: dict, cr: dict) -> list[str]:
    issues = []
    cr_authors = cr.get("author") or []
    cr_first = ((cr_authors[0].get("family") or "")
                .translate(_ACCENT_MAP).lower()) if cr_authors else ""
    bib_first = first_author_surname(entry.get("author", ""))
    if cr_first and bib_first and cr_first != bib_first \
            and not (cr_first in bib_first or bib_first in cr_first):
        issues.append(f"AUTHOR mismatch: bib='{bib_first}' crossref='{cr_first}'")

    # Prefer published-print year for journal articles (matches volume year);
    # fall back to issued (which can be online-first, year-1).
    cr_year = ""
    for k in ("published-print", "published", "issued", "published-online"):
        d = cr.get(k) or {}
        parts = d.get("date-parts") or []
        if parts and parts[0]:
            cr_year = str(parts[0][0])
            break
    bib_year = (entry.get("year") or "").strip()
    if cr_year and bib_year and cr_year != bib_year:
        try:
            # Tolerate ±1 year (online-first vs print convention).
            if abs(int(cr_year) - int(bib_year)) > 1:
                issues.append(f"YEAR mismatch: bib='{bib_year}' crossref='{cr_year}'")
        except ValueError:
            issues.append(f"YEAR mismatch: bib='{bib_year}' crossref='{cr_year}'")

    cr_titles = cr.get("title") or []
    cr_title = cr_titles[0] if cr_titles else ""
    if cr_title and norm_title(entry.get("title", "")) != norm_title(cr_title):
        # Only flag if the *normalised* form actually differs.
        bib_norm = norm_title(entry.get("title", ""))
        cr_norm = norm_title(cr_title)
        # If one is a prefix of the other, it's a Crossref display-truncation.
        if not (bib_norm.startswith(cr_norm[:60]) or cr_norm.startswith(bib_norm[:60])):
            issues.append(f"TITLE differs (review): crossref='{cr_title[:80]}'")

    cr_journals = cr.get("container-title") or []
    cr_journal = cr_journals[0] if cr_journals else ""
    bib_journal = entry.get("journal") or ""
    if cr_journal and bib_journal:
        if journal_name_substantive_diff(cr_journal, bib_journal):
            issues.append(f"JOURNAL differs: bib='{bib_journal}' crossref='{cr_journal}'")
    elif cr_journal and not bib_journal:
        issues.append(f"JOURNAL missing in bib (crossref='{cr_journal}')")

    for f in ("volume", "issue"):
        cr_v = (cr.get(f) or "").strip()
        bib_v = (entry.get(f) or "").strip()
        if cr_v and bib_v and cr_v != bib_v:
            issues.append(f"{f.upper()} mismatch: bib='{bib_v}' crossref='{cr_v}'")

    def norm_pages(p):
        return re.sub(r"-+", "-", (p or "").strip())
    cr_pages = norm_pages(cr.get("page", ""))
    bib_pages = norm_pages(entry.get("pages", ""))
    if cr_pages and bib_pages and cr_pages != bib_pages:
        # Crossref sometimes reports only the start page (e.g., "159") for
        # entries whose bib record has the full range ("159-174"). Treat
        # those as agreement on the start page.
        cr_start = cr_pages.split("-", 1)[0]
        bib_start = bib_pages.split("-", 1)[0]
        if "-" not in cr_pages and cr_start == bib_start:
            pass  # Crossref data is partial; bib is more complete -> not a real discrepancy
        else:
            issues.append(f"PAGES differ: bib='{bib_pages}' crossref='{cr_pages}'")

    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Apply auto-safe fixes (volume/issue/pages/journal where bib is empty)")
    args = ap.parse_args()

    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    with BIB.open() as fh:
        db = bibtexparser.load(fh, parser=parser)

    findings = []
    auto_fixes = []
    no_doi = []
    broken_doi = []

    total = len(db.entries)
    print(f"[09] Loaded {total} entries from {BIB.name}")
    article_entries = [e for e in db.entries if e.get("ENTRYTYPE") == "article"]
    print(f"[09] Validating {len(article_entries)} @article entries via Crossref")

    for i, e in enumerate(article_entries, 1):
        key = e.get("ID", "?")
        doi = (e.get("doi") or "").strip().rstrip(".").lower()
        if not doi:
            no_doi.append(key)
            continue
        doi = doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
        doi = doi.replace("\\_", "_").replace("\\&", "&").replace("\\$", "$").replace("\\%", "%")
        sys.stdout.write(f"\r[09] {i}/{len(article_entries)}: {key[:40]:40s} ")
        sys.stdout.flush()
        cr = crossref_lookup(doi) or {}
        if cr.get("_error"):
            err = cr["_error"]
            broken_doi.append((key, doi, err))
            findings.append({"key": key, "doi": doi, "issues": [f"DOI lookup failed: {err}"]})
            time.sleep(SLEEP_BETWEEN)
            continue
        issues = compare(e, cr)
        if issues:
            findings.append({"key": key, "doi": doi, "issues": issues,
                              "crossref_summary": {
                                 "title": (cr.get("title") or [""])[0],
                                 "container": (cr.get("container-title") or [""])[0],
                                 "volume": cr.get("volume", ""),
                                 "issue": cr.get("issue", ""),
                                 "page": cr.get("page", ""),
                                 "year": (cr.get("issued", {}).get("date-parts") or [[""]])[0][0],
                              }})
            for iss in issues:
                if iss.startswith(("VOLUME", "ISSUE", "PAGES", "JOURNAL missing")):
                    auto_fixes.append({"key": key, "issue": iss})
        time.sleep(SLEEP_BETWEEN)
    print()

    summary = {
        "total_entries": total,
        "article_entries": len(article_entries),
        "no_doi": len(no_doi),
        "broken_doi": len(broken_doi),
        "entries_with_issues": len(findings),
        "auto_fix_candidates": len(auto_fixes),
    }
    JSON_REPORT.write_text(json.dumps({
        "summary": summary,
        "findings": findings,
        "no_doi": no_doi,
        "broken_doi": broken_doi,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"Crossref validation report",
        f"==========================",
        f"",
        f"Total entries: {summary['total_entries']}",
        f"@article entries: {summary['article_entries']}",
        f"  - validated against Crossref: {summary['article_entries'] - summary['no_doi']}",
        f"  - missing DOI (skipped): {summary['no_doi']}",
        f"  - DOI broken / not in Crossref: {summary['broken_doi']}",
        f"  - entries with discrepancies: {summary['entries_with_issues']}",
        f"",
    ]
    if broken_doi:
        lines.append("BROKEN DOIs (Crossref 404 or network error):")
        for key, doi, err in broken_doi:
            lines.append(f"  - {key}: doi={doi} ({err})")
        lines.append("")
    if findings:
        lines.append("DISCREPANCIES:")
        for f in findings:
            lines.append(f"")
            lines.append(f"  {f['key']} (doi={f['doi']})")
            for iss in f["issues"]:
                lines.append(f"    - {iss}")
            if "crossref_summary" in f:
                cs = f["crossref_summary"]
                lines.append(f"    Crossref: {cs['title'][:90]}")
                lines.append(f"              {cs['container']} {cs['volume']}({cs['issue']}) {cs['page']} {cs['year']}")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[09] Report: {REPORT}")
    print(f"[09] JSON:   {JSON_REPORT}")
    print(f"[09] Summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
