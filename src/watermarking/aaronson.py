"""
Aaronson / EXP Watermarking Scheme
Aaronson (2022) — Cryptographic watermarking of language models.
https://scottaaronson.blog/?p=6823

At each position t:
  1. Derive a random vector r ∈ [0,1]^|V| via keyed PRNG(key, t).
  2. Sample: token = argmax_i { log(p_i) − log(−log(r_i)) }
     (Gumbel-max trick — implements r_i^{1/p_i} sampling).
Detection: for token w_t at position t, the score
  s_t = −log(1 − r_{t, w_t})
aggregated over T tokens gives a high score for watermarked text.
"""

import hashlib
import logging
import math
from typing import List, Optional

import torch
from transformers import LogitsProcessor

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LogitsProcessor
# ─────────────────────────────────────────────────────────────────────────────

class AaronsonWatermarkLogitsProcessor(LogitsProcessor):
    """
    Implements the EXP (exponential) watermark via Gumbel-max sampling.

    The processor replaces logits with:
        modified_logit_i = log(p_i) − log(−log(r_i + ε))
    so argmax recovers r_i^{1/p_i} sampling deterministically.

    Args:
        key:        Secret key string.
        vocab_size: Vocabulary size.
    """

    def __init__(self, key: str, vocab_size: int = 32000):
        self.key = key
        self.vocab_size = vocab_size
        self._position = 0   # call reset() between independent generations

    def reset(self):
        self._position = 0

    def _get_r(self, position: int, device: torch.device) -> torch.Tensor:
        """Deterministic uniform [0,1] vector for this (key, position)."""
        seed_bytes = hashlib.sha256(
            f"{self.key}:{position}".encode("utf-8")
        ).digest()
        seed = int.from_bytes(seed_bytes[:4], "big")
        rng = torch.Generator()
        rng.manual_seed(seed)
        return torch.rand(self.vocab_size, generator=rng, dtype=torch.float32).to(device)

    def __call__(
        self,
        input_ids: torch.LongTensor,
        scores:    torch.FloatTensor,
    ) -> torch.FloatTensor:
        for b in range(scores.shape[0]):
            r = self._get_r(self._position, scores.device)
            log_probs = torch.log_softmax(scores[b], dim=-1)
            # Gumbel-max: sample = argmax( log(p) + Gumbel(0,1) )
            # where Gumbel = -log(-log(r)) — keyed so same r every time
            gumbel = -torch.log(-torch.log(r.clamp(min=1e-10)))
            scores[b] = log_probs + gumbel
        self._position += 1
        return scores


# ─────────────────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────────────────

class AaronsonDetector:
    """
    Detect Aaronson watermark via per-token score aggregation.

    For each position t with observed token w_t:
        s_t = −log(1 − r_{t, w_t})
    The total score S = mean(s_t) is large when r_{t, w_t} is close to 1,
    which happens with high probability for watermarked text.
    """

    def __init__(self, key: str, vocab_size: int = 32000, threshold: float = 0.8):
        self.key = key
        self.vocab_size = vocab_size
        self.threshold = threshold

    def _get_r_value(self, position: int, token_id: int) -> float:
        seed_bytes = hashlib.sha256(
            f"{self.key}:{position}".encode("utf-8")
        ).digest()
        seed = int.from_bytes(seed_bytes[:4], "big")
        rng = torch.Generator()
        rng.manual_seed(seed)
        r = torch.rand(self.vocab_size, generator=rng)
        return r[token_id].item()

    def score(self, token_ids: List[int]) -> dict:
        """
        Args:
            token_ids: Encoded token IDs (must NOT include the prompt tokens).
        Returns:
            dict with mean_score, is_watermarked.
        """
        if not token_ids:
            return {"mean_score": 0.0, "is_watermarked": False, "T": 0}

        scores = []
        for t, tok in enumerate(token_ids):
            r_val = self._get_r_value(t, tok)
            s = -math.log(1.0 - r_val + 1e-10)
            scores.append(s)

        mean_s = sum(scores) / len(scores)
        return {
            "mean_score":    round(mean_s, 4),
            "is_watermarked": mean_s > self.threshold,
            "T":              len(scores),
            "key":            self.key,
        }

    def score_text(self, text: str, tokenizer) -> dict:
        ids = tokenizer.encode(text, add_special_tokens=False)
        return self.score(ids)
