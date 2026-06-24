from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import io
from pathlib import Path
import time
from typing import Callable

import pandas as pd

from wall.dataset.rounds import RoundData
from wall.domain.visibility_profile import VisibilityProfile
from wall.io.table_io import DEFAULT_TABLE_FORMAT, normalize_table_format
from wall.visibility.context import MapVisibilityContext
from wall.visibility.dataset import MatchDataset


@dataclass(frozen=True)
class VisibilityResultRow:
    tick: int
    round_id: int
    observer: str
    target: str
    observer_team: int | None
    target_team: int | None
    observer_x: float | None
    observer_y: float | None
    observer_z: float | None
    target_x: float | None
    target_y: float | None
    target_z: float | None
    observer_yaw: float | None
    distance: float | None
    relative_yaw_deg: float | None
    in_fov: bool
    has_los: bool | None
    is_visible: bool


@dataclass(frozen=True)
class VisibilityResultSet:
    round_id: int
    output_kind: str
    rows: tuple[VisibilityResultRow, ...]


class VisibilityExportResult:
    def __init__(
        self,
        output_paths: dict[str, Path],
        profile: VisibilityProfile | None = None,
        tables: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        self.output_paths = output_paths
        self.profile = profile
        self.tables = {} if tables is None else tables

    @property
    def output_path(self) -> Path:
        return next(iter(self.output_paths.values()))


@dataclass(frozen=True)
class VisibilityBatchRoundResult:
    round_id: int
    output_paths: dict[str, Path]
    profile: VisibilityProfile | None = None
    tables: dict[str, pd.DataFrame] | None = None

    @property
    def output_path(self) -> Path:
        return next(iter(self.output_paths.values()))


@dataclass(frozen=True)
class VisibilityBatchExportResult:
    round_results: tuple[VisibilityBatchRoundResult, ...]
    aggregate_profile: VisibilityProfile | None
    output_paths: dict[str, Path] | None = None


@dataclass(frozen=True)
class _VisibilityWorkerTask:
    worker_index: int
    data_dir: str
    round_ids: tuple[int, ...]
    output_path: str | None
    observer: str | None
    tick: int | None
    tick_step: int
    skip_freeze_time: bool
    only_visible: bool
    summary: bool
    output_kind: str | None
    tickrate: float
    table_format: str | None
    profile_visibility: bool
    combine_rounds: bool


@dataclass(frozen=True)
class _VisibilityWorkerResult:
    worker_index: int
    assigned_round_ids: tuple[int, ...]
    round_results: tuple[VisibilityBatchRoundResult, ...]
    checker_builds: int


class LosOverlapResult:
    def __init__(
        self,
        *,
        summary_unique_keys: int,
        pair_unique_keys: int,
        shared_keys: int,
        summary_only_keys: int,
        pair_only_keys: int,
        overlap_ratio: float,
        estimated_checker_calls_separate: int,
        estimated_checker_calls_unified: int,
    ) -> None:
        self.summary_unique_keys = summary_unique_keys
        self.pair_unique_keys = pair_unique_keys
        self.shared_keys = shared_keys
        self.summary_only_keys = summary_only_keys
        self.pair_only_keys = pair_only_keys
        self.overlap_ratio = overlap_ratio
        self.estimated_checker_calls_separate = estimated_checker_calls_separate
        self.estimated_checker_calls_unified = estimated_checker_calls_unified

    def render_summary(self, *, dataset: str, round_id: int) -> str:
        lines = [
            "",
            "LOS Overlap Diagnostic",
            f"Dataset: {dataset}",
            f"Round: {round_id}",
            "",
            f"{'metric':36} {'value':>12}",
            f"{'-' * 36} {'-' * 12}",
            f"{'summary unique LOS keys':36} {self.summary_unique_keys:12d}",
            f"{'pair unique LOS keys':36} {self.pair_unique_keys:12d}",
            f"{'keys requested by both':36} {self.shared_keys:12d}",
            f"{'summary-only keys':36} {self.summary_only_keys:12d}",
            f"{'pair-only keys':36} {self.pair_only_keys:12d}",
            f"{'overlap ratio':36} {self.overlap_ratio:11.2%}",
            f"{'estimated checker calls separate':36} {self.estimated_checker_calls_separate:12d}",
            f"{'estimated checker calls unified':36} {self.estimated_checker_calls_unified:12d}",
        ]
        return "\n".join(lines)


def _coerce_round_data(
    data_dir: Path,
    *,
    round_id: int,
    tickrate: float,
    visibility_profile: VisibilityProfile | None = None,
    dataset: MatchDataset | None = None,
    map_visibility_context: MapVisibilityContext | None = None,
) -> RoundData:
    loaded_dataset = MatchDataset.from_data_dir(data_dir) if dataset is None else dataset
    context = map_visibility_context or MapVisibilityContext.for_map(
        loaded_dataset.map_name,
        visibility_profile=visibility_profile,
    )
    return loaded_dataset.build_round_data(
        round_id,
        tickrate=tickrate,
        visibility_profile=visibility_profile,
        map_visibility_context=context,
    )


def _select_tick_values(
    round_data: RoundData,
    *,
    tick: int | None,
    tick_step: int,
    skip_freeze_time: bool,
) -> list[int]:
    profiler = round_data.visibility_timeline.visibility_profile
    started_at = time.perf_counter()
    effective_step = max(1, int(tick_step))
    if tick is not None:
        tick_values = [int(tick)]
    else:
        tick_values = list(round_data.frame_ticks[::effective_step])
        if skip_freeze_time:
            tick_values = [frame_tick for frame_tick in tick_values if frame_tick >= int(round_data.live_start_tick)]
    if profiler is not None:
        profiler.sampled_tick_selection_seconds += time.perf_counter() - started_at
        profiler.total_ticks_visited = len(round_data.frame_ticks)
        profiler.sampled_ticks_visited = len(tick_values)
    return tick_values


def build_visibility_result_set(
    round_data: RoundData,
    *,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    output_kind: str = "pair",
) -> VisibilityResultSet:
    profiler = round_data.visibility_timeline.visibility_profile
    if profiler is not None:
        profiler.output_kind = output_kind
        profiler.unified_visibility_pass_enabled = True
    tick_values = _select_tick_values(
        round_data,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
    )
    observer_names = [observer] if observer is not None else list(round_data.round_players.ordered_names)
    rows: list[VisibilityResultRow] = []
    for frame_tick in tick_values:
        tick_frames = round_data.round_players.frames_by_tick.get(int(frame_tick), {})
        if profiler is not None:
            profiler.alive_players_processed += len(round_data.round_players.alive_players_at(frame_tick))
        for observer_name in observer_names:
            if not observer_name:
                continue
            state = round_data.visibility_timeline.state_at(observer_name, frame_tick)
            for judgement in state.judgements:
                observer_frame = tick_frames.get(judgement.observer)
                target_frame = tick_frames.get(judgement.target)
                rows.append(
                    VisibilityResultRow(
                        tick=int(frame_tick),
                        round_id=int(round_data.round_id),
                        observer=judgement.observer,
                        target=judgement.target,
                        observer_team=None if observer_frame is None else observer_frame.team_num,
                        target_team=None if target_frame is None else target_frame.team_num,
                        observer_x=None if judgement.observer_position is None else judgement.observer_position[0],
                        observer_y=None if judgement.observer_position is None else judgement.observer_position[1],
                        observer_z=None if judgement.observer_position is None else judgement.observer_position[2],
                        target_x=None if judgement.target_position is None else judgement.target_position[0],
                        target_y=None if judgement.target_position is None else judgement.target_position[1],
                        target_z=None if judgement.target_position is None else judgement.target_position[2],
                        observer_yaw=None if observer_frame is None else observer_frame.yaw,
                        distance=judgement.distance,
                        relative_yaw_deg=judgement.relative_yaw_deg,
                        in_fov=bool(judgement.in_fov),
                        has_los=judgement.has_los,
                        is_visible=bool(judgement.is_visible),
                    )
                )
    return VisibilityResultSet(round_id=int(round_data.round_id), output_kind=output_kind, rows=tuple(rows))


def _result_rows_to_pair_table(result_set: VisibilityResultSet, *, only_visible: bool) -> pd.DataFrame:
    rows = [asdict(row) for row in result_set.rows if not only_visible or row.is_visible]
    table = pd.DataFrame(rows)
    expected_columns = [
        "tick",
        "round_id",
        "observer",
        "target",
        "distance",
        "relative_yaw_deg",
        "in_fov",
        "has_los",
        "is_visible",
    ]
    if table.empty:
        return pd.DataFrame(columns=expected_columns)
    return table[expected_columns]


def _result_rows_to_summary_table(result_set: VisibilityResultSet, *, only_visible: bool) -> pd.DataFrame:
    grouped: dict[tuple[int, str], dict[str, object]] = {}
    for row in result_set.rows:
        key = (int(row.tick), str(row.observer))
        if key not in grouped:
            grouped[key] = {
                "tick": int(row.tick),
                "round_id": int(row.round_id),
                "observer": row.observer,
                "pair_count": 0,
                "fov_targets": [],
                "visible_targets": [],
            }
        entry = grouped[key]
        if only_visible:
            if row.is_visible:
                entry["pair_count"] = int(entry["pair_count"]) + 1
                entry["visible_targets"].append(row.target)
        else:
            entry["pair_count"] = int(entry["pair_count"]) + 1
            if row.in_fov:
                entry["fov_targets"].append(row.target)
            if row.is_visible:
                entry["visible_targets"].append(row.target)
    summary_rows: list[dict[str, object]] = []
    for entry in grouped.values():
        fov_targets = [] if only_visible else list(entry["fov_targets"])
        visible_targets = list(entry["visible_targets"])
        summary_rows.append(
            {
                "tick": int(entry["tick"]),
                "round_id": int(entry["round_id"]),
                "observer": str(entry["observer"]),
                "pair_count": int(entry["pair_count"]),
                "fov_count": len(fov_targets),
                "visible_count": len(visible_targets),
                "fov_targets": "|".join(fov_targets),
                "visible_targets": "|".join(visible_targets),
            }
        )
    summary = pd.DataFrame(summary_rows)
    if summary.empty:
        return summary
    return summary[summary["fov_count"] > 0].reset_index(drop=True) if not only_visible else summary.reset_index(drop=True)


def build_visibility_table(
    round_data: RoundData,
    *,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
) -> pd.DataFrame:
    result_set = build_visibility_result_set(
        round_data,
        observer=observer,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
        output_kind="pair",
    )
    return _result_rows_to_pair_table(result_set, only_visible=only_visible)


def build_visibility_summary_table(
    round_data: RoundData,
    *,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
) -> pd.DataFrame:
    result_set = build_visibility_result_set(
        round_data,
        observer=observer,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
        output_kind="summary",
    )
    return _result_rows_to_summary_table(result_set, only_visible=only_visible)


def _default_output_path(
    data_dir: Path,
    *,
    round_id: int | None,
    output_kind: str,
    output_format: str,
    observer: str | None,
    tick: int | None,
    tick_step: int,
    skip_freeze_time: bool,
    only_visible: bool,
) -> Path:
    stem = "visibility_summary" if output_kind == "summary" else "visibility"
    stem += "_all_rounds" if round_id is None else f"_round_{round_id:02d}"
    if tick is not None:
        stem += f"_tick_{int(tick)}"
    elif tick_step > 1:
        stem += f"_step_{int(tick_step)}"
    if skip_freeze_time and tick is None:
        stem += "_post_freeze"
    if observer:
        safe_observer = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in observer)
        stem += f"_{safe_observer}"
    if only_visible:
        stem += "_visible_only"
    suffix = ".parquet" if output_format == "parquet" else ".csv"
    return data_dir / f"{stem}{suffix}"


