"""
visualize.py
------------
Before/after plots: geographic scatter (territory maps) and workload
distribution histograms, so the imbalance -> balance story is visible.
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def plot_territory_map(df, rep_col="rep_id", title="Territory Map", path=None):
    fig, ax = plt.subplots(figsize=(8, 7))
    reps = df[rep_col].unique()
    cmap = plt.get_cmap("tab20")
    for i, rep in enumerate(sorted(reps)):
        sub = df[df[rep_col] == rep]
        ax.scatter(sub["longitude"], sub["latitude"], s=10,
                   color=cmap(i % 20), alpha=0.7)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_workload_distribution(before_summary, after_summary, path=None):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)

    axes[0].hist(before_summary["n_hospitals"], bins=30, color="#d9534f", alpha=0.8)
    axes[0].set_title("BEFORE: Hospitals per Rep\n(unbalanced)")
    axes[0].set_xlabel("Hospitals assigned")
    axes[0].set_ylabel("Number of reps")
    axes[0].axvline(before_summary["n_hospitals"].mean(), color="black", linestyle="--",
                     label=f"mean={before_summary['n_hospitals'].mean():.0f}")
    axes[0].legend()

    axes[1].hist(after_summary["n_hospitals"], bins=30, color="#5cb85c", alpha=0.8)
    axes[1].set_title("AFTER: Hospitals per Rep\n(balanced)")
    axes[1].set_xlabel("Hospitals assigned")
    axes[1].axvline(after_summary["n_hospitals"].mean(), color="black", linestyle="--",
                     label=f"mean={after_summary['n_hospitals'].mean():.0f}")
    axes[1].legend()

    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_workload_boxplot(before_summary, after_summary, path=None):
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.boxplot(
        [before_summary["total_workload"], after_summary["total_workload"]],
        labels=["Before", "After"]
    )
    ax.set_title("Rep Workload Spread (Before vs After)")
    ax.set_ylabel("Total monthly workload per rep")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    plt.close(fig)
