# Viewer Decoupling Checklist

## Goal

Reduce the amount of game-state interpretation inside `src/wall/viewer/app.py`.

The target structure is:

- parse layer produces stable semantic tables
- domain layer turns raw tables into queryable timelines / state objects
- viewer consumes semantic queries and draws them

The viewer should gradually stop:

- directly inferring gameplay meaning from raw DataFrames
- duplicating rules that already belong to parse or domain
- depending on the internal layout of state segments

## Current Main Coupling Points

### 1. Bomb display still knows segment internals

Current state:

- viewer already uses `BombTimeline`
- but it still reads `BombState` fields like `state`, `x`, `y`, `start_tick`
- planted timer / dropped icon / carried icon logic still partially depends on bomb internals

Why it matters:

- if bomb-state construction changes, viewer can silently drift out of sync
- debugging "flashing bomb", "missing bomb", or "wrong carrier" becomes harder

Next steps:

- add `bomb_icon_state_at(tick)`
- add `planted_timer_progress_at(tick)`
- add `defuse_progress_at(tick)`
- add `drop_reason_at(tick)`
- move more icon-selection and timer-state decisions into `BombTimeline`

Priority:

- high

### 2. Sound presentation rules live in the viewer

Current state:

- viewer owns `SOUND_STYLE_BY_KIND`
- viewer decides circle suppression, display radius multipliers, alpha tweaks, and conflict resolution
- same-emitter "show only the larger circle" rule is a viewer rule

Why it matters:

- sound semantics and sound rendering rules are mixed together
- future changes to footsteps, landing, gunfire, grenade bounce, bomb sounds, or weapon-specific rules will keep making `app.py` fatter

Next steps:

- decide which parts stay purely visual and which belong to semantic data
- consider adding semantic columns to `sound_events`, for example:
  - `display_group`
  - `display_priority`
  - `suppress_lower_priority_same_emitter`
  - `display_radius_world`
- alternatively add a small `SoundTimeline` / `SoundPresentation` helper in domain

Priority:

- high

### 3. Grenade / smoke / inferno windows are assembled in the viewer

Current state:

- done:
  - `UtilityTimeline` already builds:
    - `grenade_trails`
    - `smoke_windows`
    - `flash_effects`
    - `he_effects`
    - `inferno_effects`
    - smoke-hole recovery data
- viewer still keeps a few compatibility aliases such as:
  - `self.grenade_trails`
  - `self.smoke_windows`
  - `self.flash_effects`
  - `self.he_effects`
  - `self.inferno_effects`
  - `self.smoke_holes_by_window`

Why it matters:

- this is already domain logic, not just drawing
- adding more utility semantics will make the viewer harder to maintain

Next steps:

- keep `UtilityTimeline` as the semantic owner
- gradually remove compatibility aliases from the viewer where they do not help readability
- if smoke-hole data grows more complex, consider replacing raw dict payloads with typed dataclasses
- keep viewer focused on:
  - position to pixel conversion
  - sprite selection
  - alpha / animation playback

Priority:

- mostly done

### 4. Viewer still receives many raw round tables

Current state:

- `RoundData` is mostly a bag of DataFrames
- viewer can always "reach around" domain objects and query raw tables directly

Why it matters:

- even after cleanup, new features will tend to reintroduce raw-table coupling
- architectural drift is likely unless the entrypoint gets narrower

Next steps:

- evolve `RoundData` toward semantic objects, for example:
  - `round_players`
  - `bomb_timeline`
  - `sound_timeline`
  - `utility_timeline`
- keep raw DataFrames only where they are still unavoidable

Priority:

- medium

### 5. Player rendering logic still contains mixed semantic decisions

Current state:

- `RoundPlayers` and `PlayerTimeline` already centralize much of the player state
- but viewer still combines some player-state rules with rendering decisions:
  - tracer timing
  - muzzle-flash timing
  - flash / damage overlay usage
  - some alive / team / state combinations

Why it matters:

- continued feature growth can push player-action interpretation back into `app.py`

Next steps:

- continue moving reusable state queries into `PlayerTimeline`
- keep pure rendering transforms in the viewer
- do not move cosmetic-only animation choices unless they need reuse

Priority:

- medium

## Recommended Order

### Phase 1: finish bomb cleanup

- add remaining bomb semantic helpers
- stop reading bomb segment fields directly in new viewer code
- prefer `drop_reason` / `pickup_source` semantic accessors

Expected benefit:

- better C4 stability
- easier debugging of pickup/drop/plant transitions

### Phase 2: utility timeline extraction

- move smoke / flash / HE / inferno time-window assembly out of the viewer
- keep current visuals unchanged where possible

Expected benefit:

- largest reduction in viewer complexity after bomb

Current status:

- completed for smoke / flash / HE / inferno / grenade trails / smoke-hole recovery
- remaining work is cleanup, not missing architecture

### Phase 3: sound presentation cleanup

- decide what belongs in parse/domain vs what remains view-only
- standardize suppression / grouping / presentation semantics

Expected benefit:

- easier iteration on sound circles without repeatedly touching `app.py`

### Phase 4: narrow viewer inputs

- progressively replace raw round tables with semantic objects

Expected benefit:

- prevents coupling from regrowing

## Low-Cost Wins

- avoid new direct DataFrame filtering in `app.py`
- when adding a gameplay rule, prefer parse/domain first
- if a viewer helper needs to know gameplay meaning, consider whether it belongs in domain instead
- when a state is already represented as a timeline, add a query method instead of exposing more internal fields

## Things Not Worth Over-Abstracting Yet

- purely cosmetic constants like icon padding, glow alpha, ring width
- one-off pixel offsets that are only about layout
- small draw helpers that do not encode gameplay rules

The goal is not "everything becomes an object".

The goal is:

- gameplay interpretation lives outside the viewer
- drawing stays inside the viewer
