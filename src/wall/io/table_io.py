from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


DEFAULT_TABLE_FORMAT = "parquet" if importlib.util.find_spec("pyarrow") else "csv"
SUPPORTED_TABLE_FORMATS = ("parquet", "csv")
TABLE_STEMS = (
    "ticks",
    "player_death",
    "fire_bullets",
    "player_hurt",
    "player_bullet_hit",
    "smokegrenade_detonate",
    "flashbang_detonate",
    "hegrenade_detonate",
    "player_blind",
    "bomb_pickup",
    "bomb_dropped",
    "bomb_planted",
    "bomb_defused",
    "bomb_begindefuse",
    "bomb_abortdefuse",
    "bomb_exploded",
    "smokegrenade_expired",
    "inferno_startburn",
    "grenades",
    "inferred_rounds",
)


def normalize_table_format(table_format: str) -> str:
    value = table_format.lower().strip()
    if value not in SUPPORTED_TABLE_FORMATS:
        raise ValueError(f"Unsupported table format: {table_format}")
    return value


def table_path(output_dir: Path, stem: str, table_format: str) -> Path:
    normalized = normalize_table_format(table_format)
    suffix = ".parquet" if normalized == "parquet" else ".csv"
    return output_dir / f"{stem}{suffix}"


def write_table(df: pd.DataFrame, output_dir: Path, stem: str, table_format: str) -> Path:
    normalized = normalize_table_format(table_format)
    path = table_path(output_dir, stem, normalized)
    stale_format = "csv" if normalized == "parquet" else "parquet"
    stale_path = table_path(output_dir, stem, stale_format)
    if stale_path.exists():
        stale_path.unlink()
    if normalized == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def read_table_with_fallback(data_dir: Path, stem: str, required: bool = False) -> tuple[pd.DataFrame, str]:
    parquet_path = data_dir / f"{stem}.parquet"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path), parquet_path.name

    csv_path = data_dir / f"{stem}.csv"
    if csv_path.exists():
        return pd.read_csv(csv_path), csv_path.name

    if required:
        raise FileNotFoundError(
            f"Missing required table '{stem}' in {data_dir}. "
            f"Expected one of: {parquet_path.name}, {csv_path.name}"
        )
    return pd.DataFrame(), f"{stem}.missing"


def detect_existing_tables(data_dir: Path) -> list[tuple[str, Path, str]]:
    tables: list[tuple[str, Path, str]] = []
    seen_stems: set[str] = set()

    for stem in TABLE_STEMS:
        for table_format in SUPPORTED_TABLE_FORMATS:
            path = table_path(data_dir, stem, table_format)
            if path.exists():
                tables.append((stem, path, table_format))
                seen_stems.add(stem)
                break

    for path in sorted(data_dir.glob("*.parquet")):
        if path.stem not in seen_stems:
            tables.append((path.stem, path, "parquet"))
            seen_stems.add(path.stem)

    for path in sorted(data_dir.glob("*.csv")):
        if path.stem not in seen_stems:
            tables.append((path.stem, path, "csv"))
            seen_stems.add(path.stem)

    return tables
