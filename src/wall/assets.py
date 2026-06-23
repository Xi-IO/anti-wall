from __future__ import annotations

from dataclasses import dataclass
import shutil
import sys
from pathlib import Path
import zipfile

from awpy.data import CURRENT_BUILD_ID
import requests

from wall.paths import awpy_data_dir, awpy_maps_dir, awpy_navs_dir, awpy_tris_dir


ARTIFACT_TYPES = ("maps", "navs", "tris")
FEATURE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "viewer": ("maps",),
    "visibility": ("maps", "tris"),
    "analysis": ("maps", "navs", "tris"),
}
ARTIFACT_URL_TEMPLATE = "https://awpycs.com/{patch}/{artifact}.zip"


class AssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetStatus:
    artifact: str
    present: bool
    path: Path
    detail: str


def artifact_dir(artifact: str) -> Path:
    if artifact == "maps":
        return awpy_maps_dir()
    if artifact == "navs":
        return awpy_navs_dir()
    if artifact == "tris":
        return awpy_tris_dir()
    raise ValueError(f"Unsupported artifact type: {artifact}")


def asset_root_dir() -> Path:
    return awpy_data_dir()


def required_artifacts_for_feature(feature: str) -> tuple[str, ...]:
    try:
        return FEATURE_ARTIFACTS[feature]
    except KeyError as exc:
        supported = ", ".join(sorted(FEATURE_ARTIFACTS))
        raise ValueError(f"Unsupported feature '{feature}'. Expected one of: {supported}") from exc


def map_asset_path(map_name: str, artifact: str) -> Path:
    suffix = ".png" if artifact == "maps" else f".{artifact[:-1]}"
    return artifact_dir(artifact) / f"{map_name}{suffix}"


def artifact_status(artifact: str, map_name: str | None = None) -> AssetStatus:
    directory = artifact_dir(artifact)
    if map_name:
        path = map_asset_path(map_name, artifact)
        present = path.exists()
        detail = f"map asset for {map_name}"
    else:
        path = directory
        present = directory.exists() and any(directory.iterdir())
        detail = "artifact directory"
    return AssetStatus(artifact=artifact, present=present, path=path, detail=detail)


def collect_missing_artifacts(artifacts: tuple[str, ...], map_name: str | None = None) -> list[AssetStatus]:
    return [status for artifact in artifacts if not (status := artifact_status(artifact, map_name)).present]


def prompt_download(missing: list[AssetStatus], *, feature: str | None, map_name: str | None) -> bool:
    subject = f" for map '{map_name}'" if map_name else ""
    scope = f" for {feature}" if feature else ""
    print(f"Missing Awpy assets{scope}{subject}:")
    for status in missing:
        print(f"  - {status.artifact}: {status.path}")
    sys.stdout.flush()
    while True:
        answer = input("Download them now? [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def ensure_asset_dirs() -> None:
    asset_root_dir().mkdir(parents=True, exist_ok=True)


def download_artifact(artifact: str, *, patch: int = CURRENT_BUILD_ID) -> None:
    ensure_asset_dirs()
    target_dir = artifact_dir(artifact)
    target_dir.mkdir(parents=True, exist_ok=True)
    zip_path = target_dir / f"{artifact}.zip"
    url = ARTIFACT_URL_TEMPLATE.format(patch=patch, artifact=artifact)
    print(f"Downloading {artifact} from {url}")
    response: requests.Response | None = None
    try:
        response = requests.get(
            url,
            stream=True,
            timeout=300,
            headers={"User-Agent": "wall/0.1.0 (+https://github.com/pnxenopoulos/awpy)"},
        )
        if not response.ok:
            raise AssetError(f"Failed to download {url}: HTTP {response.status_code}")
        with open(zip_path, "wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output_file.write(chunk)
    except requests.RequestException as exc:
        raise AssetError(f"Failed to download {url}: {exc}") from exc
    finally:
        if response is not None:
            response.close()
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise AssetError(f"Downloaded file for {artifact} is not a valid zip archive: {zip_path}") from exc
    finally:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except PermissionError:
                pass
    (target_dir / ".patch").write_text(str(patch), encoding="utf-8")


def ensure_artifacts(
    artifacts: tuple[str, ...],
    *,
    map_name: str | None = None,
    feature: str | None = None,
    prompt: bool = True,
) -> bool:
    missing = collect_missing_artifacts(artifacts, map_name)
    if not missing:
        return True
    if not prompt:
        return False
    if not sys.stdin.isatty():
        raise AssetError(
            "Required Awpy assets are missing and interactive download is unavailable. "
            "Run 'wall assets init' first."
        )
    if not prompt_download(missing, feature=feature, map_name=map_name):
        return False
    for status in missing:
        download_artifact(status.artifact)
    return not collect_missing_artifacts(artifacts, map_name)


def check_or_raise_for_feature(
    feature: str,
    *,
    map_name: str | None = None,
    prompt: bool = True,
) -> None:
    artifacts = required_artifacts_for_feature(feature)
    if ensure_artifacts(artifacts, map_name=map_name, feature=feature, prompt=prompt):
        return
    missing = collect_missing_artifacts(artifacts, map_name)
    details = ", ".join(f"{status.artifact} ({status.path})" for status in missing)
    raise AssetError(f"Missing Awpy assets for {feature}: {details}")
