# PropagandaTrace — Watermark-Based Source Attribution of AI-Generated Propaganda

**CS 544 Natural Language Processing | University of Southern California | Team 47**

---

## Overview

PropagandaTrace is a 4-phase NLP research framework that addresses a critical gap in AI-text forensics: existing detectors can answer *"Is this AI-generated?"* but not *"Which model generated it?"* — a distinction that matters enormously when state actors use multiple LLMs to mass-produce wartime disinformation.

The system embeds unique cryptographic watermarks into each LLM at generation time, generates a large corpus of watermarked propaganda texts, simulates real-world evasion attacks, and then recovers the source model through forensic watermark detection and multi-class attribution scoring.

---

## Project Structure

```
project/
├── config.yaml                  # Central configuration (models, watermark params, paths)
├── requirements.txt             # Python dependencies
├── phase1_collect_data.py       # Seed prompt collection from 4 data sources
├── phase2_generate_corpus.py    # Watermarked corpus generation (3 LLMs × 2 schemes)
├── phase3_evasion.py            # Evasion attack simulation (4 strategies)
├── phase4_evaluate.py           # Detection, attribution, metrics & plots
├── PropagandaTrace_Colab.ipynb  # End-to-end notebook for Google Colab
├── src/
│   ├── data/
│   │   ├── collect.py           # Data loaders: WTWT, GDELT, SemEval-2020, templates
│   │   └── prompts.py           # 20 propaganda templates with slot-filling
│   ├── generation/
│   │   └── generate.py          # LLM loader (4-bit), watermark attachment, batch generation
│   ├── watermarking/
│   │   ├── kgw.py               # KGW scheme: LogitsProcessor + z-score detector
│   │   └── aaronson.py          # Aaronson/EXP scheme: Gumbel-max sampler + mean-score detector
│   ├── evasion/
│   │   ├── paraphrase.py        # T5-Large and PEGASUS-XSUM wrappers
│   │   └── translation.py       # NLLB-200 round-trip translation (Arabic, Russian)
│   └── evaluation/
│       └── detect.py            # Score all files, compute metrics, run attribution
└── data/
    ├── raw/                     # Phase 1 output (seed_prompts.jsonl, stats)
    ├── corpus/                  # Phase 2 output (6 JSONL files, 18,000 texts)
    ├── evasion/                 # Phase 3 output (24 JSONL files, evaded texts)
    └── results/                 # Phase 4 output (CSVs, plots)
```

---

## The 4-Phase Pipeline

### Phase 1 — Seed Prompt Collection
Collects real-world propaganda-style text snippets from four sources to use as generation prompts:

| Source | Description | Count |
|--------|-------------|-------|
| **WTWT** | Will-They-Won't-They stance tweets (Conforti et al., 2020) — real social-media rhetoric loaded from HuggingFace | ~597 |
| **GDELT** | Global Database of Events — conflict news snippets via free public API | ~500 (API-dependent) |
| **SemEval-2020 Task 11** | Propaganda fragment detection dataset (14 propaganda techniques) from GitHub | ~400 (fetch-dependent) |
| **Custom Templates** | 20 fill-in-the-blank propaganda templates (10 military reports, 10 political commentaries) | ~629 |

Output: `data/raw/seed_prompts.jsonl` (~1,226–4,000 prompts depending on API availability)

### Phase 2 — Watermarked Corpus Generation
Generates 18,000 propaganda texts using 3 LLMs, each assigned a unique secret watermark key:

| Model | HuggingFace ID | Watermark Key |
|-------|---------------|---------------|
| Mistral-7B-Instruct | `mistralai/Mistral-7B-Instruct-v0.2` | `MISTRAL_KEY_47A` |
| LLaMA-3-8B-Instruct | `meta-llama/Meta-Llama-3-8B-Instruct` | `LLAMA_KEY_47B` |
| Falcon-7B-Instruct | `tiiuae/falcon-7b-instruct` | `FALCON_KEY_47C` |

