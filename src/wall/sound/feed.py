from __future__ import annotations

MOVEMENT_FEED_MERGE_GAP_TICKS = 32
MIN_MOVEMENT_FEED_DURATION_TICKS = 16
HARD_STEP_DEDUPE_WINDOW_TICKS = 64


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>"}:
        return ""
    return text


def is_sound_exposure_feed_candidate(*, sound_class: str, sound_action: str, raw_source: str) -> bool:
    normalized_class = _clean_text(sound_class)
    normalized_action = _clean_text(sound_action)
    _normalized_source = _clean_text(raw_source)
    if normalized_class == "movement" and normalized_action in {"locomotion", "hard_step"}:
        return True
    if normalized_class == "weapon" and normalized_action == "gunfire":
        return True
    if normalized_class == "bomb" and normalized_action in {
        "dropped",
        "begin_plant",
        "begin_defuse",
        "abort_defuse",
        "defused",
            "exploded",
    }:
        return True
    if normalized_class == "utility" and normalized_action in {
        "smoke_detonate",
        "flash_detonate",
        "he_detonate",
        "inferno_startburn",
    }:
        return True
    return False


def sound_feed_priority(*, sound_class: str, sound_action: str) -> int:
    _ = sound_action
    normalized_class = _clean_text(sound_class)
    return {
        "bomb": 0,
        "weapon": 1,
        "utility": 2,
        "damage": 3,
        "movement": 4,
    }.get(normalized_class, 5)


def format_sound_exposure_message(
    *,
    observer_label: str,
    source_label: str,
    sound_class: str,
    sound_action: str,
    item_name: str,
    shot_count: int | None,
    raw_source: str,
) -> str:
    listener = _clean_text(observer_label) or "observer"
    source = _clean_text(source_label)
    normalized_class = _clean_text(sound_class)
    normalized_action = _clean_text(sound_action)
    normalized_item = _clean_text(item_name)
    normalized_source = _clean_text(raw_source)
    if normalized_class == "movement" and normalized_action == "locomotion":
        return f"{listener} heard movement{f' from {source}' if source else ''}"
    if normalized_class == "movement" and normalized_action == "hard_step":
        return f"{listener} heard hard step{f' from {source}' if source else ''}"
    if normalized_class == "weapon" and normalized_action == "gunfire":
        if shot_count is not None and int(shot_count) > 1:
            descriptor = f"{int(shot_count)} {normalized_item} shots".strip()
        elif normalized_item:
            descriptor = f"{normalized_item} shot"
        else:
            descriptor = "gunfire"
        return f"{listener} heard {descriptor}{f' from {source}' if source else ''}"
    if normalized_class == "bomb":
        by_action = {
            "dropped": "heard bomb dropped",
            "begin_plant": "heard bomb plant start",
            "begin_defuse": "heard bomb defuse start",
            "abort_defuse": "heard defuse canceled",
            "defused": "heard bomb defused",
            "exploded": "heard bomb exploded",
        }
        phrase = by_action.get(normalized_action, "heard bomb audio")
        return f"{listener} {phrase}"
    if normalized_class == "utility":
        by_action = {
            "smoke_detonate": "heard smoke bloom",
            "flash_detonate": "heard flash detonate",
            "he_detonate": "heard HE detonate",
            "inferno_startburn": "heard fire start",
        }
        phrase = by_action.get(normalized_action)
        if phrase is None and normalized_item:
            phrase = f"heard {normalized_item} detonate"
        return f"{listener} {phrase or 'heard utility detonate'}"
    return f"{listener} heard {normalized_class or 'sound'}"
