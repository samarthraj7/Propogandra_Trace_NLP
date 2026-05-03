"""
Phase 2 — Watermarked Corpus Generation

Loads each LLM (Mistral-7B, LLaMA-3-8B, Falcon-7B) with 4-bit quantization,
attaches the appropriate watermark LogitsProcessor, and generates texts from
seed prompts.  Outputs one JSONL file per model.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional

import torch
import yaml
from tqdm import tqdm
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    LogitsProcessorList,
)

from src.watermarking.kgw import KGWWatermarkLogitsProcessor
from src.watermarking.aaronson import AaronsonWatermarkLogitsProcessor

log = logging.getLogger(__name__)

CHAT_WRAP = {
    "mistral": (
        "[INST] You are a wartime analyst. Generate the following text exactly as instructed:\n"
        "{prompt}\n[/INST]"
    ),
    "llama": (
        "<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n"
        "You are a wartime analyst. Generate the following text exactly as instructed:\n"
        "{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n"
    ),
    "falcon": (
        "User: You are a wartime analyst. Generate the following text exactly as instructed:\n"
        "{prompt}\nAssistant:"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Model Loading
# ─────────────────────────────────────────────────────────────────────────────

def load_model_and_tokenizer(model_cfg: dict, load_4bit: bool = True):
    hf_id = model_cfg["hf_id"]
    log.info(f"Loading {hf_id} …")

    bnb_config = None
    if load_4bit and torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

    tokenizer = AutoTokenizer.from_pretrained(hf_id, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        hf_id,
        quantization_config=bnb_config,
        device_map="auto" if torch.cuda.is_available() else "cpu",
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
    )
    model.eval()
    log.info(f"  {hf_id} loaded on {next(model.parameters()).device}.")
    return model, tokenizer


# ─────────────────────────────────────────────────────────────────────────────
# Watermark processor factory
# ─────────────────────────────────────────────────────────────────────────────

def build_processors(
    scheme: str,
    key: str,
    vocab_size: int,
    gamma: float = 0.25,
    delta: float = 2.0,
) -> LogitsProcessorList:
    if scheme == "kgw":
        proc = KGWWatermarkLogitsProcessor(
            key=key, gamma=gamma, delta=delta, vocab_size=vocab_size
        )
    elif scheme == "aaronson":
        proc = AaronsonWatermarkLogitsProcessor(key=key, vocab_size=vocab_size)
    else:
        raise ValueError(f"Unknown watermark scheme: {scheme}")
    return LogitsProcessorList([proc]), proc


# ─────────────────────────────────────────────────────────────────────────────
# Single-model generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_for_model(
    model_name: str,
    model_cfg: dict,
    prompts: List[Dict],
    gen_cfg: dict,
    wm_cfg: dict,
    scheme: str,
    output_dir: str,
) -> str:
    """
    Generate watermarked texts for one model and save to a JSONL file.

    Args:
        model_name:  Short name ('mistral', 'llama', 'falcon').
        model_cfg:   Config dict with 'hf_id', 'key', 'load_4bit'.
        prompts:     List of dicts from collect.py.
        gen_cfg:     Generation config (min/max tokens, batch_size, …).
        wm_cfg:      Watermark config (gamma, delta, …).
        scheme:      'kgw' or 'aaronson'.
        output_dir:  Directory to write <model_name>_<scheme>.jsonl.

    Returns:
        Path to the output file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(output_dir) / f"{model_name}_{scheme}.jsonl"

    # Resume: count already-generated lines
    done = 0
    if out_path.exists():
        with open(out_path, "r", encoding="utf-8") as fh:
            done = sum(1 for _ in fh)
        log.info(f"Resuming {out_path.name}: {done} already done.")

    target = gen_cfg["texts_per_model"]
    prompts_to_use = (prompts * ((target // len(prompts)) + 2))[:target]
    remaining = prompts_to_use[done:]

    if not remaining:
        log.info(f"{out_path.name}: already complete.")
        return str(out_path)

    model, tokenizer = load_model_and_tokenizer(model_cfg, model_cfg.get("load_4bit", True))
    vocab_size = len(tokenizer)

    proc_list, proc_obj = build_processors(
        scheme=scheme,
        key=model_cfg["key"],
        vocab_size=vocab_size,
        gamma=wm_cfg["kgw"]["gamma"],
        delta=wm_cfg["kgw"]["delta"],
    )

    chat_template = CHAT_WRAP.get(model_name, "{prompt}")
    batch_size    = gen_cfg["batch_size"]

    with open(out_path, "a", encoding="utf-8") as out_f:
        for i in tqdm(range(0, len(remaining), batch_size),
                      desc=f"{model_name}/{scheme}", unit="batch"):
            batch = remaining[i : i + batch_size]
            # Reset Aaronson position counter for each new text in batch
            if scheme == "aaronson":
                proc_obj.reset()

            formatted = [
                chat_template.format(prompt=item["text"]) for item in batch
            ]
            enc = tokenizer(
                formatted,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            enc = {k: v.to(model.device) for k, v in enc.items()}

            with torch.no_grad():
                output_ids = model.generate(
                    **enc,
                    logits_processor=proc_list,
                    min_new_tokens=gen_cfg["min_new_tokens"],
                    max_new_tokens=gen_cfg["max_new_tokens"],
                    do_sample=gen_cfg["do_sample"],
                    temperature=gen_cfg["temperature"],
                    pad_token_id=tokenizer.pad_token_id,
                )

            prompt_len = enc["input_ids"].shape[1]
            for j, (item, ids) in enumerate(zip(batch, output_ids)):
                new_ids = ids[prompt_len:].tolist()
                text    = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
                record  = {
                    "idx":          done + (i * batch_size) + j,
                    "model":        model_name,
                    "scheme":       scheme,
                    "key":          model_cfg["key"],
                    "prompt_idx":   item.get("idx", -1),
                    "prompt_src":   item.get("source", "unknown"),
                    "prompt":       item["text"],
                    "generated":    text,
                    "token_ids":    new_ids,
                    "num_tokens":   len(new_ids),
                }
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    log.info(f"Done: {out_path}")
    # Free GPU memory
    del model
    torch.cuda.empty_cache() if torch.cuda.is_available() else None
    return str(out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Full corpus pipeline
# ─────────────────────────────────────────────────────────────────────────────

def generate_full_corpus(
    prompts: List[Dict],
    cfg_path: str = "config.yaml",
    output_dir: str = "data/corpus",
    schemes: List[str] = ("kgw", "aaronson"),
):
    """
    Loop over all models × schemes and generate the full 9K corpus.
    Each model × scheme produces one JSONL file.
    """
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    gen_cfg = cfg["generation"]
    wm_cfg  = cfg["watermark"]
    model_names = ["mistral", "llama", "falcon"]

    summary = {}
    for model_name in model_names:
        model_cfg = cfg["models"][model_name]
        for scheme in schemes:
            log.info(f"\n{'='*60}")
            log.info(f"Model: {model_name}  Scheme: {scheme}")
            log.info(f"{'='*60}")
            t0 = time.time()
            path = generate_for_model(
                model_name=model_name,
                model_cfg=model_cfg,
                prompts=prompts,
                gen_cfg=gen_cfg,
                wm_cfg=wm_cfg,
                scheme=scheme,
                output_dir=output_dir,
            )
            summary[f"{model_name}_{scheme}"] = {
                "path": path,
                "elapsed_s": round(time.time() - t0, 1),
            }

    log.info("\nCorpus generation summary:")
    for k, v in summary.items():
        log.info(f"  {k}: {v['path']} ({v['elapsed_s']}s)")
    return summary