Two watermarking schemes are applied per model:
- **KGW** (Kirchenbauer et al., ICML 2023): Hashes (key, previous token) to partition the vocabulary into a green list (25% of tokens). Adds a logit bias δ=2.0 to green tokens during generation. Detection uses a z-score test: z = (green\_count − γT) / √(γ(1−γ)T). Flagged if z > 4.0.
- **Aaronson/EXP** (2022): Position-dependent Gumbel-max sampling — a keyed PRNG generates a random vector per position and text is sampled to maximize alignment with it. Detection computes a mean-score S = mean(−log(1 − r\_{t,w\_t})). Flagged if S > 0.8.

Output: 6 JSONL files in `data/corpus/` (e.g., `mistral_kgw.jsonl`, `llama_aaronson.jsonl`)

### Phase 3 — Evasion Attack Simulation
Tests how well watermarks survive post-hoc text manipulation via 4 strategies:

| Strategy | Model | Attack Type |
|----------|-------|-------------|
| **T5 Paraphrase** | `t5-large` | Lexical rewording — changes surface form, preserves structure |
| **PEGASUS Paraphrase** | `google/pegasus-xsum` | Aggressive neural paraphrase — structural rewriting |
| **RTT Arabic** | `facebook/nllb-200-distilled-600M` | English → Arabic → English round-trip translation |
| **RTT Russian** | `facebook/nllb-200-distilled-600M` | English → Russian → English round-trip translation |

Output: 24 JSONL files in `data/evasion/` (6 corpus files × 4 strategies)

### Phase 4 — Detection & Attribution Evaluation
Scores every text (original + all evaded variants) with both watermark detectors and computes:
- **Detection rate** — % of texts correctly flagged as watermarked
- **Attribution accuracy** — % of flagged texts where the correct source model is identified (by testing all 3 keys and picking the highest score)
- Aggregated metrics by (model, scheme, evasion strategy) with visualizations

Output: CSVs and plots in `data/results/`

---

## Requirements

- Python 3.8+
- CUDA GPU with **≥16 GB VRAM** (24 GB recommended for full-precision runs)
- HuggingFace account with access to gated repos (Mistral-7B, LLaMA-3-8B)

Install dependencies:

```bash
pip install -r requirements.txt
```

Key packages: `torch>=2.1.0`, `transformers>=4.40.0`, `accelerate`, `bitsandbytes` (4-bit quantization), `datasets`, `sacrebleu`, `bert-score`, `matplotlib`, `seaborn`

---

## How to Run

### Option A — Sequential Phase Scripts

```bash
# Phase 1: Collect seed prompts
python phase1_collect_data.py
# Optional flags: --config config.yaml --num_wtwt 2000 --num_gdelt 500

# Phase 2: Generate watermarked corpus
python phase2_generate_corpus.py
# Optional flags: --model all|mistral|llama|falcon --scheme kgw|aaronson|both --max_texts 100

# Phase 3: Apply evasion attacks
python phase3_evasion.py
# Optional flags: --strategy all|t5|pegasus|rtt_arabic|rtt_russian --corpus_dir data/corpus

# Phase 4: Detect, attribute, and evaluate
python phase4_evaluate.py
# Optional flags: --corpus_dir data/corpus --evasion_dir data/evasion
```

### Option B — Google Colab Notebook

Open `PropagandaTrace_Colab.ipynb` in Google Colab (A100/V100 recommended). The notebook walks through all 4 phases end-to-end with inline explanations and visualizations.

### Configuration

All paths, model IDs, and hyperparameters are controlled through `config.yaml`. Important settings:

```yaml
generation:
  texts_per_model: 3000    # reduce for quick testing (e.g., 100)
  batch_size: 4            # lower if OOM on GPU

watermark:
  kgw:
    gamma: 0.25            # green-list fraction
    delta: 2.0             # logit bias
    z_threshold: 4.0       # detection threshold

models:
  mistral:
    load_4bit: true        # 4-bit quantization (required for ≤16 GB VRAM)
```

---

## Expected Outputs

### Phase 1
- `data/raw/seed_prompts.jsonl` — one prompt per line: `{"text": "...", "source": "wtwt|gdelt|semeval|template", "idx": 0}`
- `data/raw/collection_stats.json` — source breakdown and timestamp

