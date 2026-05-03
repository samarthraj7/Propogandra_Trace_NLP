"""
Phase 3 — Paraphrase-based Evasion Attacks

Two strategies:
  (a) Lexical paraphrase  — T5-large  (single-pass rewriting)
  (b) Neural paraphrase   — PEGASUS-XSUM (aggressive structural rewriting)

Both modify the surface form while (ideally) preserving meaning,
which may disrupt the token-level watermark signal.
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional

import torch
from tqdm import tqdm
from transformers import (
    AutoTokenizer,
    AutoModelForSeq2SeqLM,
    pipeline,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Generic paraphraser wrapper
# ─────────────────────────────────────────────────────────────────────────────

class Paraphraser:
    def __init__(
        self,
        model_id: str,
        prefix: str = "",
        max_length: int = 512,
        num_beams: int = 4,
        device: Optional[str] = None,
    ):
        self.model_id  = model_id
        self.prefix    = prefix
        self.max_length = max_length
        self.num_beams  = num_beams
        self.device     = device or ("cuda" if torch.cuda.is_available() else "cpu")

        log.info(f"Loading paraphraser: {model_id} on {self.device}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model     = AutoModelForSeq2SeqLM.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        ).to(self.device)
        self.model.eval()

    def paraphrase(self, texts: List[str], batch_size: int = 8) -> List[str]:
        results = []
        for i in tqdm(range(0, len(texts), batch_size),
                      desc=f"Paraphrase ({self.model_id.split('/')[-1]})", unit="batch"):
            batch = texts[i : i + batch_size]
            inputs = [self.prefix + t for t in batch]
            enc = self.tokenizer(
                inputs,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.max_length,
            ).to(self.device)
            with torch.no_grad():
                out = self.model.generate(
                    **enc,
                    max_length=self.max_length,
                    num_beams=self.num_beams,
                    early_stopping=True,
                )
            decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)
            results.extend(decoded)
        return results


# ─────────────────────────────────────────────────────────────────────────────
# T5 Lexical Paraphraser
# ─────────────────────────────────────────────────────────────────────────────

def build_t5_paraphraser(model_id: str = "t5-large") -> Paraphraser:
    """
    T5-large for lexical paraphrase.
    We use the 'paraphrase: ' prefix (works with T5 fine-tuned on Quora/PAWS).
    Falls back to 't5-base' if large is unavailable.
    """
    return Paraphraser(
        model_id=model_id,
        prefix="paraphrase: ",
        max_length=512,
        num_beams=5,
    )


# ─────────────────────────────────────────────────────────────────────────────
# PEGASUS Neural Paraphraser
# ─────────────────────────────────────────────────────────────────────────────

def build_pegasus_paraphraser(model_id: str = "google/pegasus-xsum") -> Paraphraser:
    """
    PEGASUS-XSUM for aggressive neural paraphrase.
    Originally trained for extreme summarization; produces fluent rewrites
    that drastically alter surface structure while preserving core meaning.
    """
    return Paraphraser(
        model_id=model_id,
        prefix="",
        max_length=512,
        num_beams=8,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Apply evasion to a corpus JSONL file
# ─────────────────────────────────────────────────────────────────────────────

def apply_paraphrase_evasion(
    corpus_path: str,
    output_dir:  str,
    strategy:    str = "t5",        # 't5' | 'pegasus'
    model_id:    Optional[str] = None,
    batch_size:  int = 8,
    max_records: Optional[int] = None,
):
    """
    Read a corpus JSONL, apply paraphrase, and save evaded texts.

    Args:
        corpus_path: Path to input JSONL (from Phase 2).
        output_dir:  Directory to write evaded JSONL.
        strategy:    Paraphrase strategy: 't5' or 'pegasus'.
        model_id:    Override model HF id.
        batch_size:  Generation batch size.
        max_records: Limit number of records processed (None = all).
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    corpus_name = Path(corpus_path).stem
    out_path    = Path(output_dir) / f"{corpus_name}_evade_{strategy}.jsonl"

    # Load corpus
    records: List[Dict] = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
            if max_records and len(records) >= max_records:
                break
    log.info(f"Loaded {len(records)} records from {corpus_path}.")

    # Build paraphraser
    if strategy == "t5":
        mid = model_id or "t5-large"
        para = build_t5_paraphraser(mid)
    elif strategy == "pegasus":
        mid = model_id or "google/pegasus-xsum"
        para = build_pegasus_paraphraser(mid)
    else:
        raise ValueError(f"Unknown strategy: {strategy}. Use 't5' or 'pegasus'.")

    # Run paraphrase in batches
    originals = [r["generated"] for r in records]
    paraphrased = para.paraphrase(originals, batch_size=batch_size)

    # Write output
    with open(out_path, "w", encoding="utf-8") as out_f:
        for record, evaded_text in zip(records, paraphrased):
            new_record = {
                **record,
                "evaded_text":    evaded_text,
                "evasion_strategy": strategy,
                "evasion_model":  mid,
            }
            out_f.write(json.dumps(new_record, ensure_ascii=False) + "\n")

    log.info(f"Evasion ({strategy}) saved: {out_path}")
    return str(out_path)
