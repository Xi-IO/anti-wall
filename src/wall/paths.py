from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def awpy_maps_dir() -> Path:
    return Path.home() / ".awpy" / "maps"


def resolve_asset_path(*parts: str) -> Path:
    return ASSETS_DIR.joinpath(*parts)


def dataset_dir_for_demo(demo_path: Path, output_root: Path | None = None) -> Path:
    root = output_root or DEFAULT_OUTPUTS_DIR
    return root / demo_path.stem


def looks_like_dataset_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    if (path / "metadata.json").exists():
        return True
    return any(path.glob("ticks.*")) and any(path.glob("inferred_rounds.*"))
