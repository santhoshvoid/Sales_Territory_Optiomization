"""
data_generator.py
------------------
Generates a realistic synthetic dataset simulating a pharma/medtech sales
scenario (very typical of a ZS Associates-style engagement):

    - N_HOSPITALS accounts (hospitals/clinics), each with:
        * a geographic location (lat/lon)
        * a "workload" score (e.g. monthly call volume, sales potential,
          number of physicians, or product volume -- the thing a rep's
          time is actually spent on, NOT just headcount of hospitals)
    - N_REPS field reps who need to be assigned territories.

Real hospital-visit data is proprietary, so we simulate it with realistic
clustering (reps visit hospitals that cluster around cities, not uniformly
in space) and a right-skewed workload distribution (a few large teaching
hospitals, many small clinics) -- this mirrors real pharma call-panel data.
"""

import numpy as np
import pandas as pd

RNG_SEED = 42


def generate_hospital_data(n_hospitals: int = 1200,
                            n_cities: int = 18,
                            seed: int = RNG_SEED) -> pd.DataFrame:
    """
    Create synthetic hospital/account data with realistic spatial clustering
    (hospitals cluster around city centers) and a right-skewed workload
    (log-normal) distribution.
    """
    rng = np.random.default_rng(seed)

    # Simulate city centers spread across a ~1000km x 1000km region
    city_centers = rng.uniform(low=[19.0, 72.0], high=[29.0, 88.0], size=(n_cities, 2))
    city_weights = rng.dirichlet(np.ones(n_cities) * 1.5)  # some cities bigger than others

    city_idx = rng.choice(n_cities, size=n_hospitals, p=city_weights)
    jitter = rng.normal(scale=0.35, size=(n_hospitals, 2))  # spread within a city
    coords = city_centers[city_idx] + jitter

    # Workload proxy: monthly "call volume" needed, right-skewed (log-normal)
    workload = rng.lognormal(mean=3.2, sigma=0.6, size=n_hospitals)
    workload = np.clip(workload, 5, 400).round().astype(int)

    hospital_types = rng.choice(
        ["Teaching Hospital", "General Hospital", "Clinic", "Diagnostic Center"],
        size=n_hospitals, p=[0.08, 0.27, 0.45, 0.20]
    )

    df = pd.DataFrame({
        "hospital_id": [f"H{i:04d}" for i in range(n_hospitals)],
        "latitude": coords[:, 0],
        "longitude": coords[:, 1],
        "city_cluster": city_idx,
        "hospital_type": hospital_types,
        "monthly_workload": workload,   # this is the real unit of "load", not headcount
    })
    return df


def generate_naive_before_assignment(df: pd.DataFrame, n_reps: int = 200,
                                      seed: int = RNG_SEED) -> pd.DataFrame:
    """
    Simulates how territories often get assigned in practice BEFORE any
    optimization: ad-hoc / historical assignment, e.g. reps inherited
    territories when they joined, new hospitals got bolted onto the
    nearest existing rep without ever rebalancing. We simulate this by:

      1. Picking 200 "seed" reps at random hospital locations.
      2. Assigning every hospital to its nearest seed (pure nearest-neighbor,
         no capacity awareness at all).
      3. Then randomly reassigning a chunk of hospitals to introduce the kind
         of drift/inheritance noise seen in real historical territories.

    This deliberately produces imbalance -- exactly the "Rep A: 120 hospitals"
    problem statement in the brief.
    """
    rng = np.random.default_rng(seed)
    coords = df[["latitude", "longitude"]].values

    seed_idx = rng.choice(len(df), size=n_reps, replace=False)
    seeds = coords[seed_idx]

    # Nearest-seed assignment (no capacity constraint at all)
    dists = np.linalg.norm(coords[:, None, :] - seeds[None, :, :], axis=2)
    rep_assignment = dists.argmin(axis=1)

    # Add "historical drift": 15% of hospitals randomly reassigned to a
    # random rep (simulates ad-hoc manual overrides accumulated over years)
    drift_mask = rng.random(len(df)) < 0.15
    rep_assignment[drift_mask] = rng.integers(0, n_reps, size=drift_mask.sum())

    out = df.copy()
    out["rep_id"] = [f"Rep_{r:03d}" for r in rep_assignment]
    return out


if __name__ == "__main__":
    hospitals = generate_hospital_data()
    hospitals.to_csv("data/hospitals.csv", index=False)
    print(f"Generated {len(hospitals)} hospitals across {hospitals['city_cluster'].nunique()} city clusters")
    print(hospitals.head())
