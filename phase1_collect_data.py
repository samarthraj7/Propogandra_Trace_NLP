#!/usr/bin/env python3
"""
Phase 1 — Data Collection
Run: python phase1_collect_data.py [--config config.yaml]

Downloads seed prompts from:
  • WTWT (HuggingFace)
  • GDELT conflict news API
  • SemEval-2020 Task 11 (propaganda articles)
  • Custom propaganda templates (fallback/supplement)

Output: data/raw/seed_prompts.jsonl
        data/raw/collection_stats.json
"""

import argparse
import logging
import sys
import yaml
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/raw/phase1.log", mode="w"),
    ],
)
log = logging.getLogger(__name__)

# Ensure src/ is on the path when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.data.collect import collect_all_prompts


def parse_args():
    p = argparse.ArgumentParser(description="PropagandaTrace — Phase 1: Data Collection")
    p.add_argument("--config",       default="config.yaml")
    p.add_argument("--num_wtwt",     type=int, default=None, help="Override # WTWT samples")
    p.add_argument("--num_gdelt",    type=int, default=None)
    p.add_argument("--num_semeval",  type=int, default=None)
    p.add_argument("--num_templates",type=int, default=None)
    p.add_argument("--output_dir",   default=None)
    return p.parse_args()


def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    ds_cfg   = cfg.get("dataset", {})
    raw_dir  = args.output_dir or cfg["paths"]["raw_data"]
    Path(raw_dir).mkdir(parents=True, exist_ok=True)

    # Use CLI overrides or config defaults
    num_wtwt      = args.num_wtwt      or ds_cfg.get("num_prompts", 2000)
    num_gdelt     = args.num_gdelt     or 500
    num_semeval   = args.num_semeval   or 200
    num_templates = args.num_templates or 1300
    seed          = ds_cfg.get("seed", 42)

    log.info("=" * 60)
    log.info("PropagandaTrace — Phase 1: Data Collection")
    log.info("=" * 60)
    log.info(f"Config:     {args.config}")
    log.info(f"Output dir: {raw_dir}")
    log.info(f"Targets — WTWT:{num_wtwt}  GDELT:{num_gdelt}  "
             f"SemEval:{num_semeval}  Templates:{num_templates}")

    prompts = collect_all_prompts(
        output_dir    = raw_dir,
        num_wtwt      = num_wtwt,
        num_gdelt     = num_gdelt,
        num_semeval   = num_semeval,
        num_templates = num_templates,
        seed          = seed,
    )

    log.info("-" * 60)
    log.info(f"Phase 1 complete.  Total seed prompts: {len(prompts)}")
    log.info(f"Output: {raw_dir}/seed_prompts.jsonl")
    log.info("-" * 60)


if __name__ == "__main__":
    main()
