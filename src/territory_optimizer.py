"""
territory_optimizer.py
-----------------------
The core optimization engine. Three stages, matching the brief:

  1. K-MEANS CLUSTERING        -> get geographically compact candidate
                                   territory centers (Lloyd's algorithm).
  2. DISTANCE OPTIMIZATION     -> assign each hospital to the nearest rep
                                   that still has spare capacity, i.e.
                                   minimize rep-to-hospital travel distance
                                   subject to a load cap.
  3. SALES BALANCING           -> the capacity constraint in step 2 is set
                                   from each hospital's *workload*, not raw
                                   headcount, so the optimizer balances
                                   effort, not just hospital counts. Centers
                                   are then recomputed from the new
                                   assignment and the process repeats
                                   (exactly like Lloyd's algorithm for
                                   K-Means, but with a capacity check added
                                   to the assignment step) -- this is the
                                   standard "Capacitated K-Means" pattern.

Why not vanilla K-Means?
Vanilla K-Means minimizes within-cluster distance only -- it has no notion
of "cluster size" or "cluster load", so it happily produces one cluster with
120 hospitals and another with 40. Exact capacitated assignment (the
generalized assignment problem) is NP-hard, so we use the standard practical
heuristic: greedy nearest-available-capacity assignment, iterated with
centroid updates, which converges to a good local optimum quickly and is
what's used in production capacitated-clustering libraries.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from scipy.spatial import cKDTree


EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    """Vectorized great-circle distance in km."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


class TerritoryOptimizer:
    def __init__(self, hospitals_df: pd.DataFrame, n_reps: int = 200,
                 workload_col: str = "monthly_workload",
                 capacity_tolerance: float = 0.10,
                 k_nearest_candidates: int = 12,
                 random_state: int = 42):
        """
        hospitals_df        : dataframe with hospital_id, latitude, longitude, workload_col
        n_reps               : number of reps / territories to create
        workload_col         : column representing effort/load (not just count)
        capacity_tolerance   : how far a rep's load may deviate from the
                                perfectly-even average (e.g. 0.10 = +/-10%)
        k_nearest_candidates : for the flow graph, only connect each hospital
                                to its k nearest candidate centers (keeps the
                                flow problem sparse and fast at scale)
        """
        self.df = hospitals_df.reset_index(drop=True).copy()
        self.n_reps = n_reps
        self.workload_col = workload_col
        self.capacity_tolerance = capacity_tolerance
        self.k_nearest_candidates = k_nearest_candidates
        self.random_state = random_state
        self.centers_ = None
        self.result_df_ = None

    # ---------- Stage 1: K-Means for candidate territory centers ----------
    def fit_kmeans_centers(self):
        coords = self.df[["latitude", "longitude"]].values
        km = KMeans(n_clusters=self.n_reps, n_init=10, random_state=self.random_state)
        km.fit(coords)
        self.centers_ = km.cluster_centers_
        self.kmeans_labels_ = km.labels_
        return self.centers_

    # ---------- Stage 2 + 3: capacitated assignment (Lloyd's iteration) ----------
    def _capacitated_assign(self, centers, coords, workloads, capacity):
        """
        One assignment pass: each hospital goes to the NEAREST center that
        still has spare capacity (distance optimization), where capacity is
        measured in workload units, not hospital counts (sales balancing).

        Hospitals are processed largest-workload-first so that big accounts
        get first pick of their nearest rep -- this avoids the common
        failure mode where large hospitals get "stranded" far from any rep
        with room left, which happens if you process in random order.
        """
        n_hosp = len(coords)
        tree = cKDTree(centers)
        k = min(self.k_nearest_candidates, len(centers))
        _, nearest_idx = tree.query(coords, k=k)

        remaining_capacity = np.full(len(centers), capacity, dtype=float)
        assigned = np.full(n_hosp, -1, dtype=int)

        order = np.argsort(-workloads)  # largest workload first
        for i in order:
            w = workloads[i]
            candidates = nearest_idx[i]
            # try nearest-first among the k candidates that still have room
            chosen = -1
            for c in candidates:
                if remaining_capacity[c] >= w:
                    chosen = c
                    break
            if chosen == -1:
                # All k nearest candidates are full: widen the search to
                # EVERY center (not just the k nearest) and take whichever
                # has room, sorted by distance, so capacity is genuinely
                # respected rather than silently overflowed.
                dist_to_all = np.linalg.norm(centers - coords[i], axis=1)
                sorted_all = np.argsort(dist_to_all)
                for c in sorted_all:
                    if remaining_capacity[c] >= w:
                        chosen = c
                        break
                if chosen == -1:
                    # Truly every rep is full (shouldn't happen since total
                    # capacity > total workload) -- pick least-overloaded
                    chosen = int(np.argmax(remaining_capacity))
            assigned[i] = chosen
            remaining_capacity[chosen] -= w
        return assigned

    def solve_balanced_assignment(self, n_iterations: int = 6):
        if self.centers_ is None:
            self.fit_kmeans_centers()

        df = self.df
        coords = df[["latitude", "longitude"]].values
        workloads = df[self.workload_col].values.astype(float)
        total_workload = workloads.sum()
        avg_capacity = total_workload / self.n_reps
        capacity = avg_capacity * (1 + self.capacity_tolerance)

        centers = self.centers_.copy()
        assigned = None

        for iteration in range(n_iterations):
            assigned = self._capacitated_assign(centers, coords, workloads, capacity)
            # Recompute centers as the workload-weighted centroid of hospitals
            # now assigned to them (Lloyd's-algorithm update step) so the
            # NEXT assignment pass optimizes distance given the new territories
            new_centers = centers.copy()
            for c in range(self.n_reps):
                mask = assigned == c
                if mask.sum() > 0:
                    w = workloads[mask]
                    new_centers[c] = np.average(coords[mask], axis=0, weights=w)
            shift = np.linalg.norm(new_centers - centers, axis=1).mean()
            centers = new_centers
            if shift < 1e-4:
                break

        self.centers_ = centers

        result = df.copy()
        result["rep_id"] = [f"Rep_{c:03d}" for c in assigned]
        result["center_lat"] = centers[assigned, 0]
        result["center_lon"] = centers[assigned, 1]
        result["distance_km"] = haversine_km(
            result["latitude"].values, result["longitude"].values,
            result["center_lat"].values, result["center_lon"].values
        )
        self.result_df_ = result
        self.capacity_ = capacity
        return result

    # ---------- Metrics ----------
    @staticmethod
    def summarize(assigned_df: pd.DataFrame, workload_col: str = "monthly_workload"):
        by_rep = assigned_df.groupby("rep_id").agg(
            n_hospitals=("hospital_id", "count"),
            total_workload=(workload_col, "sum"),
            avg_distance_km=("distance_km", "mean") if "distance_km" in assigned_df.columns else ("hospital_id", "count"),
        ).reset_index()
        return by_rep
