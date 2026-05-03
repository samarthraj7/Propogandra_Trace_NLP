"""
Phase 3 — Round-Trip Translation Evasion

Uses NLLB-200 (facebook/nllb-200-distilled-600M) to translate:
  English → Arabic → English
  English → Russian → English

FLORES-200 language codes used by NLLB-200:
  English : eng_Latn
  Arabic  : ara_Arab
  Russian : rus_Cyrl
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import torch
from tqdm import tqdm
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

log = logging.getLogger(__name__)

LANG_CODES = {
    "english": "eng_Latn",
    "arabic":  "ara_Arab",
    "russian": "rus_Cyrl",
}


class NLLBTranslator:
    """Wraps NLLB-200 for batch translation between any supported language pair."""

    def __init__(
        self,
        model_id: str = "facebook/nllb-200-distilled-600M",
        device: Optional[str] = None,
        max_length: int = 512,
    ):
        self.max_length = max_length
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"Loading NLLB-200: {model_id} on {self.device}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        ).to(self.device)
        self.model.eval()
        self.model_id = model_id

    def translate(
        self,
        texts:     List[str],
        src_lang:  str,
        tgt_lang:  str,
        batch_size: int = 8,
    ) -> List[str]:
        """Translate a list of texts from src_lang to tgt_lang."""
        self.tokenizer.src_lang = src_lang
        results = []
        tgt_lang_id = self.tokenizer.convert_tokens_to_ids(tgt_lang)

        for i in tqdm(range(0, len(texts), batch_size),
                      desc=f"{src_lang}→{tgt_lang}", unit="batch"):
            batch = texts[i : i + batch_size]
            enc = self.tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=self.max_length,
            ).to(self.device)
            with torch.no_grad():
                out = self.model.generate(
                    **enc,
                    forced_bos_token_id=tgt_lang_id,
                    max_length=self.max_length,
                    num_beams=4,
                )
            decoded = self.tokenizer.batch_decode(out, skip_special_tokens=True)
            results.extend(decoded)
        return results

    def round_trip(
        self,
        texts:     List[str],
        pivot_lang: str,
        src_lang:  str = "eng_Latn",
        batch_size: int = 8,
    ) -> List[str]:
        """
        Translate texts: src_lang → pivot_lang → src_lang.
        Returns the back-translated texts.
        """
        pivot_lang_code = LANG_CODES.get(pivot_lang.lower(), pivot_lang)
        log.info(f"Round-trip: {src_lang} → {pivot_lang_code} → {src_lang}")

        forward  = self.translate(texts, src_lang, pivot_lang_code, batch_size)
        backward = self.translate(forward, pivot_lang_code, src_lang, batch_size)
        return backward


# ─────────────────────────────────────────────────────────────────────────────
# Apply translation evasion to a corpus JSONL
# ─────────────────────────────────────────────────────────────────────────────

def apply_translation_evasion(
    corpus_path:  str,
    output_dir:   str,
    pivot_lang:   str = "arabic",
    model_id:     str = "facebook/nllb-200-distilled-600M",
    batch_size:   int = 8,
    max_records:  Optional[int] = None,
) -> str:
    """
    Read corpus JSONL, apply round-trip translation evasion, and save.

    Args:
        corpus_path: Path to input JSONL (Phase 2 output).
        output_dir:  Directory for evaded JSONL.
        pivot_lang:  'arabic' | 'russian' (or FLORES-200 code directly).
        model_id:    NLLB-200 model variant.
        batch_size:  Translation batch size.
        max_records: Limit records (None = all).
    Returns:
        Path to output JSONL.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    corpus_name = Path(corpus_path).stem
    lang_tag    = LANG_CODES.get(pivot_lang.lower(), pivot_lang).split("_")[0]
    out_path    = Path(output_dir) / f"{corpus_name}_evade_rtt_{lang_tag}.jsonl"

    records: List[Dict] = []
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))
            if max_records and len(records) >= max_records:
                break
    log.info(f"Loaded {len(records)} records for translation evasion.")

    translator = NLLBTranslator(model_id=model_id)
    originals  = [r["generated"] for r in records]
    evaded     = translator.round_trip(originals, pivot_lang=pivot_lang,
                                       batch_size=batch_size)

    with open(out_path, "w", encoding="utf-8") as out_f:
        for record, evaded_text in zip(records, evaded):
            new_record = {
                **record,
                "evaded_text":      evaded_text,
                "evasion_strategy": f"rtt_{lang_tag}",
                "evasion_model":    model_id,
                "pivot_lang":       pivot_lang,
            }
            out_f.write(json.dumps(new_record, ensure_ascii=False) + "\n")

    log.info(f"Translation evasion saved: {out_path}")
    return str(out_path)


def apply_all_translation_evasions(
    corpus_path: str,
    output_dir:  str,
    model_id:    str = "facebook/nllb-200-distilled-600M",
    batch_size:  int = 8,
    max_records: Optional[int] = None,
) -> Dict[str, str]:
    """Convenience: run both Arabic and Russian round-trip on one corpus file."""
    paths = {}
    for lang in ["arabic", "russian"]:
        paths[lang] = apply_translation_evasion(
            corpus_path=corpus_path,
            output_dir=output_dir,
            pivot_lang=lang,
            model_id=model_id,
            batch_size=batch_size,
            max_records=max_records,
        )
    return paths