def _write_table_to_path(
    table: pd.DataFrame,
    output_path: Path,
    *,
    output_format: str,
    profile: VisibilityProfile | None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if profile is not None:
        if output_format == "parquet":
            serialization_started_at = time.perf_counter()
            buffer = io.BytesIO()
            table.to_parquet(buffer, index=False)
            payload = buffer.getvalue()
            profile.cache_serialization_seconds += time.perf_counter() - serialization_started_at
            write_started_at = time.perf_counter()
            output_path.write_bytes(payload)
            profile.cache_file_writing_seconds += time.perf_counter() - write_started_at
        else:
            serialization_started_at = time.perf_counter()
            buffer = io.StringIO()
            table.to_csv(buffer, index=False)
            payload = buffer.getvalue()
            profile.cache_serialization_seconds += time.perf_counter() - serialization_started_at
            write_started_at = time.perf_counter()
            output_path.write_text(payload, encoding="utf-8", newline="")
            profile.cache_file_writing_seconds += time.perf_counter() - write_started_at
    else:
        if output_format == "parquet":
            table.to_parquet(output_path, index=False)
        else:
            table.to_csv(output_path, index=False)


def _build_visibility_output_tables(
    result_set: VisibilityResultSet,
    *,
    only_visible: bool,
    resolved_output_kind: str,
    profile: VisibilityProfile | None,
) -> dict[str, pd.DataFrame]:
    kinds = ("summary", "pair") if resolved_output_kind == "both" else (resolved_output_kind,)
    tables: dict[str, pd.DataFrame] = {}
    for kind in kinds:
        writer_started_at = time.perf_counter()
        table = (
            _result_rows_to_summary_table(result_set, only_visible=only_visible)
            if kind == "summary"
            else _result_rows_to_pair_table(result_set, only_visible=only_visible)
        )
        if profile is not None:
            elapsed = time.perf_counter() - writer_started_at
            if kind == "summary":
                profile.summary_writer_seconds += elapsed
            else:
                profile.pair_writer_seconds += elapsed
        tables[kind] = table
    return tables


def run_visibility_export(
    data_dir: Path,
    *,
    round_id: int,
    output_path: Path | None = None,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
    summary: bool = False,
    output_kind: str | None = None,
    tickrate: float = 64.0,
    table_format: str | None = None,
    profile_visibility: bool = False,
    dataset: MatchDataset | None = None,
    write_output: bool = True,
    map_visibility_context: MapVisibilityContext | None = None,
) -> VisibilityExportResult:
    resolved_output_kind = output_kind or ("summary" if summary else "pair")
    profile = VisibilityProfile(output_kind=resolved_output_kind) if profile_visibility else None
    pipeline_started_at = time.perf_counter()
    round_data = _coerce_round_data(
        data_dir,
        round_id=round_id,
        tickrate=tickrate,
        visibility_profile=profile,
        dataset=dataset,
        map_visibility_context=map_visibility_context,
    )
    result_set = build_visibility_result_set(
        round_data,
        observer=observer,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
        output_kind=resolved_output_kind,
    )
    output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
    tables = _build_visibility_output_tables(
        result_set,
        only_visible=only_visible,
        resolved_output_kind=resolved_output_kind,
        profile=profile,
    )
    output_paths: dict[str, Path] = {}
    if resolved_output_kind == "both" and output_path is not None:
        raise ValueError("Explicit --output is not supported when output kind is 'both'.")
    if write_output:
        for kind, table in tables.items():
            target_path = Path(output_path) if output_path is not None else _default_output_path(
                data_dir,
                round_id=round_id,
                output_kind=kind,
                output_format=output_format,
                observer=observer,
                tick=tick,
                tick_step=tick_step,
                skip_freeze_time=skip_freeze_time,
                only_visible=only_visible,
            )
            _write_table_to_path(table, target_path, output_format=output_format, profile=profile)
            output_paths[kind] = target_path
    if profile is not None:
        profile.total_visibility_pipeline_seconds = time.perf_counter() - pipeline_started_at
    return VisibilityExportResult(output_paths=output_paths, profile=profile, tables=tables)


def _chunk_round_ids(round_ids: list[int], jobs: int) -> list[tuple[int, ...]]:
    if not round_ids:
        return []
    worker_count = max(1, min(int(jobs), len(round_ids)))
    chunks: list[list[int]] = [[] for _ in range(worker_count)]
    for index, round_id in enumerate(round_ids):
        chunks[index % worker_count].append(int(round_id))
    return [tuple(chunk) for chunk in chunks if chunk]


def _concat_tables(tables: list[pd.DataFrame]) -> pd.DataFrame:
    if not tables:
        return pd.DataFrame()
    if len(tables) == 1:
        return tables[0].reset_index(drop=True)
    return pd.concat(tables, ignore_index=True)


def _run_visibility_worker_task(task: _VisibilityWorkerTask) -> _VisibilityWorkerResult:
    data_dir = Path(task.data_dir)
    dataset = MatchDataset.from_data_dir(data_dir)
    context = MapVisibilityContext.for_map(dataset.map_name)
    round_results: list[VisibilityBatchRoundResult] = []
    checker_builds = 0
    for round_id in task.round_ids:
        result = run_visibility_export(
            data_dir,
            round_id=int(round_id),
            output_path=None if task.output_path is None else Path(task.output_path),
            observer=task.observer,
            tick=task.tick,
            tick_step=task.tick_step,
            skip_freeze_time=task.skip_freeze_time,
            only_visible=task.only_visible,
            summary=task.summary,
            output_kind=task.output_kind,
            tickrate=task.tickrate,
            table_format=task.table_format,
            profile_visibility=task.profile_visibility,
            dataset=dataset,
            write_output=not task.combine_rounds,
            map_visibility_context=context,
        )
        if result.profile is not None:
            checker_builds += result.profile.checker_build_count
        round_results.append(
            VisibilityBatchRoundResult(
                round_id=int(round_id),
                output_paths=result.output_paths,
                profile=result.profile,
                tables=result.tables,
            )
        )
    return _VisibilityWorkerResult(
        worker_index=task.worker_index,
        assigned_round_ids=task.round_ids,
        round_results=tuple(round_results),
        checker_builds=checker_builds,
    )


def run_visibility_exports(
    data_dir: Path,
    *,
    round_ids: list[int],
    output_path: Path | None = None,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
    summary: bool = False,
    output_kind: str | None = None,
    tickrate: float = 64.0,
    table_format: str | None = None,
    profile_visibility: bool = False,
    dataset: MatchDataset | None = None,
    jobs: int = 4,
    combine_rounds: bool = True,
    progress_callback: Callable[[int, int, int], None] | None = None,
) -> VisibilityBatchExportResult:
    resolved_jobs = max(1, int(jobs))
    total_rounds = len(round_ids)
    if resolved_jobs == 1:
        round_results: list[VisibilityBatchRoundResult] = []
        aggregate_profile = (
            VisibilityProfile(output_kind=output_kind or ("summary" if summary else "pair"))
            if profile_visibility
            else None
        )
        loaded_dataset = dataset or MatchDataset.from_data_dir(data_dir)
        context = MapVisibilityContext.for_map(loaded_dataset.map_name)
        completed_rounds = 0
        for round_id in round_ids:
            result = run_visibility_export(
                data_dir,
                round_id=int(round_id),
                output_path=output_path,
                observer=observer,
                tick=tick,
                tick_step=tick_step,
                skip_freeze_time=skip_freeze_time,
                only_visible=only_visible,
                summary=summary,
                output_kind=output_kind,
                tickrate=tickrate,
                table_format=table_format,
                profile_visibility=profile_visibility,
                dataset=loaded_dataset,
                write_output=not combine_rounds,
                map_visibility_context=context,
            )
            round_results.append(
                VisibilityBatchRoundResult(
                    round_id=int(round_id),
                    output_paths=result.output_paths,
                    profile=result.profile,
                    tables=result.tables,
                )
            )
            if aggregate_profile is not None and result.profile is not None:
                aggregate_profile.merge_from(result.profile)
            completed_rounds += 1
            if progress_callback is not None:
                progress_callback(int(round_id), completed_rounds, total_rounds)
        combined_output_paths: dict[str, Path] | None = None
        if combine_rounds:
            output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
            combined_output_paths = {}
            first_tables = round_results[0].tables if round_results and round_results[0].tables is not None else {}
            for kind in first_tables:
                combined_table = _concat_tables(
                    [result.tables[kind] for result in round_results if result.tables is not None]
                )
                target_path = Path(output_path) if output_path is not None else _default_output_path(
                    data_dir,
                    round_id=None,
                    output_kind=kind,
                    output_format=output_format,
                    observer=observer,
                    tick=tick,
                    tick_step=tick_step,
                    skip_freeze_time=skip_freeze_time,
                    only_visible=only_visible,
                )
                _write_table_to_path(
                    combined_table,
                    target_path,
                    output_format=output_format,
                    profile=aggregate_profile,
                )
                combined_output_paths[kind] = target_path
        return VisibilityBatchExportResult(
            round_results=tuple(round_results),
            aggregate_profile=aggregate_profile,
            output_paths=combined_output_paths,
        )

    chunks = _chunk_round_ids(round_ids, resolved_jobs)
    worker_count = len(chunks)
    aggregate_profile = (
        VisibilityProfile(output_kind=output_kind or ("summary" if summary else "pair"))
        if profile_visibility
        else None
    )
    if aggregate_profile is not None:
        aggregate_profile.jobs = resolved_jobs
        aggregate_profile.worker_count = worker_count
    started_at = time.perf_counter()
    tasks = [
        _VisibilityWorkerTask(
            worker_index=worker_index,
            data_dir=str(data_dir),
            round_ids=chunk,
            output_path=None if output_path is None else str(output_path),
            observer=observer,
            tick=tick,
            tick_step=tick_step,
            skip_freeze_time=skip_freeze_time,
            only_visible=only_visible,
            summary=summary,
            output_kind=output_kind,
            tickrate=tickrate,
            table_format=table_format,
            profile_visibility=profile_visibility,
            combine_rounds=combine_rounds,
        )
        for worker_index, chunk in enumerate(chunks)
    ]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        future_to_task = {
            executor.submit(_run_visibility_worker_task, task): task
            for task in tasks
        }
        worker_results: list[_VisibilityWorkerResult] = []
        completed_rounds = 0
        for future in as_completed(future_to_task):
            worker_result = future.result()
            worker_results.append(worker_result)
            if progress_callback is not None:
                for round_result in sorted(worker_result.round_results, key=lambda result: result.round_id):
                    completed_rounds += 1
                    progress_callback(int(round_result.round_id), completed_rounds, total_rounds)
    round_results: list[VisibilityBatchRoundResult] = []
    for worker_result in worker_results:
        round_results.extend(worker_result.round_results)
        if aggregate_profile is not None:
            worker_name = f"worker-{worker_result.worker_index}"
            aggregate_profile.per_worker_assigned_rounds[worker_name] = worker_result.assigned_round_ids
            aggregate_profile.per_worker_checker_builds[worker_name] = worker_result.checker_builds
            for round_result in worker_result.round_results:
                if round_result.profile is not None:
                    aggregate_profile.merge_from(round_result.profile)
    if aggregate_profile is not None:
        aggregate_profile.wall_clock_elapsed_seconds = time.perf_counter() - started_at
    combined_output_paths: dict[str, Path] | None = None
    if combine_rounds:
        output_format = normalize_table_format(table_format or DEFAULT_TABLE_FORMAT)
        combined_output_paths = {}
        sorted_round_results = sorted(round_results, key=lambda result: result.round_id)
        first_tables = sorted_round_results[0].tables if sorted_round_results and sorted_round_results[0].tables is not None else {}
        for kind in first_tables:
            combined_table = _concat_tables(
                [result.tables[kind] for result in sorted_round_results if result.tables is not None]
            )
            target_path = Path(output_path) if output_path is not None else _default_output_path(
                data_dir,
                round_id=None,
                output_kind=kind,
                output_format=output_format,
                observer=observer,
                tick=tick,
                tick_step=tick_step,
                skip_freeze_time=skip_freeze_time,
                only_visible=only_visible,
            )
            _write_table_to_path(
                combined_table,
                target_path,
                output_format=output_format,
                profile=aggregate_profile,
            )
            combined_output_paths[kind] = target_path
    return VisibilityBatchExportResult(
        round_results=tuple(sorted(round_results, key=lambda result: result.round_id)),
        aggregate_profile=aggregate_profile,
        output_paths=combined_output_paths,
    )


def export_visibility_table(
    data_dir: Path,
    *,
    round_id: int,
    output_path: Path | None = None,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
    summary: bool = False,
    tickrate: float = 64.0,
    table_format: str | None = None,
) -> Path:
    result = run_visibility_export(
        data_dir,
        round_id=round_id,
        output_path=output_path,
        observer=observer,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
        only_visible=only_visible,
        summary=summary,
        tickrate=tickrate,
        table_format=table_format,
    )
    return result.output_path


def profile_los_overlap(
    data_dir: Path,
    *,
    round_id: int,
    observer: str | None = None,
    tick: int | None = None,
    tick_step: int = 1,
    skip_freeze_time: bool = True,
    only_visible: bool = False,
    tickrate: float = 64.0,
    dataset: MatchDataset | None = None,
    map_visibility_context: MapVisibilityContext | None = None,
) -> LosOverlapResult:
    profile = VisibilityProfile()
    round_data = _coerce_round_data(
        data_dir,
        round_id=round_id,
        tickrate=tickrate,
        visibility_profile=profile,
        dataset=dataset,
        map_visibility_context=map_visibility_context,
    )
    result_set = build_visibility_result_set(
        round_data,
        observer=observer,
        tick=tick,
        tick_step=tick_step,
        skip_freeze_time=skip_freeze_time,
        output_kind="both",
    )
    keys = {
        (int(row.tick), min(str(row.observer), str(row.target)), max(str(row.observer), str(row.target)))
        for row in result_set.rows
        if row.in_fov
    }
    summary_keys = keys
    pair_keys = keys
    shared_keys = summary_keys.intersection(pair_keys)
    summary_only = summary_keys - pair_keys
    pair_only = pair_keys - summary_keys
    union_size = len(summary_keys.union(pair_keys))
    overlap_ratio = (len(shared_keys) / union_size) if union_size > 0 else 0.0
    return LosOverlapResult(
        summary_unique_keys=len(summary_keys),
        pair_unique_keys=len(pair_keys),
        shared_keys=len(shared_keys),
        summary_only_keys=len(summary_only),
        pair_only_keys=len(pair_only),
        overlap_ratio=overlap_ratio,
        estimated_checker_calls_separate=len(summary_keys) + len(pair_keys),
        estimated_checker_calls_unified=union_size,
    )
