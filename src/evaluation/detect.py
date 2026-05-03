"""
Phase 4 — Detection & Attribution
Scores corpus and evasion JSONL files with KGW and Aaronson detectors,
computes detection rates and attribution accuracy, returns tidy DataFrames.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from transformers import AutoTokenizer

from src.watermarking.kgw import KGWDetector
from src.watermarking.aaronson import AaronsonDetector

log = logging.getLogger(__name__)

# ── Model metadata ────────────────────────────────────────────────────────────

MODEL_HF_IDS = {
    "mistral": "mistralai/Mistral-7B-Instruct-v0.2",
    "llama":   "meta-llama/Meta-Llama-3-8B-Instruct",
    "falcon":  "tiiuae/falcon-7b-instruct",
}

MODEL_KEYS = {
    "mistral": "MISTRAL_KEY_47A",
    "llama":   "LLAMA_KEY_47B",
    "falcon":  "FALCON_KEY_47C",
}

# Vocabulary sizes per model (used by detectors for green-list computation)
MODEL_VOCAB_SIZES = {
    "mistral": 32000,
    "llama":   128256,
    "falcon":  65024,
}

MODELS = list(MODEL_KEYS.keys())


# ── Tokenizer cache (load once per model) ────────────────────────────────────

_tok_cache: Dict[str, AutoTokenizer] = {}

def get_tokenizer(model_name: str) -> AutoTokenizer:
    if model_name not in _tok_cache:
        log.info(f"Loading tokenizer for {model_name} ...")
        tok = AutoTokenizer.from_pretrained(MODEL_HF_IDS[model_name], use_fast=True)
        _tok_cache[model_name] = tok
    return _tok_cache[model_name]

def encode(text: str, model_name: str) -> List[int]:
    tok = get_tokenizer(model_name)
    return tok.encode(text, add_special_tokens=False)


# ── Per-record scoring ────────────────────────────────────────────────────────

def score_kgw(token_ids: List[int], key: str, vocab_size: int,
              gamma: float = 0.25, z_threshold: float = 4.0) -> dict:
    det = KGWDetector(key=key, gamma=gamma, vocab_size=vocab_size)
    result = det.score(token_ids)
    result["threshold"] = z_threshold
    result["is_watermarked"] = result["z_score"] > z_threshold
    return result

def score_aaronson(token_ids: List[int], key: str, vocab_size: int,
                   threshold: float = 0.8) -> dict:
    det = AaronsonDetector(key=key, vocab_size=vocab_size, threshold=threshold)
    return det.score(token_ids)


# ── Attribution: test a text against all 3 model keys ────────────────────────

def attribute_kgw(token_ids: List[int], true_model: str,
                  gamma: float = 0.25, z_threshold: float = 4.0) -> dict:
    """
    Score token_ids against every model key. Predicted model = highest z-score.
    Returns scores per model plus attribution result.
    """
    scores = {}
    for m in MODELS:
        s = score_kgw(token_ids, MODEL_KEYS[m],
                      MODEL_VOCAB_SIZES[true_model],   # use generating model's vocab
                      gamma, z_threshold)
        scores[m] = s["z_score"]

    predicted = max(scores, key=scores.get)
    return {
        "true_model":       true_model,
        "predicted_model":  predicted,
        "attributed_correctly": predicted == true_model,
        "z_scores":         scores,
        "max_z":            scores[predicted],
        "is_detected":      scores[true_model] > z_threshold,
    }

def attribute_aaronson(token_ids: List[int], true_model: str,
                       threshold: float = 0.8) -> dict:
    scores = {}
    for m in MODELS:
        s = score_aaronson(token_ids, MODEL_KEYS[m],
                           MODEL_VOCAB_SIZES[true_model], threshold)
        scores[m] = s["mean_score"]

    predicted = max(scores, key=scores.get)
    return {
        "true_model":           true_model,
        "predicted_model":      predicted,
        "attributed_correctly": predicted == true_model,
        "mean_scores":          scores,
        "max_mean":             scores[predicted],
        "is_detected":          scores[true_model] > threshold,
    }


# ── Load JSONL files ──────────────────────────────────────────────────────────

def load_jsonl(path: str, max_records: Optional[int] = None) -> List[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
            if max_records and len(records) >= max_records:
                break
    return records


# ── Score a corpus file (baseline — uses stored token_ids) ───────────────────

def score_corpus_file(path: str, wm_cfg: dict,
                      max_records: Optional[int] = None) -> pd.DataFrame:
    """
    Score a Phase 2 corpus JSONL against both watermark schemes.
    Uses stored token_ids — no tokenizer needed.
    """
    records = load_jsonl(path, max_records)
    rows = []
    for r in records:
        token_ids  = r["token_ids"]
        true_model = r["model"]
        scheme     = r["scheme"]
        vocab_size = MODEL_VOCAB_SIZES[true_model]

        kgw_res = attribute_kgw(
            token_ids, true_model,
            gamma=wm_cfg["kgw"]["gamma"],
            z_threshold=wm_cfg["kgw"]["z_threshold"],
        )
        aar_res = attribute_aaronson(
            token_ids, true_model,
            threshold=wm_cfg["aaronson"]["score_threshold"],
        )

        rows.append({
            "idx":              r["idx"],
            "true_model":       true_model,
            "scheme":           scheme,
            "source":           "corpus",
            "evasion_strategy": "none",
            # KGW
            "kgw_z_score":              kgw_res["z_scores"][true_model],
            "kgw_detected":             kgw_res["is_detected"],
            "kgw_predicted_model":      kgw_res["predicted_model"],
            "kgw_attributed_correctly": kgw_res["attributed_correctly"],
            # Aaronson
            "aar_mean_score":           aar_res["mean_scores"][true_model],
            "aar_detected":             aar_res["is_detected"],
            "aar_predicted_model":      aar_res["predicted_model"],
            "aar_attributed_correctly": aar_res["attributed_correctly"],
            "num_tokens": r.get("num_tokens", len(token_ids)),
        })

    return pd.DataFrame(rows)


# ── Score an evasion file (re-tokenise the evaded text) ──────────────────────

def score_evasion_file(path: str, wm_cfg: dict,
                       max_records: Optional[int] = None) -> pd.DataFrame:
    """
    Score a Phase 3 evasion JSONL. Tokenises evaded_text with the generating
    model's tokenizer before running both detectors.
    """
    records = load_jsonl(path, max_records)
    rows = []
    for r in records:
        true_model = r["model"]
        strategy   = r.get("evasion_strategy", "unknown")
        evaded_text = r.get("evaded_text", "")
        vocab_size  = MODEL_VOCAB_SIZES[true_model]

        token_ids = encode(evaded_text, true_model)

        kgw_res = attribute_kgw(
            token_ids, true_model,
            gamma=wm_cfg["kgw"]["gamma"],
            z_threshold=wm_cfg["kgw"]["z_threshold"],
        )
        aar_res = attribute_aaronson(
            token_ids, true_model,
            threshold=wm_cfg["aaronson"]["score_threshold"],
        )

        rows.append({
            "idx":              r["idx"],
            "true_model":       true_model,
            "scheme":           r["scheme"],
            "source":           "evasion",
            "evasion_strategy": strategy,
            # KGW
            "kgw_z_score":              kgw_res["z_scores"][true_model],
            "kgw_detected":             kgw_res["is_detected"],
            "kgw_predicted_model":      kgw_res["predicted_model"],
            "kgw_attributed_correctly": kgw_res["attributed_correctly"],
            # Aaronson
            "aar_mean_score":           aar_res["mean_scores"][true_model],
            "aar_detected":             aar_res["is_detected"],
            "aar_predicted_model":      aar_res["predicted_model"],
            "aar_attributed_correctly": aar_res["attributed_correctly"],
            "num_tokens": len(token_ids),
        })

    return pd.DataFrame(rows)


# ── Aggregate metrics ─────────────────────────────────────────────────────────

def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group by (true_model, scheme, evasion_strategy) and compute:
      - KGW detection rate & attribution accuracy
      - Aaronson detection rate & attribution accuracy
    """
    grp = df.groupby(["true_model", "scheme", "evasion_strategy"])
    metrics = grp.agg(
        n=("idx", "count"),
        kgw_detection_rate=("kgw_detected", "mean"),
        kgw_attribution_acc=("kgw_attributed_correctly", "mean"),
        kgw_avg_z=("kgw_z_score", "mean"),
        aar_detection_rate=("aar_detected", "mean"),
        aar_attribution_acc=("aar_attributed_correctly", "mean"),
        aar_avg_mean_score=("aar_mean_score", "mean"),
    ).reset_index()

    # Convert to percentages for readability
    for col in ["kgw_detection_rate", "kgw_attribution_acc",
                "aar_detection_rate", "aar_attribution_acc"]:
        metrics[col] = (metrics[col] * 100).round(1)

    metrics["kgw_avg_z"]         = metrics["kgw_avg_z"].round(3)
    metrics["aar_avg_mean_score"] = metrics["aar_avg_mean_score"].round(3)

    return metrics


def pivot_detection_table(metrics: pd.DataFrame, scheme: str,
                           detector: str = "kgw") -> pd.DataFrame:
    """
    Produce the paper-style table:
      rows = models, columns = evasion strategies, values = detection rate (%).
    detector: 'kgw' or 'aar'
    """
    col = f"{detector}_detection_rate"
    sub = metrics[metrics["scheme"] == scheme][["true_model", "evasion_strategy", col]]
    table = sub.pivot(index="true_model", columns="evasion_strategy", values=col)
    # Reorder columns
    order = [c for c in ["none", "t5", "pegasus", "rtt_ara", "rtt_rus"] if c in table.columns]
    return table[order]
