#!/usr/bin/env python3
"""
Phase 4 — Detection & Attribution Scoring
Run: python phase4_evaluate.py [--config config.yaml]

Scores Phase 2 corpus and Phase 3 evasion files with KGW and Aaronson detectors.
Computes detection rates, attribution accuracy, and generates result plots.

Output:
  data/results/all_scores.csv          — per-record detection scores
  data/results/metrics_summary.csv     — aggregated metrics table
  data/results/table_kgw_detection.csv — paper-style detection rate table (KGW)
  data/results/table_aar_detection.csv — paper-style detection rate table (Aaronson)
  data/results/plots/                  — PNG figures
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))

from src.evaluation.detect import (
    score_corpus_file,
    score_evasion_file,
    compute_metrics,
    pivot_detection_table,
)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="PropagandaTrace — Phase 4: Evaluation")
    p.add_argument("--config",      default="config.yaml")
    p.add_argument("--corpus_dir",  default=None)
    p.add_argument("--evasion_dir", default=None)
    p.add_argument("--output_dir",  default=None)
    p.add_argument("--max_records", type=int, default=None,
                   help="Limit records per file (for quick testing)")
    p.add_argument("--skip_plots",  action="store_true",
                   help="Skip matplotlib plot generation")
    return p.parse_args()


# ── Plotting ──────────────────────────────────────────────────────────────────

def make_plots(metrics: pd.DataFrame, all_scores: pd.DataFrame, plot_dir: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns
    except ImportError:
        log.warning("matplotlib/seaborn not installed — skipping plots.")
        return

    plot_dir.mkdir(parents=True, exist_ok=True)
    sns.set_theme(style="whitegrid", palette="muted")

    STRATEGY_ORDER = ["none", "t5", "pegasus", "rtt_ara", "rtt_rus"]
    STRATEGY_LABELS = {
        "none":    "No Attack",
        "t5":      "T5 Para.",
        "pegasus": "PEGASUS",
        "rtt_ara": "RTT Arabic",
        "rtt_rus": "RTT Russian",
    }
    MODELS = ["mistral", "llama", "falcon"]

    # ── 1. Z-score distribution per model (KGW, corpus only) ─────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharey=False)
    corpus_df = all_scores[all_scores["evasion_strategy"] == "none"]
    for ax, model in zip(axes, MODELS):
        sub = corpus_df[corpus_df["true_model"] == model]["kgw_z_score"]
        if sub.empty:
            ax.set_title(f"{model} (no data)")
            continue
        ax.hist(sub.dropna(), bins=30, color="steelblue", edgecolor="white", alpha=0.85)
        ax.axvline(4.0, color="crimson", linestyle="--", linewidth=1.5, label="threshold z=4")
        ax.set_title(f"{model.capitalize()}", fontsize=12)
        ax.set_xlabel("KGW z-score")
        ax.set_ylabel("Count")
        ax.legend(fontsize=8)
    fig.suptitle("KGW Z-Score Distribution (Unattacked Watermarked Text)", fontsize=13)
    plt.tight_layout()
    fig.savefig(plot_dir / "fig1_zscore_distributions.png", dpi=150)
    plt.close(fig)
    log.info("Saved fig1_zscore_distributions.png")

    # ── 2. Detection rate by evasion strategy — KGW ──────────────────────────
    for scheme in metrics["scheme"].unique():
        for detector, label in [("kgw", "KGW"), ("aar", "Aaronson")]:
            col = f"{detector}_detection_rate"
            sub = metrics[metrics["scheme"] == scheme].copy()
            sub = sub[sub["evasion_strategy"].isin(STRATEGY_ORDER)]
            sub["strategy_label"] = sub["evasion_strategy"].map(
                lambda x: STRATEGY_LABELS.get(x, x))

            pivot = sub.pivot(index="true_model",
                              columns="evasion_strategy",
                              values=col)
            pivot = pivot.reindex(columns=[s for s in STRATEGY_ORDER if s in pivot.columns])
            pivot.columns = [STRATEGY_LABELS.get(c, c) for c in pivot.columns]

            fig, ax = plt.subplots(figsize=(10, 5))
            pivot.plot(kind="bar", ax=ax, edgecolor="white", width=0.7)
            ax.set_ylim(0, 110)
            ax.set_ylabel("Detection Rate (%)")
            ax.set_xlabel("Model")
            ax.set_title(f"{label} Detection Rate by Evasion Strategy ({scheme.upper()} scheme)")
            ax.set_xticklabels([m.capitalize() for m in pivot.index], rotation=0)
            ax.axhline(100, color="grey", linestyle=":", linewidth=0.8)
            ax.legend(title="Strategy", bbox_to_anchor=(1.01, 1), loc="upper left")
            plt.tight_layout()
            fname = f"fig2_{detector}_detection_{scheme}.png"
            fig.savefig(plot_dir / fname, dpi=150)
            plt.close(fig)
            log.info(f"Saved {fname}")

    # ── 3. Attribution accuracy heatmap ──────────────────────────────────────
    for scheme in metrics["scheme"].unique():
        for detector, label in [("kgw", "KGW"), ("aar", "Aaronson")]:
            col = f"{detector}_attribution_acc"
            sub = metrics[(metrics["scheme"] == scheme) &
                          (metrics["evasion_strategy"].isin(STRATEGY_ORDER))].copy()
            if sub.empty:
                continue
            pivot = sub.pivot(index="true_model",
                              columns="evasion_strategy",
                              values=col)
            pivot = pivot.reindex(columns=[s for s in STRATEGY_ORDER if s in pivot.columns])
            pivot.columns = [STRATEGY_LABELS.get(c, c) for c in pivot.columns]

            fig, ax = plt.subplots(figsize=(8, 3.5))
            sns.heatmap(pivot, annot=True, fmt=".1f", cmap="YlGn",
                        vmin=0, vmax=100, ax=ax,
                        linewidths=0.5, cbar_kws={"label": "Attribution Acc. (%)"})
            ax.set_title(f"{label} Attribution Accuracy — {scheme.upper()} scheme")
            ax.set_xlabel("Evasion Strategy")
            ax.set_ylabel("True Model")
            ax.set_yticklabels([m.capitalize() for m in pivot.index], rotation=0)
            plt.tight_layout()
            fname = f"fig3_{detector}_attribution_heatmap_{scheme}.png"
            fig.savefig(plot_dir / fname, dpi=150)
            plt.close(fig)
            log.info(f"Saved {fname}")

    # ── 4. Avg KGW z-score drop across strategies ─────────────────────────────
    for scheme in metrics["scheme"].unique():
        sub = metrics[metrics["scheme"] == scheme].copy()
        sub = sub[sub["evasion_strategy"].isin(STRATEGY_ORDER)]

        fig, ax = plt.subplots(figsize=(9, 4))
        for model in MODELS:
            m_sub = sub[sub["true_model"] == model].set_index("evasion_strategy")
            m_sub = m_sub.reindex(STRATEGY_ORDER).dropna(subset=["kgw_avg_z"])
            if m_sub.empty:
                continue
            ax.plot(
                [STRATEGY_LABELS.get(s, s) for s in m_sub.index],
                m_sub["kgw_avg_z"],
                marker="o", label=model.capitalize()
            )
        ax.axhline(4.0, color="crimson", linestyle="--", linewidth=1.2, label="Detection threshold")
        ax.set_ylabel("Average KGW z-score")
        ax.set_xlabel("Evasion Strategy")
        ax.set_title(f"KGW Z-score Degradation Across Evasion Attacks ({scheme.upper()} scheme)")
        ax.legend()
        plt.tight_layout()
        fname = f"fig4_zscore_degradation_{scheme}.png"
        fig.savefig(plot_dir / fname, dpi=150)
        plt.close(fig)
        log.info(f"Saved {fname}")

    log.info(f"All plots saved to {plot_dir}/")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    args = parse_args()

    with open(args.config) as f:
        cfg = yaml.safe_load(f)

    corpus_dir  = Path(args.corpus_dir  or cfg["paths"]["corpus"])
    evasion_dir = Path(args.evasion_dir or cfg["paths"]["evasion"])
    output_dir  = Path(args.output_dir  or cfg["paths"]["results"])
    plot_dir    = output_dir / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    wm_cfg = cfg["watermark"]

    log.info("=" * 60)
    log.info("PropagandaTrace — Phase 4: Detection & Attribution")
    log.info("=" * 60)

    all_dfs = []

    # ── Score corpus files (baseline — no evasion) ────────────────────────────
    corpus_files = sorted(corpus_dir.glob("*.jsonl"))
    log.info(f"\nCorpus files found: {len(corpus_files)}")

    for path in corpus_files:
        log.info(f"  Scoring corpus: {path.name}")
        df = score_corpus_file(str(path), wm_cfg, args.max_records)
        all_dfs.append(df)
        log.info(f"    → {len(df)} records scored")

    # ── Score evasion files ───────────────────────────────────────────────────
    evasion_files = sorted(evasion_dir.glob("*.jsonl"))
    log.info(f"\nEvasion files found: {len(evasion_files)}")

    for path in evasion_files:
        log.info(f"  Scoring evasion: {path.name}")
        df = score_evasion_file(str(path), wm_cfg, args.max_records)
        all_dfs.append(df)
        log.info(f"    → {len(df)} records scored")

    if not all_dfs:
        log.error("No files found. Run Phases 2 and 3 first.")
        sys.exit(1)

    all_scores = pd.concat(all_dfs, ignore_index=True)
    all_scores.to_csv(output_dir / "all_scores.csv", index=False)
    log.info(f"\nAll scores saved → {output_dir}/all_scores.csv  ({len(all_scores)} rows)")

    # ── Compute aggregated metrics ────────────────────────────────────────────
    metrics = compute_metrics(all_scores)
    metrics.to_csv(output_dir / "metrics_summary.csv", index=False)
    log.info(f"Metrics summary → {output_dir}/metrics_summary.csv")

    # ── Paper-style detection rate tables ─────────────────────────────────────
    for scheme in metrics["scheme"].unique():
        for detector, label in [("kgw", "KGW"), ("aar", "Aaronson")]:
            table = pivot_detection_table(metrics, scheme, detector)
            fname = output_dir / f"table_{detector}_detection_{scheme}.csv"
            table.to_csv(fname)
            log.info(f"\n{label} Detection Rate (%) — {scheme.upper()} scheme:\n{table.to_string()}")

    # ── Console summary ───────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info("RESULTS SUMMARY")
    log.info("=" * 60)

    for scheme in sorted(metrics["scheme"].unique()):
        log.info(f"\n── Scheme: {scheme.upper()} ──")
        sub = metrics[metrics["scheme"] == scheme].sort_values(
            ["true_model", "evasion_strategy"])
        for _, row in sub.iterrows():
            log.info(
                f"  {row['true_model']:8s} | {row['evasion_strategy']:12s} | "
                f"KGW detect: {row['kgw_detection_rate']:5.1f}%  "
                f"attr: {row['kgw_attribution_acc']:5.1f}%  "
                f"z̄={row['kgw_avg_z']:.2f}  |  "
                f"AAR detect: {row['aar_detection_rate']:5.1f}%  "
                f"attr: {row['aar_attribution_acc']:5.1f}%"
            )

    # ── Plots ─────────────────────────────────────────────────────────────────
    if not args.skip_plots:
        make_plots(metrics, all_scores, plot_dir)

    log.info("\n" + "=" * 60)
    log.info(f"Phase 4 complete. Results in: {output_dir}/")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
