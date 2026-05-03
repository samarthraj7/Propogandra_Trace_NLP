"""
KGW Watermarking Scheme
Kirchenbauer et al. (2023) "A Watermark for Large Language Models"
https://arxiv.org/abs/2301.10226

At each generation step:
  1. Use a keyed hash of the previous token to partition vocab into
     green (γ·|V|) and red ((1−γ)·|V|) lists.
  2. Add δ to every green-token logit before sampling.
Detection: compute z-score of green-token fraction over the generated text.
"""

import hashlib
import math
import logging
from typing import List, Optional

import torch
from transformers import LogitsProcessor

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# LogitsProcessor (injected during generation)
# ─────────────────────────────────────────────────────────────────────────────

class KGWWatermarkLogitsProcessor(LogitsProcessor):
    """
    HuggingFace LogitsProcessor that applies the KGW green-list bias.

    Args:
        key:        Secret string key unique to the deploying model.
        gamma:      Fraction of vocabulary placed in the green list (default 0.25).
        delta:      Logit bias added to green tokens (default 2.0).
        vocab_size: Size of the model vocabulary.
        ignore_ids: Token IDs to skip (e.g., padding, EOS).
    """

    def __init__(
        self,
        key: str,
        gamma: float = 0.25,
        delta: float = 2.0,
        vocab_size: int = 32000,
        ignore_ids: Optional[List[int]] = None,
    ):
        self.key = key
        self.gamma = gamma
        self.delta = delta
        self.vocab_size = vocab_size
        self.ignore_ids = set(ignore_ids or [])

    # ------------------------------------------------------------------
    def _green_list(self, prev_token_id: int) -> torch.Tensor:
        """Return green-list token indices for this context token."""
        seed_bytes = hashlib.sha256(
            f"{self.key}:{prev_token_id}".encode("utf-8")
        ).digest()
        seed = int.from_bytes(seed_bytes[:4], "big")
        rng = torch.Generator()
        rng.manual_seed(seed)
        perm = torch.randperm(self.vocab_size, generator=rng)
        return perm[: int(self.gamma * self.vocab_size)]

    # ------------------------------------------------------------------
    def __call__(
        self,
        input_ids: torch.LongTensor,   # (batch, seq_len)
        scores:    torch.FloatTensor,  # (batch, vocab)
    ) -> torch.FloatTensor:
        for b in range(input_ids.shape[0]):
            prev = input_ids[b, -1].item()
            if prev in self.ignore_ids:
                continue
            green = self._green_list(prev).to(scores.device)
            scores[b, green] += self.delta
        return scores


# ─────────────────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────────────────

class KGWDetector:
    """
    Detect KGW watermark in a decoded text by computing the z-score.

    z = (|green tokens| − γ·T) / sqrt(γ(1−γ)·T)
    where T = number of testable tokens (all except first).
    """

    def __init__(self, key: str, gamma: float = 0.25, vocab_size: int = 32000):
        self.key = key
        self.gamma = gamma
        self.vocab_size = vocab_size

    def _green_list_set(self, prev_token_id: int):
        seed_bytes = hashlib.sha256(
            f"{self.key}:{prev_token_id}".encode("utf-8")
        ).digest()
        seed = int.from_bytes(seed_bytes[:4], "big")
        rng = torch.Generator()
        rng.manual_seed(seed)
        perm = torch.randperm(self.vocab_size, generator=rng)
        return set(perm[: int(self.gamma * self.vocab_size)].tolist())

    def score(self, token_ids: List[int]) -> dict:
        """
        Args:
            token_ids: Encoded token IDs of the text to test.
        Returns:
            dict with z_score, green_fraction, T, is_watermarked.
        """
        if len(token_ids) < 2:
            return {"z_score": 0.0, "green_fraction": 0.0, "T": 0, "is_watermarked": False}

        green_count = 0
        T = len(token_ids) - 1
        for i in range(1, len(token_ids)):
            gl = self._green_list_set(token_ids[i - 1])
            if token_ids[i] in gl:
                green_count += 1

        gamma = self.gamma
        z = (green_count - gamma * T) / math.sqrt(gamma * (1 - gamma) * T)
        return {
            "z_score":        round(z, 4),
            "green_fraction": round(green_count / T, 4),
            "green_count":    green_count,
            "T":              T,
            "is_watermarked": z > 4.0,
        }

    def score_text(self, text: str, tokenizer) -> dict:
        ids = tokenizer.encode(text, add_special_tokens=False)
        result = self.score(ids)
        result["key"] = self.key
        return result
