from __future__ import annotations

from dataclasses import dataclass
import math
import time

try:
    from awpy.visibility import VisibilityChecker
except ModuleNotFoundError:
    VisibilityChecker = None

from wall.domain.player import PlayerFrame, RoundPlayers
from wall.domain.visibility_profile import VisibilityProfile
EYE_HEIGHT_Z = 64.0


def _normalize_degrees(angle: float) -> float:
    normalized = (angle + 180.0) % 360.0 - 180.0
    if normalized == -180.0:
        return 180.0
    return normalized


@dataclass(frozen=True)
class VisibilityJudgement:
    observer: str
    target: str
    tick: int
    in_fov: bool
    has_los: bool | None
    is_visible: bool
    distance: float | None
    relative_yaw_deg: float | None
    observer_position: tuple[float, float, float] | None
    target_position: tuple[float, float, float] | None


@dataclass(frozen=True)
class PlayerVisibilityState:
    observer: str
    tick: int
    visible_enemies: tuple[str, ...]
    judgements: tuple[VisibilityJudgement, ...]


@dataclass(frozen=True)
class VisibilitySummary:
    observer: str
    tick: int
    pair_count: int
    fov_targets: tuple[str, ...]
    visible_targets: tuple[str, ...]


class VisibilityTimeline:
    def __init__(
        self,
        round_players: RoundPlayers,
        fov_deg: float = 90.0,
        visibility_checker: VisibilityChecker | None = None,
        visibility_profile: VisibilityProfile | None = None,
    ) -> None:
        self.round_players = round_players
        self.fov_deg = max(0.0, float(fov_deg))
        self.visibility_checker = visibility_checker
        self.visibility_profile = visibility_profile
        self._frame_cache: dict[tuple[str, int], PlayerFrame | None] = {}
        self._alive_frames_cache: dict[int, tuple[PlayerFrame, ...]] = {}
        self._los_cache: dict[tuple[int, str, str], bool | None] = {}
        self._los_request_source: str = "other"

    def _with_los_source(self, source: str):
        class _LosSourceContext:
            def __init__(self, timeline: "VisibilityTimeline", next_source: str) -> None:
                self.timeline = timeline
                self.next_source = next_source
                self.previous_source = timeline._los_request_source

            def __enter__(self) -> None:
                self.timeline._los_request_source = self.next_source
                return None

            def __exit__(self, exc_type, exc, tb) -> bool:
                self.timeline._los_request_source = self.previous_source
                return False

        return _LosSourceContext(self, source)

    def observer_target_visibility_at(self, observer: str, target: str, tick: int) -> VisibilityJudgement:
        observer_frame = self._frame_at(observer, tick)
        target_frame = self._frame_at(target, tick)
        if (
            observer_frame is None
            or target_frame is None
            or not observer_frame.is_alive
            or not target_frame.is_alive
            or not observer_frame.name
            or not target_frame.name
            or observer_frame.name == target_frame.name
            or observer_frame.team_num is None
            or target_frame.team_num is None
            or observer_frame.team_num == target_frame.team_num
        ):
            if self.visibility_profile is not None:
                self.visibility_profile.not_visible_total_pairs += 1
                self.visibility_profile.pre_los_rejected_pairs += 1
            return VisibilityJudgement(
                observer=observer,
                target=target,
                tick=int(tick),
                in_fov=False,
                has_los=self._has_line_of_sight(observer_frame, target_frame),
                is_visible=False,
                distance=self._distance_between(observer_frame, target_frame),
                relative_yaw_deg=self._relative_yaw_between(observer_frame, target_frame),
                observer_position=self._position_tuple(observer_frame),
                target_position=self._position_tuple(target_frame),
            )
        relative_yaw = self._relative_yaw_between(observer_frame, target_frame)
        fov_started_at = time.perf_counter()
        in_fov = relative_yaw is not None and abs(relative_yaw) <= (self.fov_deg / 2.0)
        if self.visibility_profile is not None:
            self.visibility_profile.fov_filtering_seconds += time.perf_counter() - fov_started_at
            if not in_fov:
                self.visibility_profile.pairs_rejected_fov += 1
                self.visibility_profile.not_visible_total_pairs += 1
                self.visibility_profile.pre_los_rejected_pairs += 1
                return VisibilityJudgement(
                    observer=observer_frame.name,
                    target=target_frame.name,
                    tick=int(tick),
                    in_fov=in_fov,
                    has_los=None,
                    is_visible=False,
                    distance=self._distance_between(observer_frame, target_frame),
                    relative_yaw_deg=relative_yaw,
                    observer_position=self._position_tuple(observer_frame),
                    target_position=self._position_tuple(target_frame),
                )
        elif not in_fov:
            return VisibilityJudgement(
                observer=observer_frame.name,
                target=target_frame.name,
                tick=int(tick),
                in_fov=in_fov,
                has_los=None,
                is_visible=False,
                distance=self._distance_between(observer_frame, target_frame),
                relative_yaw_deg=relative_yaw,
                observer_position=self._position_tuple(observer_frame),
                target_position=self._position_tuple(target_frame),
            )
        if self.visibility_profile is not None:
            self.visibility_profile.pairs_sent_to_checker += 1
        has_los = self._has_line_of_sight(observer_frame, target_frame)
        is_visible = in_fov and (True if has_los is None else has_los)
        if self.visibility_profile is not None:
            if has_los is False:
                self.visibility_profile.invisible_pairs += 1
                self.visibility_profile.not_visible_total_pairs += 1
            elif is_visible:
                self.visibility_profile.visible_pairs += 1
        return VisibilityJudgement(
            observer=observer_frame.name,
            target=target_frame.name,
            tick=int(tick),
            in_fov=in_fov,
            has_los=has_los,
            is_visible=is_visible,
            distance=self._distance_between(observer_frame, target_frame),
            relative_yaw_deg=relative_yaw,
            observer_position=self._position_tuple(observer_frame),
            target_position=self._position_tuple(target_frame),
        )

    def visible_enemies_at(self, observer: str, tick: int) -> list[str]:
        state = self.state_at(observer, tick)
        return list(state.visible_enemies)

    def state_at(self, observer: str, tick: int) -> PlayerVisibilityState:
        with self._with_los_source("pair"):
            observer_frame = self.round_players.frame_at(name=observer, tick=tick)
            if observer_frame is None or not observer_frame.is_alive or observer_frame.team_num is None:
                return PlayerVisibilityState(observer=observer, tick=int(tick), visible_enemies=(), judgements=())
            judgements: list[VisibilityJudgement] = []
            visible_enemies: list[str] = []
            for target_frame in self._profiled_valid_targets(observer_frame, tick):
                judgement = self.observer_target_visibility_at(observer_frame.name, target_frame.name, tick)
                judgements.append(judgement)
                if judgement.is_visible:
                    visible_enemies.append(target_frame.name)
            return PlayerVisibilityState(
                observer=observer_frame.name,
                tick=int(tick),
                visible_enemies=tuple(visible_enemies),
                judgements=tuple(judgements),
            )

    def summary_at(self, observer: str, tick: int, *, only_visible: bool = False) -> VisibilitySummary:
        with self._with_los_source("summary"):
            observer_frame = self._frame_at(observer, tick)
            if observer_frame is None or not observer_frame.is_alive or observer_frame.team_num is None:
                return VisibilitySummary(
                    observer=observer,
                    tick=int(tick),
                    pair_count=0,
                    fov_targets=(),
                    visible_targets=(),
                )

            pair_count = 0
            fov_targets: list[str] = []
            visible_targets: list[str] = []
            for target_frame in self._profiled_valid_targets(observer_frame, tick):
                pair_count += 1
                fov_started_at = time.perf_counter()
                relative_yaw = self._relative_yaw_between(observer_frame, target_frame)
                in_fov = relative_yaw is not None and abs(relative_yaw) <= (self.fov_deg / 2.0)
                if self.visibility_profile is not None:
                    self.visibility_profile.fov_filtering_seconds += time.perf_counter() - fov_started_at
                if not in_fov:
                    if self.visibility_profile is not None:
                        self.visibility_profile.pairs_rejected_fov += 1
                        self.visibility_profile.not_visible_total_pairs += 1
                        self.visibility_profile.pre_los_rejected_pairs += 1
                    continue
                fov_targets.append(target_frame.name)
                if self.visibility_profile is not None:
                    self.visibility_profile.pairs_sent_to_checker += 1
                has_los = self._has_line_of_sight(observer_frame, target_frame)
                is_visible = True if has_los is None else bool(has_los)
                if is_visible:
                    visible_targets.append(target_frame.name)
                    if self.visibility_profile is not None:
                        self.visibility_profile.visible_pairs += 1
                elif self.visibility_profile is not None and has_los is False:
                    self.visibility_profile.invisible_pairs += 1
                    self.visibility_profile.not_visible_total_pairs += 1

            if only_visible:
                return VisibilitySummary(
                    observer=observer_frame.name,
                    tick=int(tick),
                    pair_count=len(visible_targets),
                    fov_targets=(),
                    visible_targets=tuple(visible_targets),
                )
            return VisibilitySummary(
                observer=observer_frame.name,
                tick=int(tick),
                pair_count=pair_count,
                fov_targets=tuple(fov_targets),
                visible_targets=tuple(visible_targets),
            )

    def _is_enemy(self, observer_frame: PlayerFrame, target_frame: PlayerFrame) -> bool:
        return (
            observer_frame.name != target_frame.name
            and observer_frame.team_num is not None
            and target_frame.team_num is not None
            and observer_frame.team_num != target_frame.team_num
        )

    def _position_tuple(self, frame: PlayerFrame | None) -> tuple[float, float, float] | None:
        if frame is None:
            return None
        return (float(frame.x), float(frame.y), float(frame.z))

    def _all_players_at(self, tick: int) -> tuple[PlayerFrame, ...]:
        tick_frames = self.round_players.frames_by_tick.get(int(tick), {})
        return tuple(tick_frames.values())

    def _has_valid_position(self, frame: PlayerFrame | None) -> bool:
        if frame is None:
            return False
        return (
            math.isfinite(float(frame.x))
            and math.isfinite(float(frame.y))
            and math.isfinite(float(frame.z))
        )

    def _profiled_valid_targets(self, observer_frame: PlayerFrame, tick: int) -> tuple[PlayerFrame, ...]:
        profiler = self.visibility_profile
        if profiler is None:
            return tuple(
                target_frame
                for target_frame in self._alive_players_at(tick)
                if self._is_enemy(observer_frame, target_frame)
            )
        generation_started_at = time.perf_counter()
        valid_targets: list[PlayerFrame] = []
        for target_frame in self._all_players_at(tick):
            if target_frame.name == observer_frame.name:
                continue
            profiler.raw_observer_target_pairs += 1
            if (
                not observer_frame.is_alive
                or observer_frame.team_num is None
                or not self._has_valid_position(observer_frame)
                or not target_frame.is_alive
                or target_frame.team_num is None
                or not self._has_valid_position(target_frame)
                or observer_frame.team_num == target_frame.team_num
            ):
                profiler.pairs_rejected_team_death_invalid += 1
                profiler.not_visible_total_pairs += 1
                profiler.pre_los_rejected_pairs += 1
                continue
            profiler.record_distance(self._distance_between(observer_frame, target_frame))
            valid_targets.append(target_frame)
        profiler.candidate_pair_generation_seconds += time.perf_counter() - generation_started_at
        return tuple(valid_targets)

    def _frame_at(self, name: str, tick: int) -> PlayerFrame | None:
        cache_key = (str(name), int(tick))
        if cache_key not in self._frame_cache:
            self._frame_cache[cache_key] = self.round_players.frame_at(name=name, tick=tick)
        return self._frame_cache[cache_key]

    def _alive_players_at(self, tick: int) -> tuple[PlayerFrame, ...]:
        cache_key = int(tick)
        if cache_key not in self._alive_frames_cache:
            self._alive_frames_cache[cache_key] = tuple(self.round_players.alive_players_at(cache_key))
        return self._alive_frames_cache[cache_key]

    def _distance_between(self, observer_frame: PlayerFrame | None, target_frame: PlayerFrame | None) -> float | None:
        if observer_frame is None or target_frame is None:
            return None
        dx = float(target_frame.x) - float(observer_frame.x)
        dy = float(target_frame.y) - float(observer_frame.y)
        dz = float(target_frame.z) - float(observer_frame.z)
        return math.sqrt((dx * dx) + (dy * dy) + (dz * dz))

    def _relative_yaw_between(self, observer_frame: PlayerFrame | None, target_frame: PlayerFrame | None) -> float | None:
        if observer_frame is None or target_frame is None:
            return None
        dx = float(target_frame.x) - float(observer_frame.x)
        dy = float(target_frame.y) - float(observer_frame.y)
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0
        target_angle = math.degrees(math.atan2(dy, dx))
        return _normalize_degrees(target_angle - float(observer_frame.yaw))

    def _has_line_of_sight(self, observer_frame: PlayerFrame | None, target_frame: PlayerFrame | None) -> bool | None:
        if self.visibility_checker is None or observer_frame is None or target_frame is None:
            return None
        observer_name = str(observer_frame.name)
        target_name = str(target_frame.name)
        first_name, second_name = sorted((observer_name, target_name))
        cache_key = (int(observer_frame.tick), first_name, second_name)
        profiler = self.visibility_profile
        request_source = self._los_request_source
        if profiler is not None:
            profiler.record_los_request(request_source, cache_key)
        if cache_key not in self._los_cache:
            if profiler is not None:
                profiler.los_cache_misses += 1
                profiler.los_cache_misses_by_source[request_source] += 1
            glue_started_at = time.perf_counter()
            start_anchor = self._visibility_anchor(observer_frame)
            end_anchor = self._visibility_anchor(target_frame)
            coordinate_key = tuple(round(value, 3) for value in (*start_anchor, *end_anchor))
            if profiler is not None:
                profiler.los_glue_seconds += time.perf_counter() - glue_started_at
                if coordinate_key in getattr(self, "_los_coordinate_keys", set()):
                    profiler.duplicate_los_coordinate_pairs += 1
                else:
                    profiler.unique_los_coordinate_pairs += 1
                self.__dict__.setdefault("_los_coordinate_keys", set()).add(coordinate_key)
                profiler.checker_is_visible_call_count += 1
                profiler.checker_calls_by_source[request_source] += 1
            los_started_at = time.perf_counter()
            self._los_cache[cache_key] = bool(
                self.visibility_checker.is_visible(
                    start_anchor,
                    end_anchor,
                )
            )
            if profiler is not None:
                profiler.record_los_call(time.perf_counter() - los_started_at)
        elif profiler is not None:
            profiler.los_cache_hits += 1
            profiler.los_cache_hits_by_source[request_source] += 1
        return self._los_cache[cache_key]

    def _visibility_anchor(self, frame: PlayerFrame) -> tuple[float, float, float]:
        return (float(frame.x), float(frame.y), float(frame.z) + EYE_HEIGHT_Z)
