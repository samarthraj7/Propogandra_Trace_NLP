"""
Phase 1 — Data Collection
Collects seed prompts from:
  1. WTWT dataset (HuggingFace)
  2. GDELT conflict news API (no key required)
  3. SemEval-2020 Task 11 (propaganda labels)
  4. Custom propaganda prompt templates (fallback)
"""

import os
import json
import random
import logging
import requests
import pandas as pd
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 1.  WTWT Dataset (HuggingFace)
# ─────────────────────────────────────────────────────────────────────────────

def load_wtwt(num_samples: int = 4000, seed: int = 42) -> List[str]:
    """Download WTWT (Conforti et al., 2020) via HuggingFace datasets."""
    try:
        from datasets import load_dataset
        log.info("Loading WTWT dataset from HuggingFace …")
        # Primary HF path
        ds = load_dataset("conforti/wtwt", split="train", trust_remote_code=True)
        texts = [row["tweet"] for row in ds if len(row.get("tweet", "")) > 30]
        random.seed(seed)
        random.shuffle(texts)
        log.info(f"WTWT: {len(texts)} tweets loaded; sampling {min(num_samples, len(texts))}.")
        return texts[:num_samples]
    except Exception as e:
        log.warning(f"WTWT HuggingFace load failed ({e}); trying alternate id …")

    try:
        from datasets import load_dataset
        ds = load_dataset("tweet_eval", "stance_feminist", split="train")
        texts = [row["text"] for row in ds if len(row.get("text", "")) > 30]
        random.seed(seed)
        random.shuffle(texts)
        log.warning("Falling back to tweet_eval stance dataset as proxy for WTWT.")
        return texts[:num_samples]
    except Exception as e2:
        log.warning(f"Alternate dataset load also failed ({e2}).")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 2.  GDELT Conflict News (free public API)
# ─────────────────────────────────────────────────────────────────────────────

GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"

CONFLICT_QUERIES = [
    "military offensive attack",
    "war propaganda disinformation",
    "wartime civilian casualties",
    "military operation ceasefire",
    "conflict geopolitical tension",
    "armed forces strategic advance",
]


def fetch_gdelt_articles(max_articles: int = 500, days_back: int = 365) -> List[str]:
    """
    Fetch conflict-related article snippets from GDELT v2 DocAPI.
    Returns a list of headline+snippet strings.
    """
    results = []
    end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=days_back)
    startdatetime = start_dt.strftime("%Y%m%d%H%M%S")
    enddatetime   = end_dt.strftime("%Y%m%d%H%M%S")

    for query in CONFLICT_QUERIES:
        if len(results) >= max_articles:
            break
        params = {
            "query":    query,
            "mode":     "ArtList",
            "maxrecords": 50,
            "startdatetime": startdatetime,
            "enddatetime":   enddatetime,
            "format":   "json",
        }
        try:
            r = requests.get(GDELT_API, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            articles = data.get("articles", [])
            for art in articles:
                title   = art.get("title", "").strip()
                snippet = art.get("seendescription", "").strip()
                if title and len(title) > 10:
                    text = f"{title}. {snippet}" if snippet else title
                    results.append(text)
            log.info(f"GDELT query '{query}': {len(articles)} articles fetched.")
        except Exception as e:
            log.warning(f"GDELT query '{query}' failed: {e}")

    log.info(f"GDELT total collected: {len(results)} article snippets.")
    return results[:max_articles]


# ─────────────────────────────────────────────────────────────────────────────
# 3.  SemEval-2020 Task 11 (propaganda fragment detection)
# ─────────────────────────────────────────────────────────────────────────────

SEMEVAL_GITHUB = (
    "https://raw.githubusercontent.com/SemEval/SemEval2020/master/"
    "task11/data/dev-articles/article736757.txt"
)

def fetch_semeval_samples(num_samples: int = 200) -> List[str]:
    """
    Fetch a handful of SemEval-2020 Task 11 propaganda article samples.
    Falls back gracefully if the URL is unavailable.
    """
    # Article IDs from the public dev set (subset)
    article_ids = [736757, 724865, 733677, 757627, 760153,
                   762099, 763061, 765186, 766178, 778510]
    base = (
        "https://raw.githubusercontent.com/SemEval/SemEval2020/master/"
        "task11/data/dev-articles/article{}.txt"
    )
    texts = []
    for aid in article_ids:
        try:
            r = requests.get(base.format(aid), timeout=15)
            if r.status_code == 200 and len(r.text) > 50:
                # Split into sentences / short paragraphs
                paragraphs = [p.strip() for p in r.text.split("\n\n") if len(p.strip()) > 40]
                texts.extend(paragraphs[:20])
                log.info(f"SemEval article {aid}: {len(paragraphs)} paragraphs.")
        except Exception as e:
            log.warning(f"SemEval article {aid} fetch failed: {e}")
    log.info(f"SemEval total collected: {len(texts)} paragraphs.")
    return texts[:num_samples]


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Custom Propaganda Prompt Templates (always available fallback)
# ─────────────────────────────────────────────────────────────────────────────

def generate_template_prompts(num_prompts: int = 1000, seed: int = 42) -> List[str]:
    """Generate filled propaganda prompts from templates in prompts.py."""
    from src.data.prompts import get_all_templates, fill_template
    rng = random.Random(seed)
    templates = get_all_templates()
    prompts = []
    for _ in range(num_prompts):
        tpl = rng.choice(templates)
        prompts.append(fill_template(tpl, rng))
    return prompts


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Combined Collection Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def collect_all_prompts(
    output_dir: str = "data/raw",
    num_wtwt:      int = 2000,
    num_gdelt:     int = 500,
    num_semeval:   int = 200,
    num_templates: int = 1300,
    seed:          int = 42,
) -> List[Dict]:
    """
    Collect seed prompts from all sources, deduplicate, and save to disk.
    Returns a list of dicts: {text, source, idx}.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    all_prompts = []

    # WTWT
    wtwt = load_wtwt(num_wtwt, seed)
    for t in wtwt:
        all_prompts.append({"text": t, "source": "wtwt"})

    # GDELT
    gdelt = fetch_gdelt_articles(num_gdelt)
    for t in gdelt:
        all_prompts.append({"text": t, "source": "gdelt"})

    # SemEval
    semeval = fetch_semeval_samples(num_semeval)
    for t in semeval:
        all_prompts.append({"text": t, "source": "semeval2020"})

    # Templates
    templates = generate_template_prompts(num_templates, seed)
    for t in templates:
        all_prompts.append({"text": t, "source": "template"})

    # Deduplicate by text content
    seen = set()
    deduped = []
    for item in all_prompts:
        key = item["text"].strip().lower()[:100]
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Add sequential index
    for i, item in enumerate(deduped):
        item["idx"] = i

    # Save
    out_path = Path(output_dir) / "seed_prompts.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for item in deduped:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    stats_path = Path(output_dir) / "collection_stats.json"
    stats = {
        "total":        len(deduped),
        "wtwt":         sum(1 for x in deduped if x["source"] == "wtwt"),
        "gdelt":        sum(1 for x in deduped if x["source"] == "gdelt"),
        "semeval2020":  sum(1 for x in deduped if x["source"] == "semeval2020"),
        "template":     sum(1 for x in deduped if x["source"] == "template"),
        "collected_at": datetime.utcnow().isoformat() + "Z",
    }
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    log.info(f"Collection complete. {len(deduped)} prompts saved to {out_path}")
    log.info(f"Source breakdown: {stats}")
    return deduped
