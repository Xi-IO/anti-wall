# Viewer Decoupling Checklist

## Goal

Reduce the amount of game-state interpretation inside the active viewer stack under `src/wall/viewer/`.

The target structure is:

- parse layer produces stable semantic tables
- domain layer turns raw tables into queryable timelines / state objects
- viewer consumes semantic queries and draws them

The viewer should gradually stop:

- directly inferring gameplay meaning from raw DataFrames
- duplicating rules that already belong to parse or domain
- depending on the internal layout of state segments

Current viewer module split:

- `viewer/cli.py`: startup entrypoint
- `viewer/shell.py`: event loop, playback orchestration, sidebar / timeline coordination
- `viewer/runtime.py`: round switching and frame-cache lifecycle
- `viewer/state.py`: interaction state
- `viewer/layout.py` and `viewer/ui.py`: dropdown / sidebar / bottom-bar layout and drawing
- `viewer/renderer.py`: round-frame render coordinator
- `viewer/render_player.py`: player body / label / tracer / muzzle-flash drawing
- `viewer/render_sound.py`: sound-ring drawing
- `viewer/render_bomb.py`: bomb and defuse visuals
- `viewer/render_utility.py`: smoke / flash / HE / inferno visuals
- `viewer/render_config.py`: viewer-only render constants

## Current Main Coupling Points

### 1. Bomb display still knows segment internals

Current state:

- `BombTimeline.render_state_at(...)` is now the main semantic entrypoint for bomb visuals
- viewer-side bomb drawing has been split into `viewer/render_bomb.py`
- active viewer code no longer reopens raw bomb segments to decide icon state, plant visuals, or defuse visuals

Why it matters:

- bomb semantics and bomb visuals are now much less coupled
- the remaining risk is mostly accidental bypasses in future code, not the current path

Next steps:

- keep new bomb-state queries inside `BombTimeline`
- avoid reintroducing direct segment inspection in viewer helpers
- only widen `BombRenderState` if a new visual really needs new semantic data

Priority:

- completed for the active path

### 2. Sound presentation rules live in the viewer

Current state:

- `SoundTimeline` now owns:
  - sound style metadata
  - suppression / grouping rules
  - capped-label decisions
  - per-frame sound presentation queries
- viewer-side sound drawing has been split into `viewer/render_sound.py`
- the viewer now mostly owns only pure draw concerns such as cached ring surfaces and pixel offsets

Why it matters:

- the main sound-coupling risk has been removed from the active viewer path
- future work should keep semantic changes in parse/domain and leave `render_sound.py` cosmetic-only

Next steps:

- keep adding gameplay meaning in parse/domain first
- only add render-module parameters for cosmetic choices
- avoid moving suppression or grouping logic back into the viewer

Priority:

- completed for the active path

### 3. Grenade / smoke / inferno windows are assembled in the viewer

Current state:

- `UtilityTimeline` is the semantic owner for grenade trails, smoke windows, flashes, HE bursts, infernos, and smoke-hole recovery
- viewer-side utility drawing has been split into `viewer/render_utility.py`
- the active viewer path no longer keeps the old compatibility aliases around as primary state

Why it matters:

- utility semantics are now mostly separated from utility drawing
- the main remaining risk is future feature code bypassing `UtilityTimeline`

Next steps:

- keep `UtilityTimeline` as the semantic owner
- keep `render_utility.py` focused on sprite selection, alpha, and animation playback
- if new utility effects appear, extend timeline queries before adding viewer-side state

Priority:

- completed for the active path

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

- `RoundPlayers` and `PlayerTimeline` centralize most player state queries
- pure player drawing has been split into `viewer/render_player.py`
- `renderer.py` still coordinates a few semantic-to-visual decisions:
  - choosing alive vs death-marker path
  - deriving tracer hit targets from player timelines
  - mapping overlay state into final player tinting

Why it matters:

- continued feature growth can push player-action interpretation back into `renderer.py`

Next steps:

- continue moving reusable state queries into `PlayerTimeline`
- keep pure rendering transforms in the viewer
- do not move cosmetic-only animation choices unless they need reuse

Priority:

- mostly done

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
- viewer no longer reads grenade-trail `DataFrame` payloads directly
- smoke-hole payloads are now typed domain objects instead of raw dicts
- remaining work is cleanup, not missing architecture

### Phase 3: sound presentation cleanup

- decide what belongs in parse/domain vs what remains view-only
- standardize suppression / grouping / presentation semantics

Expected benefit:

- easier iteration on sound circles without repeatedly touching the main render coordinator

Current status:

- mostly completed
- `SoundTimeline` now owns:
  - sound style metadata
  - suppression / grouping rules
  - capped-label decisions
  - per-frame sound presentation queries
- parse now deduplicates short `grenade_bounce` bursts before the viewer sees them
- viewer still owns a small set of pure drawing constants such as:
  - ring surface fill math
  - label pixel offset
  - cached surface reuse

Important note:

- gameplay meaning for sound should now be added in parse/domain first
- `renderer.py` should only consume `SoundTimeline.present_events_at(...)` results for sound drawing

### Phase 4: narrow viewer inputs

- progressively replace raw round tables with semantic objects

Expected benefit:

- prevents coupling from regrowing

Current status:

- completed for the current viewer path
- `RoundData` now carries semantic viewer inputs such as:
  - `round_players`
  - `utility_timeline`
  - `bomb_timeline`
  - `sound_timeline`
  - `frame_ticks`
  - `round_start_tick`
- `PygameRoundRenderer` now consumes `RoundData` directly instead of receiving a long list of round tables
- viewer utility rendering now prefers `UtilityTimeline` query methods over reopening utility internals
- unused legacy `RoundRenderer` code has been removed from the active rendering path
- the previous mixed `viewer/app.py` implementation has been split so the active path now runs through:
  - `viewer/cli.py`
  - `viewer/shell.py`
  - `viewer/renderer.py`
  - specialized render helpers for player / sound / bomb / utility visuals

Important note:

- when adding new viewer features, prefer extending `RoundData` with semantic objects first
- avoid widening `PygameRoundRenderer(...)` back into another long raw-table parameter list

### Phase 4 cleanup status

- renderer-only helpers are now split by responsibility:
  - player visuals
  - sound visuals
  - bomb visuals
  - utility-effect visuals
- the old `viewer/app.py` path has been fully retired after downstream imports were updated
- remaining work is mostly:
  - documentation and naming cleanup
  - selective unit coverage for pure helper modules

## Low-Cost Wins

- avoid new direct DataFrame filtering in `renderer.py` or `shell.py`
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
