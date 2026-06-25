from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from wall.dataset.rounds import RoundData, get_round_data, load_round_data
from wall.domain.visibility_profile import VisibilityProfile
from wall.visibility.context import MapVisibilityContext


@dataclass(frozen=True)
class MatchDataset:
    ticks: pd.DataFrame
    deaths: pd.DataFrame
    fires: pd.DataFrame
    hurts: pd.DataFrame
    hits: pd.DataFrame
    footsteps: pd.DataFrame
    smoke_detonates: pd.DataFrame
    flash_detonates: pd.DataFrame
    he_detonates: pd.DataFrame
    blinds: pd.DataFrame
    bomb_pickups: pd.DataFrame
    bomb_drops: pd.DataFrame
    bomb_begin_plants: pd.DataFrame
    bomb_plants: pd.DataFrame
    bomb_defuses: pd.DataFrame
    bomb_begin_defuses: pd.DataFrame
    bomb_abort_defuses: pd.DataFrame
    bomb_explodes: pd.DataFrame
    smoke_expires: pd.DataFrame
    inferno_starts: pd.DataFrame
    grenade_trajectory_segments: pd.DataFrame
    sound_events: pd.DataFrame
    inferred_rounds: pd.DataFrame
    metadata: dict

    @classmethod
    def from_data_dir(cls, data_dir: Path) -> "MatchDataset":
        return cls(*load_round_data(data_dir))

    @property
    def round_ids(self) -> list[int]:
        return sorted(self.inferred_rounds["inferred_round_id"].astype(int).tolist())

    @property
    def map_name(self) -> str | None:
        return self.metadata.get("derived", {}).get("map_name")

    def build_round_data(
        self,
        round_id: int,
        *,
        tickrate: float,
        visibility_profile: VisibilityProfile | None = None,
        map_visibility_context: MapVisibilityContext | None = None,
    ) -> RoundData:
        context = map_visibility_context or MapVisibilityContext.for_map(
            self.map_name,
            visibility_profile=visibility_profile,
        )
        return get_round_data(
            self.ticks,
            self.deaths,
            self.fires,
            self.hurts,
            self.hits,
            self.footsteps,
            self.smoke_detonates,
            self.flash_detonates,
            self.he_detonates,
            self.blinds,
            self.bomb_pickups,
            self.bomb_drops,
            self.bomb_begin_plants,
            self.bomb_plants,
            self.bomb_defuses,
            self.bomb_begin_defuses,
            self.bomb_abort_defuses,
            self.bomb_explodes,
            self.smoke_expires,
            self.inferno_starts,
            self.sound_events,
            self.inferred_rounds,
            round_id,
            tickrate=tickrate,
            map_name=self.map_name,
            visibility_profile=visibility_profile,
            visibility_checker=None if context is None else context.visibility_checker,
            grenade_trajectory_segments=self.grenade_trajectory_segments,
        )

    def build_demo_hud_numbers(self) -> dict[str, int]:
        if self.ticks.empty or "name" not in self.ticks.columns:
            return {}
        work = self.ticks[["tick", "name", "team_num"]].copy()
        work = work[work["name"].notna()].copy()
        work["team_num"] = pd.to_numeric(work["team_num"], errors="coerce")
        work = work[work["team_num"].isin([2, 3])].sort_values(["tick", "name"]).copy()
        first_seen = work.groupby("name", sort=False).first().reset_index()

        player_numbers: dict[str, int] = {}
        team_slots = {2: [1, 2, 3, 4, 5], 3: [6, 7, 8, 9, 10]}
        for team_num in (2, 3):
            team_rows = first_seen[first_seen["team_num"] == team_num].sort_values(["tick", "name"])
            for slot, player in zip(team_slots[team_num], team_rows["name"].tolist()):
                player_numbers[str(player)] = slot

        remaining_players = sorted(set(self.ticks["name"].dropna().astype(str)) - set(player_numbers))
        next_number = 11
        for player in remaining_players:
            player_numbers[player] = next_number
            next_number += 1
        return player_numbers
