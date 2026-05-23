#!/usr/bin/env python3
"""Fetch NAQA accreditation cases for speciality 014 Secondary Education.

Wraps the existing /home/cc/claude_code/musiienko/design/naqa_scraper pipeline
without modifying it. Overrides the package's hard-coded settings so the
output lands inside paper/data/naqa/ rather than the original project root.

Strategy:
  1. Filter the NAQA portal by specialty=014 + degree=Бакалавр.
  2. Collect case URLs.
  3. For each case (up to MAX_CASES), navigate the Form SE, extract its 16
     tabs, and download every attached PDF/document (educational programmes,
     accreditation reports, expert opinions, etc.).
  4. Resume safely from checkpoint if interrupted.

The pipeline downloads ~ 1–4 MB per case (Form SE has 16 tabs and N attached
PDFs); plan for ~ 1–2 minutes per case. Run with MAX_CASES=2 first to verify.

Usage:
  python3 scripts/07_fetch_naqa.py --max 2          # smoke test
  python3 scripts/07_fetch_naqa.py --max 25         # production fetch
  python3 scripts/07_fetch_naqa.py --headed         # watch the browser

Output (relative to paper/):
  data/naqa/raw/case_*.json          # one JSON per case (16-tab dump)
  data/naqa/downloads/{case_id}/*    # downloaded PDFs
  data/naqa/output/all_programs.csv  # flattened summary
  data/naqa/checkpoints/{sid}.json   # resume state
  data/naqa/logs/{sid}.log
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Make the musiienko naqa_scraper package importable
SCRAPER_PKG_PARENT = Path("/home/cc/claude_code/musiienko/design")
if str(SCRAPER_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(SCRAPER_PKG_PARENT))

# Relocate the scraper's output to our paper/data/naqa/.
# Must be done BEFORE importing main, since main imports settings directly.
from naqa_scraper.config import settings  # noqa: E402

PAPER_ROOT = Path(__file__).resolve().parents[1]
NAQA_ROOT = PAPER_ROOT / "data" / "naqa"
settings.project_root = NAQA_ROOT
settings.data_dir = NAQA_ROOT / "data"
settings.downloads_dir = NAQA_ROOT / "data" / "downloads"
settings.raw_dir = NAQA_ROOT / "data" / "raw"
settings.output_dir = NAQA_ROOT / "output"
settings.logs_dir = NAQA_ROOT / "logs"
settings.checkpoints_dir = NAQA_ROOT / "checkpoints"
settings.ensure_directories()

from naqa_scraper.main import main_async  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max", type=int, default=2, dest="max_cases",
                   help="Maximum cases to scrape (default: 2 for smoke test).")
    p.add_argument("--specialty", default="014",
                   help="NAQA specialty filter (default: 014 Середня освіта).")
    p.add_argument("--degree", default="Бакалавр",
                   help="Degree level (default: Бакалавр).")
    p.add_argument("--institution", default=None,
                   help="Optional institution-name substring filter.")
    p.add_argument("--region", default=None, help="Optional region filter.")
    p.add_argument("--status", default=None,
                   help="Optional accreditation-status filter (e.g. Акредитована).")
    p.add_argument("--session-id", default=None,
                   help="Resume from an existing session.")
    p.add_argument("--headed", action="store_true",
                   help="Show the browser window (debug).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    sid = args.session_id or f"014-secondary-{uuid.uuid4().hex[:8]}"

    print(f"[07] NAQA fetch session: {sid}")
    print(f"[07] specialty={args.specialty!r}  degree={args.degree!r}  "
          f"institution={args.institution!r}  region={args.region!r}  "
          f"max_cases={args.max_cases}")
    print(f"[07] Output rooted at: {NAQA_ROOT}")

    asyncio.run(main_async(
        session_id=sid,
        resume=True,
        max_cases=args.max_cases,
        headless=not args.headed,
        specialty=args.specialty,
        degree_level=args.degree,
        accreditation_status=args.status,
        region=args.region,
        institution_name=args.institution,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
