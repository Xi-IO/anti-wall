from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def verbose_enabled() -> bool:
    return _env_truthy("WALL_VERBOSE")


def profile_enabled() -> bool:
    return _env_truthy("WALL_VIEWER_PROFILE")


def progress_enabled() -> bool:
    return verbose_enabled() or profile_enabled()


def status_enabled() -> bool:
    return verbose_enabled() or profile_enabled()


def print_status(message: str = "") -> None:
    if not status_enabled():
        return
    print(message, flush=True)


def print_milestone(message: str = "") -> None:
    print(message, flush=True)


@contextmanager
def applied_output_mode(*, verbose: bool = False, profile: bool = False) -> Iterator[None]:
    previous_verbose = os.environ.get("WALL_VERBOSE")
    previous_profile = os.environ.get("WALL_VIEWER_PROFILE")
    try:
        if verbose:
            os.environ["WALL_VERBOSE"] = "1"
        if profile:
            os.environ["WALL_VIEWER_PROFILE"] = "1"
        yield
    finally:
        if previous_verbose is None:
            os.environ.pop("WALL_VERBOSE", None)
        else:
            os.environ["WALL_VERBOSE"] = previous_verbose
        if previous_profile is None:
            os.environ.pop("WALL_VIEWER_PROFILE", None)
        else:
            os.environ["WALL_VIEWER_PROFILE"] = previous_profile
