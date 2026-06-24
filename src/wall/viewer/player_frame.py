from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from wall.domain.player import PlayerTimeline, RoundPlayers


@dataclass(frozen=True, slots=True)
class PlayerDeathPresentation:
    world_position: tuple[float, float]
    label: str


@dataclass(frozen=True, slots=True)
class PlayerTracerPresentation:
    yaw: float
    team_num: int | None
    hit_position_world: tuple[float, float] | None
    flash_fade: float


@dataclass(frozen=True, slots=True)
class PlayerFramePresentation:
    player: str
    player_number: int
    base_color: tuple[int, int, int]
    draw_color: tuple[int, int, int]
    world_position: tuple[float, float]
    yaw: float
    team_num: int | None
    health: int | None
    blind_strength: float
    weapon_name: str
    tail_world_points: tuple[tuple[float, float], ...]
    death: PlayerDeathPresentation | None
    tracer: PlayerTracerPresentation | None
    is_alive: bool


def _mix_with_white(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round((1.0 - amount) * channel + amount * 255)) for channel in color)


def assemble_player_frame_presentation(
    *,
    player: str,
    player_number: int,
    frame_tick: int,
    timeline: PlayerTimeline,
    round_players: RoundPlayers,
    round_start_tick: int,
    trail: int,
    damage_flash_duration_ticks: int,
    fire_flash_duration_ticks: int,
    hit_match_window_ticks: int,
    base_color: tuple[int, int, int],
) -> PlayerFramePresentation | None:
    current = timeline.frame_at(frame_tick)
    if current is None:
        return None
    overlay_state = timeline.overlay_state_at(frame_tick, damage_flash_duration_ticks=damage_flash_duration_ticks)
    draw_color = _resolve_player_color(base_color, overlay_state.damage_flash_fade, overlay_state.blind_strength)
    tail = timeline.frames_between(max(round_start_tick, frame_tick - trail + 1), frame_tick)
    tail_world_points = tuple((float(row.X), float(row.Y)) for row in tail.itertuples())
    death = _death_presentation(player=player, frame_tick=frame_tick, timeline=timeline)
    tracer = _tracer_presentation(
        frame_tick=frame_tick,
        timeline=timeline,
        round_players=round_players,
        fire_flash_duration_ticks=fire_flash_duration_ticks,
        hit_match_window_ticks=hit_match_window_ticks,
    )
    is_alive = timeline.is_alive_at(frame_tick)
    return PlayerFramePresentation(
        player=player,
        player_number=player_number,
        base_color=base_color,
        draw_color=draw_color,
        world_position=(float(current.x), float(current.y)),
        yaw=float(current.yaw),
        team_num=current.team_num,
        health=current.health,
        blind_strength=overlay_state.blind_strength,
        weapon_name=current.active_weapon_name,
        tail_world_points=tail_world_points,
        death=death,
        tracer=tracer,
        is_alive=is_alive,
    )


def _resolve_player_color(
    base_color: tuple[int, int, int],
    damage_flash_fade: float,
    blind_strength: float,
) -> tuple[int, int, int]:
    color = base_color
    if damage_flash_fade > 0.0:
        color = tuple(
            int(round((1.0 - damage_flash_fade) * base_channel + damage_flash_fade * overlay_channel))
            for base_channel, overlay_channel in zip(color, (220, 48, 48))
        )
    if blind_strength > 0.0:
        color = _mix_with_white(color, blind_strength * 0.88)
    return color


def _death_presentation(
    *,
    player: str,
    frame_tick: int,
    timeline: PlayerTimeline,
) -> PlayerDeathPresentation | None:
    position = timeline.death_position_at(frame_tick)
    if position is None:
        return None
    return PlayerDeathPresentation(
        world_position=(float(position[0]), float(position[1])),
        label=player,
    )


def _tracer_presentation(
    *,
    frame_tick: int,
    timeline: PlayerTimeline,
    round_players: RoundPlayers,
    fire_flash_duration_ticks: int,
    hit_match_window_ticks: int,
) -> PlayerTracerPresentation | None:
    fire_event = timeline.latest_fire_event(frame_tick)
    if fire_event is None:
        return None
    fire_tick = int(fire_event["tick"])
    elapsed = frame_tick - fire_tick
    if elapsed < 0 or elapsed > fire_flash_duration_ticks:
        return None
    return PlayerTracerPresentation(
        yaw=float(timeline.frame_at(frame_tick).yaw),
        team_num=_coerce_team_num(fire_event),
        hit_position_world=_resolve_hit_point(
            fire_event=fire_event,
            round_players=round_players,
            hit_match_window_ticks=hit_match_window_ticks,
        ),
        flash_fade=1.0 - (elapsed / fire_flash_duration_ticks),
    )


def _resolve_hit_point(
    *,
    fire_event: pd.Series,
    round_players: RoundPlayers,
    hit_match_window_ticks: int,
) -> tuple[float, float] | None:
    attacker_timeline = round_players.get_by_steamid(str(fire_event.get("user_steamid", "")).strip())
    if attacker_timeline is None:
        attacker_timeline = round_players.get_by_name(str(fire_event.get("user_name", "")))
    if attacker_timeline is None:
        return None
    return attacker_timeline.resolve_hit_position_for_fire_event(
        fire_event,
        max_tick=int(fire_event["tick"]) + hit_match_window_ticks,
        victim_position_lookup=lambda hurt_event: _extract_hurt_world_xy(hurt_event=hurt_event, round_players=round_players),
    )


def _extract_hurt_world_xy(
    *,
    hurt_event: pd.Series,
    round_players: RoundPlayers,
) -> tuple[float, float] | None:
    victim_name = hurt_event.get("user_name")
    if pd.isna(victim_name):
        return None
    hurt_tick = int(hurt_event["tick"])
    frame = round_players.frame_at(name=str(victim_name), tick=hurt_tick)
    if frame is None:
        return None
    return (float(frame.x), float(frame.y))


def _coerce_team_num(fire_event: pd.Series) -> int | None:
    numeric = pd.to_numeric(fire_event.get("team_num"), errors="coerce")
    if pd.isna(numeric):
        return None
    return int(numeric)
