#!/usr/bin/env python3
"""
Phase 2 — Watermarked Corpus Generation
Run: python phase2_generate_corpus.py [--config config.yaml] [--model mistral] [--scheme kgw]

Loads each LLM with 4-bit quantization, attaches KGW or Aaronson watermark,
and generates propaganda texts from Phase 1 seed prompts.

Target: 3,000 texts × 3 models × 2 schemes = 18,000 total records
        (primary attribution corpus: 9,000 with one watermark per model)

Supports resuming interrupted runs.

Prerequisites:
  • CUDA GPU with ≥ 16 GB VRAM (or 24 GB for 8B models without 4-bit)
  • HuggingFace token with access to Mistral / Llama gated repos
  • Phase 1 complete: data/raw/seed_prompts.jsonl must exist

Output: data/corpus/<model>_<scheme>.jsonl
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from src.generation.generate import generate_full_corpus, generate_for_model

VALID_MODELS  = ["mistral", "llama", "falcon", "all"]
VALID_SCHEMES = ["kgw", "aaronson", "both"]


def parse_args():
    p = argparse.ArgumentParser(description="PropagandaTrace — Phase 2: Corpus Generation")
    p.add_argument("--config",     default="config.yaml")
    p.add_argument("--model",      choices=VALID_MODELS,  default="all",
                   help="Which model to run (default: all)")
    p.add_argument("--scheme",     choices=VALID_SCHEMES, default="both",
                   help="Watermark scheme (default: both)")
    p.add_argument("--prompts",    default="data/raw/seed_prompts.jsonl",
                   help="Path to seed prompts from Phase 1")
    p.add_argument("--output_dir", default=None)
    p.add_argument("--max_texts",  type=int, default=None,
                   help="Override texts_per_model (for quick testing)")
    return p.parse_args()


def load_prompts(path: str):
    if not Path(path).exists():
        log.error(f"Seed prompts not found: {path}")
        log.error("Run phase1_collect_data.py first.")
        sys.exit(1)
    prompts = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            prompts.append(json.loads(line))
    log.info(f"Loaded {len(prompts)} seed prompts from {path}.")
    return prompts


def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    output_dir = args.output_dir or cfg["paths"]["corpus"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    if args.max_texts:
        cfg["generation"]["texts_per_model"] = args.max_texts
        log.info(f"Overriding texts_per_model → {args.max_texts}")

    prompts = load_prompts(args.prompts)

    models  = ["mistral", "llama", "falcon"] if args.model  == "all"  else [args.model]
    schemes = ["kgw", "aaronson"]            if args.scheme == "both" else [args.scheme]

    log.info("=" * 60)
    log.info("PropagandaTrace — Phase 2: Watermarked Corpus Generation")
    log.info("=" * 60)
    log.info(f"Models:  {models}")
    log.info(f"Schemes: {schemes}")
    log.info(f"Texts per model: {cfg['generation']['texts_per_model']}")

    for model_name in models:
        model_cfg = cfg["models"][model_name]
        for scheme in schemes:
            log.info(f"\n→ Generating: model={model_name}  scheme={scheme}")
            generate_for_model(
                model_name=model_name,
                model_cfg=model_cfg,
                prompts=prompts,
                gen_cfg=cfg["generation"],
                wm_cfg=cfg["watermark"],
                scheme=scheme,
                output_dir=output_dir,
            )

    log.info("\nPhase 2 complete.")
    log.info(f"Corpus files in: {output_dir}/")


if __name__ == "__main__":
    main()
