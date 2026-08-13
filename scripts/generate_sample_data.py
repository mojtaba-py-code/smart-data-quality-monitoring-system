"""Generate reproducible sample datasets for demos and manual testing.

Run with::

    python scripts/generate_sample_data.py

It writes a deliberately imperfect "customers" dataset (with duplicates, bad
emails, whitespace, missing values, and outliers) plus a "baseline" and
"current" pair for drift demonstrations, in several formats under data/samples.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"
SEED = 20260101


def build_customers(rng: np.random.Generator, rows: int = 500) -> pd.DataFrame:
    """Build a messy customer dataset that exercises every validation rule."""
    ids = np.arange(1, rows + 1)
    emails = [f"customer{i}@example.com" for i in range(rows)]
    phones = ["+1 (555) 010-" + f"{rng.integers(1000, 9999)}" for _ in range(rows)]
    amounts = rng.normal(250, 60, rows).round(2)
    signup = pd.date_range("2023-01-01", periods=rows, freq="6h").astype(str)
    country = rng.choice(["US", "GB", "DE", "FR", "JP"], size=rows, p=[0.4, 0.2, 0.15, 0.15, 0.1])
    notes = rng.choice(["  premium ", "standard", "", "  ", "vip"], size=rows)

    frame = pd.DataFrame(
        {
            "Customer ID": ids,
            "Email": emails,
            "Phone": phones,
            "Purchase Amount": amounts,
            "Signup Date": signup,
            "Country": country,
            "Notes": notes,
        }
    )

    # Inject quality problems.
    frame.loc[rng.choice(rows, 20, replace=False), "Email"] = "not-an-email"
    frame.loc[rng.choice(rows, 15, replace=False), "Phone"] = "N/A"
    frame.loc[rng.choice(rows, 25, replace=False), "Purchase Amount"] = np.nan
    frame.loc[rng.choice(rows, 5, replace=False), "Purchase Amount"] = 99999.0
    frame.loc[rng.choice(rows, 10, replace=False), "Signup Date"] = "31/31/2023"
    # Duplicate a handful of rows.
    duplicates = frame.sample(8, random_state=SEED)
    return pd.concat([frame, duplicates], ignore_index=True)


def build_drift_pair(
    rng: np.random.Generator, rows: int = 1000
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build baseline/current datasets with injected schema and data drift."""
    baseline = pd.DataFrame(
        {
            "age": rng.normal(40, 10, rows).round(),
            "income": rng.normal(60000, 15000, rows).round(),
            "region": rng.choice(["north", "south", "east", "west"], rows),
        }
    )
    current = pd.DataFrame(
        {
            "age": rng.normal(46, 12, rows).round(),  # distribution shift
            "income": rng.normal(60000, 15000, rows).round().astype(float),
            "region": rng.choice(["north", "south", "east", "west"], rows, p=[0.5, 0.2, 0.2, 0.1]),
            "channel": rng.choice(["web", "store"], rows),  # added column
        }
    )
    return baseline, current


def main() -> None:
    """Generate and persist the sample datasets."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    customers = build_customers(rng)
    customers.to_csv(OUTPUT_DIR / "customers.csv", index=False)
    customers.to_json(OUTPUT_DIR / "customers.json", orient="records", indent=2)
    customers.to_parquet(OUTPUT_DIR / "customers.parquet", index=False)

    baseline, current = build_drift_pair(rng)
    baseline.to_csv(OUTPUT_DIR / "baseline.csv", index=False)
    current.to_csv(OUTPUT_DIR / "current.csv", index=False)

    print(f"Sample data written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
