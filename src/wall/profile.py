from __future__ import annotations

import gc
import importlib.util
import os
import threading
import time
from typing import Any

import pandas as pd


_PSUTIL_SPEC = importlib.util.find_spec("psutil")
if _PSUTIL_SPEC is not None:
    import psutil
else:
    psutil = None

_PYARROW_SPEC = importlib.util.find_spec("pyarrow")
if _PYARROW_SPEC is not None:
    import pyarrow as pa
else:
    pa = None


def viewer_profile_enabled() -> bool:
    value = os.environ.get("WALL_VIEWER_PROFILE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def viewer_profile_gc_enabled() -> bool:
    value = os.environ.get("WALL_PROFILE_GC", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def current_rss_mb() -> float | None:
    if psutil is None:
        return None
    try:
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def current_pyarrow_allocated_mb() -> float | None:
    if pa is None:
        return None
    try:
        return pa.total_allocated_bytes() / (1024 * 1024)
    except Exception:
        return None


def current_thread_label() -> str:
    thread = threading.current_thread()
    if thread is threading.main_thread():
        return "main"
    return f"bg:{thread.name}"


def collected_rss_mb() -> float | None:
    if not viewer_profile_enabled() or not viewer_profile_gc_enabled():
        return None
    try:
        gc.collect()
    except Exception:
        return None
    return current_rss_mb()


def profile_log(
    stage: str,
    *,
    started_at: float | None = None,
    df: pd.DataFrame | None = None,
    round_id: int | None = None,
    map_name: str | None = None,
    tick_range: tuple[int, int] | None = None,
    note: str | None = None,
) -> None:
    if not viewer_profile_enabled():
        return
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0 if started_at is not None else None
    rss_mb = current_rss_mb()
    rss_post_gc_mb = collected_rss_mb()
    pyarrow_mb = current_pyarrow_allocated_mb()
    parts: list[str] = [f"[viewer-profile] stage={stage}"]
    if elapsed_ms is not None:
        parts.append(f"elapsed_ms={elapsed_ms:.1f}")
    parts.append(f"thread={current_thread_label()}")
    if rss_mb is not None:
        parts.append(f"rss_mb={rss_mb:.1f}")
    if rss_post_gc_mb is not None:
        parts.append(f"rss_post_gc_mb={rss_post_gc_mb:.1f}")
    if pyarrow_mb is not None:
        parts.append(f"pyarrow_mb={pyarrow_mb:.1f}")
    if df is not None:
        parts.append(f"shape={df.shape}")
    if round_id is not None:
        parts.append(f"round_id={int(round_id)}")
    if map_name:
        parts.append(f"map={map_name}")
    if tick_range is not None:
        parts.append(f"tick_range={tick_range[0]}..{tick_range[1]}")
    if note:
        parts.append(f"note={note}")
    print(" ".join(parts), flush=True)


def profile_table_log(
    table_name: str,
    *,
    round_id: int,
    read_path: str,
    filter_column: str | None,
    started_at: float,
    rss_before_mb: float | None,
    before_df: pd.DataFrame | None,
    after_df: pd.DataFrame | None,
    tick_column: str = "tick",
    note: str | None = None,
) -> None:
    if not viewer_profile_enabled():
        return
    rss_after_mb = current_rss_mb()
    rss_post_gc_mb = collected_rss_mb()
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    pyarrow_mb = current_pyarrow_allocated_mb()
    parts: list[str] = [
        "[viewer-profile]",
        "kind=table-load",
        f"table={table_name}",
        f"round_id={int(round_id)}",
        f"read_path={read_path}",
        f"elapsed_ms={elapsed_ms:.1f}",
        f"thread={current_thread_label()}",
    ]
    if rss_before_mb is not None:
        parts.append(f"rss_before_mb={rss_before_mb:.1f}")
    if rss_after_mb is not None:
        parts.append(f"rss_after_mb={rss_after_mb:.1f}")
    if rss_post_gc_mb is not None:
        parts.append(f"rss_post_gc_mb={rss_post_gc_mb:.1f}")
    if rss_before_mb is not None and rss_after_mb is not None:
        parts.append(f"rss_delta_mb={rss_after_mb - rss_before_mb:.1f}")
    if pyarrow_mb is not None:
        parts.append(f"pyarrow_mb={pyarrow_mb:.1f}")
    parts.append(f"shape_before={shape_text(before_df)}")
    parts.append(f"shape_after={shape_text(after_df)}")
    if filter_column:
        parts.append(f"filter_column={filter_column}")
    tick_range = frame_tick_range(after_df if after_df is not None else pd.DataFrame(), tick_column=tick_column)
    if tick_range is not None:
        parts.append(f"tick_range={tick_range[0]}..{tick_range[1]}")
    if note:
        parts.append(f"note={note}")
    print(" ".join(parts), flush=True)




def frame_tick_range(df: pd.DataFrame, *, tick_column: str = "tick") -> tuple[int, int] | None:
    if df.empty or tick_column not in df.columns:
        return None
    ticks = pd.to_numeric(df[tick_column], errors="coerce").dropna()
    if ticks.empty:
        return None
    return int(ticks.min()), int(ticks.max())


def shape_text(df: pd.DataFrame | None) -> str:
    if df is None:
        return "none"
    return str(df.shape)


def profile_note(*parts: Any) -> str:
    return " ".join(str(part) for part in parts if part is not None and str(part) != "")