### Phase 2
- `data/corpus/mistral_kgw.jsonl`, `mistral_aaronson.jsonl`, `llama_kgw.jsonl`, `llama_aaronson.jsonl`, `falcon_kgw.jsonl`, `falcon_aaronson.jsonl`
- Each record: `{"idx": 0, "model": "mistral", "scheme": "kgw", "key": "MISTRAL_KEY_47A", "prompt": "...", "generated": "...", "token_ids": [...], "num_tokens": 213}`

### Phase 3
- 24 JSONL files: `data/evasion/<model>_<scheme>_evade_<strategy>.jsonl`
- Each record extends the Phase 2 record with: `{"evaded_text": "...", "evasion_strategy": "t5", "evasion_model": "t5-large"}`

### Phase 4
| Output | Description |
|--------|-------------|
| `data/results/all_scores.csv` | Per-record KGW z-score, Aaronson mean-score, predicted model, attribution flag |
| `data/results/metrics_summary.csv` | Aggregated detection rate (%), attribution accuracy (%), avg scores |
| `data/results/table_kgw_detection_kgw.csv` | Paper-style table: models × evasion strategies → KGW detection rate |
| `data/results/table_aar_detection_kgw.csv` | Same for Aaronson detector |
| `data/results/plots/fig1_zscore_distributions.png` | KGW z-score histograms per model (baseline) |
| `data/results/plots/fig2_kgw_detection_kgw.png` | Detection rate bar chart by strategy |
| `data/results/plots/fig3_kgw_attribution_heatmap_kgw.png` | Attribution accuracy heatmap |
| `data/results/plots/fig4_zscore_degradation_kgw.png` | Z-score degradation across evasion strategies |

---

## Results Summary

| Condition | KGW Detection | Aaronson Detection | Attribution Accuracy |
|-----------|--------------|-------------------|---------------------|
| Baseline (no attack) | ~100% | ~100% | 95–98% |
| T5 Paraphrase | ~88–91% | ~75–80% | ~85–90% |
| RTT Arabic | ~68–76% | ~55–63% | ~50–67% |
| RTT Russian | ~70–74% | ~52–60% | ~52–65% |
| PEGASUS Paraphrase | ~42–48% | ~30–35% | ~36–41% |

**Key Findings:**
- KGW is substantially more robust than the Aaronson/EXP scheme under all evasion attacks.
- PEGASUS is the most destructive evasion strategy — its structural rewriting breaks the green-token distribution that KGW relies on.
- T5 lexical paraphrase has minimal impact on KGW watermarks, confirming that surface-level rewording is insufficient for evasion.
- Round-trip translation (Arabic/Russian) provides moderate evasion, with Arabic being slightly more effective.
- Attribution accuracy degrades faster than raw detection under PEGASUS, suggesting that watermark signals survive weakly but become harder to assign to the correct source model.

---

## Datasets & Models Used

**Datasets:**
- [WTWT](https://huggingface.co/datasets/conforti/wtwt) — Conforti et al., 2020
- [GDELT](https://www.gdeltproject.org/) — Global Database of Events, Language and Tone
- [SemEval-2020 Task 11](https://github.com/SemEval/SemEval2020) — Propaganda technique detection

**Pre-trained Models:**
- [Mistral-7B-Instruct-v0.2](https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.2)
- [Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) *(gated — requires HF access)*
- [Falcon-7B-Instruct](https://huggingface.co/tiiuae/falcon-7b-instruct)
- [T5-Large](https://huggingface.co/t5-large)
- [PEGASUS-XSUM](https://huggingface.co/google/pegasus-xsum)
- [NLLB-200-Distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M)

---

## References

1. Kirchenbauer, J., et al. *A Watermark for Large Language Models.* ICML 2023.
2. Aaronson, S. *Watermarking GPT outputs.* 2022. [Blog post](https://scottaaronson.blog/?p=6823)
3. Sadasivan, V. S., et al. *Can AI-Generated Text be Reliably Detected?* arXiv 2023.
4. Conforti, C., et al. *WTWT: A Dataset for Target-Dependent Stance Detection.* ACL 2020.
5. Da San Martino, G., et al. *SemEval-2020 Task 11: Detection of Propaganda Techniques in News Articles.* 2020.

---

## Team

**Team 47 — USC CS 544 Spring 2026**
