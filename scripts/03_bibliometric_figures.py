#!/usr/bin/env python3
"""Generate two bibliometric figures from the dedup'd corpus.

Outputs:
  ../figures/fig_publication_trend.pdf   -- year histogram by pillar (stacked)
  ../figures/fig_keyword_network.pdf     -- keyword co-occurrence network

Pillars are inferred from a small keyword-rule set so we can colour-code the
publication trend without reading every abstract.

Inputs:
  ../data/corpus_filtered.bib  (~4,573 entries)
"""

import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import bibtexparser
import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
from bibtexparser.bparser import BibTexParser

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
IN_BIB = ROOT / "data" / "corpus_filtered.bib"
OUT_TREND = ROOT / "figures" / "fig_publication_trend.pdf"
OUT_NET = ROOT / "figures" / "fig_keyword_network.pdf"

PILLAR_RULES = [
    ("Dual-subject / Major-Minor",
     r"\b(dual[ -]subject|double[ -]major|hauptfach|nebenfach|major[ -]?minor|"
     r"two[ -]subject|combined subject|subject combination)\b"),
    ("PCK & content knowledge",
     r"\b(pedagogical content knowledge|pck|content knowledge|"
     r"subject matter knowledge|disciplinary knowledge|fachdidaktik)\b"),
    ("Comparative / Cross-national",
     r"\b(comparative|cross[ -]national|international comparison|"
     r"oecd|eurydice|talis|policy transfer)\b"),
    ("Accreditation & QA",
     r"\b(accreditation|quality assurance|standard|qualification framework|"
     r"licensure|certification)\b"),
    ("Rural / labour market",
     r"\b(rural|small school|multi[ -]grade|multi[ -]subject|"
     r"teacher shortage|teacher supply|employability|labour market|labor market|"
     r"recruitment|retention)\b"),
    ("History / continental tradition",
     r"\b(historical|history of teacher|tradition|"
     r"humboldtian|pädagogische hochschule|post[ -]soviet)\b"),
]
PILLAR_PATTERNS = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in PILLAR_RULES]


def kw_field(entry: dict) -> str:
    """WoS exports use 'keyword' (author keywords) and 'keywords-plus' (auto)."""
    return " ; ".join(filter(None, (
        entry.get("keyword", ""), entry.get("keywords-plus", ""),
        entry.get("keywords", ""),
    )))


def assign_pillar(entry: dict) -> str:
    text_parts = [entry.get("title", ""), entry.get("abstract", ""),
                  kw_field(entry)]
    text = " ".join(p for p in text_parts if p)
    for name, pat in PILLAR_PATTERNS:
        if pat.search(text):
            return name
    return "Other / general teacher ed."


def year(e: dict) -> int:
    y = re.sub(r"[^\d]", "", e.get("year", "") or "")
    return int(y) if y else 0


def split_keywords(s: str) -> list[str]:
    if not s:
        return []
    parts = re.split(r"\s*[;,]\s*|\s*\n\s*", s)
    return [p.strip().lower() for p in parts if p.strip()]


KEYWORD_BLACKLIST = {
    "teacher", "education", "teachers", "teaching", "students", "student",
    "school", "schools", "learning", "study", "studies", "research",
}


def normalize_keyword(kw: str) -> str:
    kw = re.sub(r"\s+", " ", kw.lower()).strip()
    kw = re.sub(r"[^\w\s/-]", "", kw)
    return kw


def main():
    parser = BibTexParser(common_strings=True)
    parser.homogenize_fields = True
    with open(IN_BIB, encoding="utf-8") as f:
        db = bibtexparser.load(f, parser=parser)
    print(f"[03] Loaded {len(db.entries)} entries")

    # ---------- Publication trend by pillar ----------
    counts: dict[str, Counter] = defaultdict(Counter)
    for e in db.entries:
        y = year(e)
        if y < 1995 or y > 2026:
            continue
        counts[assign_pillar(e)][y] += 1

    pillars = [p[0] for p in PILLAR_RULES] + ["Other / general teacher ed."]
    years_axis = list(range(1995, 2027))

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    bottom = [0] * len(years_axis)
    palette = plt.get_cmap("tab10").colors
    for i, pillar in enumerate(pillars):
        ys = [counts[pillar].get(y, 0) for y in years_axis]
        ax.bar(years_axis, ys, bottom=bottom, label=pillar,
               color=palette[i % len(palette)], edgecolor="white", linewidth=0.3)
        bottom = [b + y for b, y in zip(bottom, ys)]

    ax.set_xlabel("Publication year")
    ax.set_ylabel("Number of records")
    ax.set_title("Corpus publication trend by conceptual cluster (n = {0})".format(len(db.entries)))
    ax.legend(fontsize=8, frameon=False, loc="upper left", ncol=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(1994.5, 2026.5)
    fig.tight_layout()
    fig.savefig(OUT_TREND)
    plt.close(fig)
    print(f"[03] Wrote {OUT_TREND}")

    # ---------- Keyword co-occurrence network ----------
    kw_total = Counter()
    pairs = Counter()
    for e in db.entries:
        kws = [normalize_keyword(k) for k in split_keywords(kw_field(e))]
        kws = [k for k in kws if k and k not in KEYWORD_BLACKLIST and len(k) >= 4]
        kws = list(dict.fromkeys(kws))  # dedup within an entry
        kw_total.update(kws)
        for a, b in combinations(sorted(kws), 2):
            pairs[(a, b)] += 1

    top_keywords = [k for k, _ in kw_total.most_common(80)]
    top_set = set(top_keywords)
    g = nx.Graph()
    for k in top_keywords:
        g.add_node(k, weight=kw_total[k])
    for (a, b), w in pairs.items():
        if a in top_set and b in top_set and w >= 4:
            g.add_edge(a, b, weight=w)

    # drop isolates if any
    g.remove_nodes_from([n for n in list(g.nodes()) if g.degree(n) == 0])

    print(f"[03] Network: {g.number_of_nodes()} nodes / {g.number_of_edges()} edges")

    fig2, ax2 = plt.subplots(figsize=(10, 8))
    pos = nx.spring_layout(g, seed=7, k=0.55, iterations=120)
    sizes = [40 + 12 * g.nodes[n]["weight"] ** 0.5 for n in g.nodes()]
    edge_w = [0.3 + 0.06 * g.edges[e]["weight"] for e in g.edges()]
    nx.draw_networkx_edges(g, pos, ax=ax2, width=edge_w, alpha=0.35, edge_color="#888888")
    nx.draw_networkx_nodes(g, pos, ax=ax2, node_size=sizes, node_color="#3a6ea5",
                           edgecolors="white", linewidths=0.6, alpha=0.9)
    nx.draw_networkx_labels(g, pos, ax=ax2, font_size=7, font_color="#222222")
    ax2.set_title("Keyword co-occurrence network (top {0} keywords, edge weight ≥ 4)".format(g.number_of_nodes()))
    ax2.axis("off")
    fig2.tight_layout()
    fig2.savefig(OUT_NET)
    plt.close(fig2)
    print(f"[03] Wrote {OUT_NET}")


if __name__ == "__main__":
    main()
