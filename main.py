"""
main.py
-------
End-to-end run of the Sales Territory Optimization project.

Pipeline:
  1. Generate synthetic hospital data (1200 hospitals, 18 city clusters)
  2. Generate a "BEFORE" assignment (naive/historical, unbalanced)
  3. Run the optimizer (K-Means + capacitated min-cost-flow) -> "AFTER"
  4. Print before/after summary stats in the exact style of the brief
  5. Save CSVs + plots to outputs/
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import pandas as pd
import numpy as np

from data_generator import generate_hospital_data, generate_naive_before_assignment
from territory_optimizer import TerritoryOptimizer, haversine_km
from visualize import plot_territory_map, plot_workload_distribution, plot_workload_boxplot

N_HOSPITALS = 1200
N_REPS = 200
OUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUT_DIR, "plots"), exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def compute_before_distance(before_df):
    """For the BEFORE scenario, distance = distance to the centroid of the
    hospitals actually assigned to that rep (their de facto center),
    since there was no planned center."""
    centroids = before_df.groupby("rep_id")[["latitude", "longitude"]].mean()
    merged = before_df.merge(centroids, on="rep_id", suffixes=("", "_centroid"))
    merged["distance_km"] = haversine_km(
        merged["latitude"], merged["longitude"],
        merged["latitude_centroid"], merged["longitude_centroid"]
    )
    return merged


def main():
    print("=" * 70)
    print("SALES TERRITORY OPTIMIZATION")
    print("=" * 70)

    # 1. Data
    hospitals = generate_hospital_data(n_hospitals=N_HOSPITALS, seed=42)
    hospitals.to_csv(os.path.join(DATA_DIR, "hospitals.csv"), index=False)
    print(f"\nGenerated {len(hospitals)} hospitals, {N_REPS} reps, "
          f"total monthly workload = {hospitals['monthly_workload'].sum():,}")

    # 2. BEFORE: naive historical assignment
    before = generate_naive_before_assignment(hospitals, n_reps=N_REPS, seed=42)
    before = compute_before_distance(before)
    before_summary = TerritoryOptimizer.summarize(before)

    # 3. AFTER: K-Means + capacitated balancing
    optimizer = TerritoryOptimizer(
        hospitals, n_reps=N_REPS,
        workload_col="monthly_workload",
        capacity_tolerance=0.08,
        k_nearest_candidates=12,
        random_state=42,
    )
    optimizer.fit_kmeans_centers()
    after = optimizer.solve_balanced_assignment()
    after_summary = TerritoryOptimizer.summarize(after)

    # 4. Report — mirrors the "Rep A: 120 -> Rep A 75 / Rep B 72" style output
    def stats_block(name, summary_df, dist_df):
        print(f"\n--- {name} ---")
        print(f"  Hospitals/rep      : min={summary_df.n_hospitals.min():>3}  "
              f"max={summary_df.n_hospitals.max():>3}  "
              f"mean={summary_df.n_hospitals.mean():6.1f}  "
              f"std={summary_df.n_hospitals.std():6.1f}")
        print(f"  Workload/rep       : min={summary_df.total_workload.min():>6.0f}  "
              f"max={summary_df.total_workload.max():>6.0f}  "
              f"mean={summary_df.total_workload.mean():8.1f}  "
              f"std={summary_df.total_workload.std():8.1f}")
        print(f"  Avg travel dist/rep: {dist_df['distance_km'].mean():.1f} km "
              f"(mean of per-hospital distance to rep center)")
        cv = summary_df.total_workload.std() / summary_df.total_workload.mean()
        print(f"  Coefficient of variation (workload balance): {cv:.3f}  "
              f"(lower = more balanced)")

    stats_block("BEFORE (naive/historical assignment)", before_summary, before)
    stats_block("AFTER  (K-Means + capacity-balanced flow)", after_summary, after)

    overloaded_before = (before_summary.n_hospitals >
                          before_summary.n_hospitals.mean() * 1.3).sum()
    overloaded_after = (after_summary.n_hospitals >
                         after_summary.n_hospitals.mean() * 1.3).sum()
    print(f"\nReps with >30% above average hospital count: "
          f"BEFORE={overloaded_before}  AFTER={overloaded_after}")

    # Example callout matching the brief's "Rep A" example: find the most
    # overloaded rep BEFORE, show what happened to its hospitals AFTER
    worst_rep = before_summary.sort_values("n_hospitals", ascending=False).iloc[0]
    print(f"\nExample -- most overloaded rep before optimization: "
          f"{worst_rep.rep_id} had {int(worst_rep.n_hospitals)} hospitals.")
    worst_rep_hospitals = before.loc[before.rep_id == worst_rep.rep_id, "hospital_id"]
    after_reps_for_those = after.loc[after.hospital_id.isin(worst_rep_hospitals), "rep_id"]
    split_counts = after_reps_for_those.value_counts().head(5)
    print("Those hospitals are now spread across these reps post-optimization:")
    for rep_id, cnt in split_counts.items():
        total_for_rep = (after.rep_id == rep_id).sum()
        print(f"  {rep_id}: gets {cnt} of those hospitals "
              f"(now serves {total_for_rep} hospitals total)")

    # 5. Save outputs
    before.to_csv(os.path.join(OUT_DIR, "before_assignment.csv"), index=False)
    after.to_csv(os.path.join(OUT_DIR, "after_assignment.csv"), index=False)
    before_summary.to_csv(os.path.join(OUT_DIR, "before_summary_by_rep.csv"), index=False)
    after_summary.to_csv(os.path.join(OUT_DIR, "after_summary_by_rep.csv"), index=False)

    plot_territory_map(before, title="BEFORE: Territory Map (unbalanced)",
                        path=os.path.join(OUT_DIR, "plots", "before_map.png"))
    plot_territory_map(after, title="AFTER: Territory Map (K-Means + balanced)",
                        path=os.path.join(OUT_DIR, "plots", "after_map.png"))
    plot_workload_distribution(before_summary, after_summary,
                                path=os.path.join(OUT_DIR, "plots", "hospitals_per_rep_hist.png"))
    plot_workload_boxplot(before_summary, after_summary,
                           path=os.path.join(OUT_DIR, "plots", "workload_boxplot.png"))

    print(f"\nSaved CSVs and plots to: {OUT_DIR}")
    print("=" * 70)


if __name__ == "__main__":
    main()
