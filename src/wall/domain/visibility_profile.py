from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


DISTANCE_THRESHOLDS = (4000.0, 6000.0, 8000.0)
LOS_SOURCES = ("summary", "pair", "other")


@dataclass
class VisibilityProfile:
    jobs: int = 1
    worker_count: int = 1
    wall_clock_elapsed_seconds: float = 0.0
    total_visibility_pipeline_seconds: float = 0.0
    output_kind: str = "pair"
    unified_visibility_pass_enabled: bool = False
    checker_construction_seconds: float = 0.0
    player_frame_extraction_seconds: float = 0.0
    round_lookup_seconds: float = 0.0
    sampled_tick_selection_seconds: float = 0.0
    player_timeline_lookup_seconds: float = 0.0
    alive_team_filtering_seconds: float = 0.0
    coordinate_extraction_seconds: float = 0.0
    yaw_pitch_extraction_seconds: float = 0.0
    frame_object_construction_seconds: float = 0.0
    candidate_pair_generation_seconds: float = 0.0
    fov_filtering_seconds: float = 0.0
    los_seconds: float = 0.0
    cache_serialization_seconds: float = 0.0
    cache_file_writing_seconds: float = 0.0
    summary_writer_seconds: float = 0.0
    pair_writer_seconds: float = 0.0
    total_ticks_visited: int = 0
    sampled_ticks_visited: int = 0
    alive_players_processed: int = 0
    raw_observer_target_pairs: int = 0
    pairs_rejected_team_death_invalid: int = 0
    pairs_rejected_distance: int = 0
    pairs_rejected_fov: int = 0
    pairs_sent_to_checker: int = 0
    checker_is_visible_call_count: int = 0
    visible_pairs: int = 0
    invisible_pairs: int = 0
    not_visible_total_pairs: int = 0
    pre_los_rejected_pairs: int = 0
    los_call_count: int = 0
    max_los_call_seconds: float = 0.0
    los_cache_hits: int = 0
    los_cache_misses: int = 0
    duplicate_los_coordinate_pairs: int = 0
    unique_los_coordinate_pairs: int = 0
    los_glue_seconds: float = 0.0
    checker_cache_key: str = ""
    checker_cache_hits: int = 0
    checker_cache_misses: int = 0
    checker_build_count: int = 0
    distance_samples: list[float] = field(default_factory=list)
    los_requests_by_source: dict[str, int] = field(default_factory=lambda: {source: 0 for source in LOS_SOURCES})
    los_cache_hits_by_source: dict[str, int] = field(default_factory=lambda: {source: 0 for source in LOS_SOURCES})
    los_cache_misses_by_source: dict[str, int] = field(default_factory=lambda: {source: 0 for source in LOS_SOURCES})
    checker_calls_by_source: dict[str, int] = field(default_factory=lambda: {source: 0 for source in LOS_SOURCES})
    los_unique_keys_by_source: dict[str, set[tuple[int, str, str]]] = field(
        default_factory=lambda: {source: set() for source in LOS_SOURCES}
    )
    los_unique_keys_overall: set[tuple[int, str, str]] = field(default_factory=set)
    per_worker_assigned_rounds: dict[str, tuple[int, ...]] = field(default_factory=dict)
    per_worker_checker_builds: dict[str, int] = field(default_factory=dict)

    def record_los_call(self, seconds: float) -> None:
        duration = max(0.0, float(seconds))
        self.los_seconds += duration
        self.los_call_count += 1
        if duration > self.max_los_call_seconds:
            self.max_los_call_seconds = duration

    def record_distance(self, distance: float | None) -> None:
        if distance is None:
            return
        self.distance_samples.append(float(distance))

    def record_los_request(self, source: str, cache_key: tuple[int, str, str]) -> None:
        normalized = source if source in self.los_requests_by_source else "other"
        self.los_requests_by_source[normalized] += 1
        self.los_unique_keys_by_source[normalized].add(cache_key)
        self.los_unique_keys_overall.add(cache_key)

    @property
    def average_los_call_seconds(self) -> float:
        if self.los_call_count <= 0:
            return 0.0
        return self.los_seconds / self.los_call_count

    @property
    def los_calls_per_tick(self) -> float:
        if self.sampled_ticks_visited <= 0:
            return 0.0
        return self.los_call_count / self.sampled_ticks_visited

    @property
    def los_runtime_percent(self) -> float:
        if self.total_visibility_pipeline_seconds <= 0:
            return 0.0
        return (self.los_seconds / self.total_visibility_pipeline_seconds) * 100.0

    @property
    def non_los_runtime_percent(self) -> float:
        if self.total_visibility_pipeline_seconds <= 0:
            return 0.0
        non_los = max(0.0, self.total_visibility_pipeline_seconds - self.los_seconds)
        return (non_los / self.total_visibility_pipeline_seconds) * 100.0

    def distance_quantile(self, q: float) -> float:
        if not self.distance_samples:
            return 0.0
        return float(np.quantile(np.asarray(self.distance_samples, dtype=float), q))

    def distance_rejections_at(self, threshold: float) -> int:
        if not self.distance_samples:
            return 0
        return int(sum(1 for distance in self.distance_samples if distance > threshold))

    def merge_from(self, other: "VisibilityProfile") -> None:
        self.jobs = max(self.jobs, other.jobs)
        self.worker_count = max(self.worker_count, other.worker_count)
        self.wall_clock_elapsed_seconds = max(self.wall_clock_elapsed_seconds, other.wall_clock_elapsed_seconds)
        self.total_visibility_pipeline_seconds += other.total_visibility_pipeline_seconds
        self.summary_writer_seconds += other.summary_writer_seconds
        self.pair_writer_seconds += other.pair_writer_seconds
        self.checker_construction_seconds += other.checker_construction_seconds
        self.player_frame_extraction_seconds += other.player_frame_extraction_seconds
        self.round_lookup_seconds += other.round_lookup_seconds
        self.sampled_tick_selection_seconds += other.sampled_tick_selection_seconds
        self.player_timeline_lookup_seconds += other.player_timeline_lookup_seconds
        self.alive_team_filtering_seconds += other.alive_team_filtering_seconds
        self.coordinate_extraction_seconds += other.coordinate_extraction_seconds
        self.yaw_pitch_extraction_seconds += other.yaw_pitch_extraction_seconds
        self.frame_object_construction_seconds += other.frame_object_construction_seconds
        self.candidate_pair_generation_seconds += other.candidate_pair_generation_seconds
        self.fov_filtering_seconds += other.fov_filtering_seconds
        self.los_seconds += other.los_seconds
        self.cache_serialization_seconds += other.cache_serialization_seconds
        self.cache_file_writing_seconds += other.cache_file_writing_seconds
        self.total_ticks_visited += other.total_ticks_visited
        self.sampled_ticks_visited += other.sampled_ticks_visited
        self.alive_players_processed += other.alive_players_processed
        self.raw_observer_target_pairs += other.raw_observer_target_pairs
        self.pairs_rejected_team_death_invalid += other.pairs_rejected_team_death_invalid
        self.pairs_rejected_distance += other.pairs_rejected_distance
        self.pairs_rejected_fov += other.pairs_rejected_fov
        self.pairs_sent_to_checker += other.pairs_sent_to_checker
        self.checker_is_visible_call_count += other.checker_is_visible_call_count
        self.visible_pairs += other.visible_pairs
        self.invisible_pairs += other.invisible_pairs
        self.not_visible_total_pairs += other.not_visible_total_pairs
        self.pre_los_rejected_pairs += other.pre_los_rejected_pairs
        self.los_call_count += other.los_call_count
        self.max_los_call_seconds = max(self.max_los_call_seconds, other.max_los_call_seconds)
        self.los_cache_hits += other.los_cache_hits
        self.los_cache_misses += other.los_cache_misses
        self.duplicate_los_coordinate_pairs += other.duplicate_los_coordinate_pairs
        self.unique_los_coordinate_pairs += other.unique_los_coordinate_pairs
        self.los_glue_seconds += other.los_glue_seconds
        self.checker_cache_hits += other.checker_cache_hits
        self.checker_cache_misses += other.checker_cache_misses
        self.checker_build_count += other.checker_build_count
        self.distance_samples.extend(other.distance_samples)
        for source in LOS_SOURCES:
            self.los_requests_by_source[source] += other.los_requests_by_source[source]
            self.los_cache_hits_by_source[source] += other.los_cache_hits_by_source[source]
            self.los_cache_misses_by_source[source] += other.los_cache_misses_by_source[source]
            self.checker_calls_by_source[source] += other.checker_calls_by_source[source]
            self.los_unique_keys_by_source[source].update(other.los_unique_keys_by_source[source])
        self.los_unique_keys_overall.update(other.los_unique_keys_overall)
        self.per_worker_assigned_rounds.update(other.per_worker_assigned_rounds)
        self.per_worker_checker_builds.update(other.per_worker_checker_builds)
        if not self.checker_cache_key:
            self.checker_cache_key = other.checker_cache_key
        if self.output_kind == "pair":
            self.output_kind = other.output_kind
        self.unified_visibility_pass_enabled = self.unified_visibility_pass_enabled or other.unified_visibility_pass_enabled

    def render_summary(self, *, dataset: str, round_id: int, output_path: str) -> str:
        lines = [
            "",
            "Visibility Profile Summary",
            f"Dataset: {dataset}",
            f"Round: {round_id}",
            f"Output: {output_path}",
            "",
            "Timings",
            f"{'metric':36} {'seconds':>12}",
            f"{'-' * 36} {'-' * 12}",
            f"{'total visibility pipeline time':36} {self.total_visibility_pipeline_seconds:12.3f}",
            f"{'summary writer time':36} {self.summary_writer_seconds:12.3f}",
            f"{'pair writer time':36} {self.pair_writer_seconds:12.3f}",
            f"{'VisibilityChecker construction time':36} {self.checker_construction_seconds:12.3f}",
            f"{'player frame extraction time':36} {self.player_frame_extraction_seconds:12.3f}",
            f"{'round lookup time':36} {self.round_lookup_seconds:12.3f}",
            f"{'sampled tick selection time':36} {self.sampled_tick_selection_seconds:12.3f}",
            f"{'player timeline/state lookup time':36} {self.player_timeline_lookup_seconds:12.3f}",
            f"{'alive/team filtering time':36} {self.alive_team_filtering_seconds:12.3f}",
            f"{'coordinate extraction time':36} {self.coordinate_extraction_seconds:12.3f}",
            f"{'yaw/pitch extraction time':36} {self.yaw_pitch_extraction_seconds:12.3f}",
            f"{'PlayerFrame/dict construction time':36} {self.frame_object_construction_seconds:12.3f}",
            f"{'candidate pair generation time':36} {self.candidate_pair_generation_seconds:12.3f}",
            f"{'FOV filtering time':36} {self.fov_filtering_seconds:12.3f}",
            f"{'LOS / checker.is_visible() time':36} {self.los_seconds:12.3f}",
            f"{'cache serialization time':36} {self.cache_serialization_seconds:12.3f}",
            f"{'cache file writing time':36} {self.cache_file_writing_seconds:12.3f}",
        ]
        lines.extend(
            [
                "",
                "Concurrency",
                f"{'metric':36} {'value':>12}",
                f"{'-' * 36} {'-' * 12}",
                f"{'jobs':36} {self.jobs:12d}",
                f"{'worker count':36} {self.worker_count:12d}",
                f"{'wall-clock elapsed time':36} {self.wall_clock_elapsed_seconds:12.3f}",
                f"{'aggregate total round pipeline time':36} {self.total_visibility_pipeline_seconds:12.3f}",
                f"{'aggregate checker.is_visible() calls':36} {self.checker_is_visible_call_count:12d}",
            ]
        )
        for worker_name in sorted(self.per_worker_assigned_rounds):
            rounds = ",".join(str(value) for value in self.per_worker_assigned_rounds[worker_name]) or "-"
            lines.append(f"{(worker_name + ' rounds'):36} {rounds:>12}")
            lines.append(
                f"{(worker_name + ' checker builds'):36} {self.per_worker_checker_builds.get(worker_name, 0):12d}"
            )
        lines.extend(
            [
                "",
                "Checker Cache",
                f"{'metric':36} {'value':>12}",
                f"{'-' * 36} {'-' * 12}",
                f"{'output kind':36} {self.output_kind:>12}",
                f"{'unified visibility pass':36} {str(self.unified_visibility_pass_enabled):>12}",
                f"{'checker cache key':36} {self.checker_cache_key or '-':>12}",
                f"{'checker cache hits':36} {self.checker_cache_hits:12d}",
                f"{'checker cache misses':36} {self.checker_cache_misses:12d}",
                f"{'checker builds':36} {self.checker_build_count:12d}",
                f"{'LOS cache hits':36} {self.los_cache_hits:12d}",
                f"{'LOS cache misses':36} {self.los_cache_misses:12d}",
                f"{'duplicate LOS coord pairs':36} {self.duplicate_los_coordinate_pairs:12d}",
                f"{'unique LOS coord pairs':36} {self.unique_los_coordinate_pairs:12d}",
                "",
                "LOS Sources",
                f"{'metric':36} {'value':>12}",
                f"{'-' * 36} {'-' * 12}",
                f"{'summary logical LOS requests':36} {self.los_requests_by_source['summary']:12d}",
                f"{'summary LOS cache hits':36} {self.los_cache_hits_by_source['summary']:12d}",
                f"{'summary LOS cache misses':36} {self.los_cache_misses_by_source['summary']:12d}",
                f"{'summary checker calls':36} {self.checker_calls_by_source['summary']:12d}",
                f"{'pair logical LOS requests':36} {self.los_requests_by_source['pair']:12d}",
                f"{'pair LOS cache hits':36} {self.los_cache_hits_by_source['pair']:12d}",
                f"{'pair LOS cache misses':36} {self.los_cache_misses_by_source['pair']:12d}",
                f"{'pair checker calls':36} {self.checker_calls_by_source['pair']:12d}",
                f"{'other logical LOS requests':36} {self.los_requests_by_source['other']:12d}",
                f"{'other LOS cache hits':36} {self.los_cache_hits_by_source['other']:12d}",
                f"{'other LOS cache misses':36} {self.los_cache_misses_by_source['other']:12d}",
                f"{'other checker calls':36} {self.checker_calls_by_source['other']:12d}",
                f"{'unique LOS keys overall':36} {len(self.los_unique_keys_overall):12d}",
                f"{'unique LOS keys summary':36} {len(self.los_unique_keys_by_source['summary']):12d}",
                f"{'unique LOS keys pair':36} {len(self.los_unique_keys_by_source['pair']):12d}",
                f"{'keys requested by both summary/pair':36} {len(self.los_unique_keys_by_source['summary'].intersection(self.los_unique_keys_by_source['pair'])):12d}",
                "",
                "Counters",
                f"{'metric':36} {'count':>12}",
                f"{'-' * 36} {'-' * 12}",
                f"{'total ticks visited':36} {self.total_ticks_visited:12d}",
                f"{'sampled ticks visited':36} {self.sampled_ticks_visited:12d}",
                f"{'alive players processed':36} {self.alive_players_processed:12d}",
                f"{'raw observer-target pairs':36} {self.raw_observer_target_pairs:12d}",
                f"{'pairs rejected by team/death/invalid':36} {self.pairs_rejected_team_death_invalid:12d}",
                f"{'pairs rejected by distance':36} {self.pairs_rejected_distance:12d}",
                f"{'pairs rejected by FOV':36} {self.pairs_rejected_fov:12d}",
                f"{'pre-LOS rejected pairs':36} {self.pre_los_rejected_pairs:12d}",
                f"{'pairs sent to checker.is_visible()':36} {self.pairs_sent_to_checker:12d}",
                f"{'actual checker.is_visible() calls':36} {self.checker_is_visible_call_count:12d}",
                f"{'visible pairs (LOS visible)':36} {self.visible_pairs:12d}",
                f"{'LOS invisible pairs':36} {self.invisible_pairs:12d}",
                f"{'not visible total':36} {self.not_visible_total_pairs:12d}",
            ]
        )
        lines.extend(
            [
                "",
                "Derived",
                f"{'metric':36} {'value':>12}",
                f"{'-' * 36} {'-' * 12}",
                f"{'average LOS call time':36} {self.average_los_call_seconds:12.6f}",
                f"{'max LOS call time':36} {self.max_los_call_seconds:12.6f}",
                f"{'LOS calls per tick':36} {self.los_calls_per_tick:12.3f}",
                f"{'LOS glue overhead time':36} {self.los_glue_seconds:12.6f}",
                f"{'% runtime in checker.is_visible()':36} {self.los_runtime_percent:11.2f}%",
                f"{'% runtime outside checker.is_visible()':36} {self.non_los_runtime_percent:11.2f}%",
            ]
        )
        return "\n".join(lines)
