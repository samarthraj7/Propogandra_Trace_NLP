#!/usr/bin/env python3
"""
Phase 3 — Evasion Attacks
Run: python phase3_evasion.py [--config config.yaml] [--strategy all]

Applies four evasion strategies to watermarked corpus files:
  (a) t5        — Lexical paraphrase via T5-large
  (b) pegasus   — Neural paraphrase via PEGASUS-XSUM
  (c) rtt_ara   — Round-trip translation: English → Arabic → English
  (d) rtt_rus   — Round-trip translation: English → Russian → English

Input:  data/corpus/<model>_<scheme>.jsonl
Output: data/evasion/<model>_<scheme>_evade_<strategy>.jsonl

Each output record includes the original and evaded text, ready for
Phase 4 watermark detection and attribution scoring.
"""

import argparse
import logging
import sys
import yaml
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from src.evasion.paraphrase   import apply_paraphrase_evasion
from src.evasion.translation  import apply_translation_evasion

VALID_STRATEGIES = ["t5", "pegasus", "rtt_arabic", "rtt_russian", "all"]


def parse_args():
    p = argparse.ArgumentParser(description="PropagandaTrace — Phase 3: Evasion")
    p.add_argument("--config",      default="config.yaml")
    p.add_argument("--corpus_dir",  default=None,
                   help="Directory containing Phase 2 JSONL files")
    p.add_argument("--output_dir",  default=None)
    p.add_argument("--strategy",    choices=VALID_STRATEGIES, default="all")
    p.add_argument("--max_records", type=int, default=None,
                   help="Limit records per file (useful for testing)")
    p.add_argument("--corpus_file", default=None,
                   help="Single corpus JSONL to process (overrides --corpus_dir)")
    return p.parse_args()


def get_corpus_files(corpus_dir: str):
    files = sorted(Path(corpus_dir).glob("*.jsonl"))
    if not files:
        log.error(f"No JSONL files found in {corpus_dir}. Run Phase 2 first.")
        sys.exit(1)
    return files


def run_strategy(strategy: str, corpus_path: str, output_dir: str,
                 cfg: dict, max_records: int):
    eva_cfg = cfg.get("evasion", {})
    nllb_id = eva_cfg.get("nllb_model", "facebook/nllb-200-distilled-600M")

    if strategy == "t5":
        return apply_paraphrase_evasion(
            corpus_path=corpus_path,
            output_dir=output_dir,
            strategy="t5",
            model_id=eva_cfg.get("t5_model", "t5-large"),
            max_records=max_records,
        )
    elif strategy == "pegasus":
        return apply_paraphrase_evasion(
            corpus_path=corpus_path,
            output_dir=output_dir,
            strategy="pegasus",
            model_id=eva_cfg.get("pegasus_model", "google/pegasus-xsum"),
            max_records=max_records,
        )
    elif strategy == "rtt_arabic":
        return apply_translation_evasion(
            corpus_path=corpus_path,
            output_dir=output_dir,
            pivot_lang="arabic",
            model_id=nllb_id,
            max_records=max_records,
        )
    elif strategy == "rtt_russian":
        return apply_translation_evasion(
            corpus_path=corpus_path,
            output_dir=output_dir,
            pivot_lang="russian",
            model_id=nllb_id,
            max_records=max_records,
        )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")


def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    corpus_dir = args.corpus_dir or cfg["paths"]["corpus"]
    output_dir = args.output_dir or cfg["paths"]["evasion"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Determine corpus files to process
    if args.corpus_file:
        corpus_files = [Path(args.corpus_file)]
    else:
        corpus_files = get_corpus_files(corpus_dir)

    # Determine strategies
    if args.strategy == "all":
        strategies = ["t5", "pegasus", "rtt_arabic", "rtt_russian"]
    else:
        strategies = [args.strategy]

    log.info("=" * 60)
    log.info("PropagandaTrace — Phase 3: Evasion Attacks")
    log.info("=" * 60)
    log.info(f"Corpus files:  {[f.name for f in corpus_files]}")
    log.info(f"Strategies:    {strategies}")
    log.info(f"Output dir:    {output_dir}")
    if args.max_records:
        log.info(f"Max records:   {args.max_records} (test mode)")

    results = {}
    for corpus_path in corpus_files:
        for strategy in strategies:
            key = f"{corpus_path.stem}+{strategy}"
            log.info(f"\n→ {corpus_path.name}  strategy={strategy}")
            try:
                out = run_strategy(
                    strategy=strategy,
                    corpus_path=str(corpus_path),
                    output_dir=output_dir,
                    cfg=cfg,
                    max_records=args.max_records,
                )
                results[key] = {"status": "ok", "output": out}
            except Exception as e:
                log.error(f"Failed {key}: {e}")
                results[key] = {"status": "error", "error": str(e)}

    log.info("\n" + "=" * 60)
    log.info("Phase 3 Summary:")
    for k, v in results.items():
        status = "✓" if v["status"] == "ok" else "✗"
        log.info(f"  {status}  {k}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
