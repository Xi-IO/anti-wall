from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

try:
    from awpy.visibility import VisibilityChecker
except ModuleNotFoundError:
    VisibilityChecker = None

from wall.domain.visibility_profile import VisibilityProfile
from wall.paths import awpy_tris_dir
from wall.profile import profile_log


_VISIBILITY_CHECKER_CACHE: dict[str, VisibilityChecker] = {}


def _count_bvh_nodes(root) -> tuple[int, int]:
    if root is None:
        return 0, 0
    node_count = 0
    leaf_count = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        node_count += 1
        triangle = getattr(node, "triangle", None)
        if triangle is not None:
            leaf_count += 1
        else:
            stack.append(getattr(node, "left", None))
            stack.append(getattr(node, "right", None))
    return node_count, leaf_count


def _visibility_checker_counts(checker, triangles: list | None = None) -> str:
    triangle_count = int(len(triangles)) if triangles is not None else int(getattr(checker, "n_triangles", 0) or 0)
    vertex_count = triangle_count * 3
    node_count, leaf_count = _count_bvh_nodes(getattr(checker, "root", None))
    polygon_count = triangle_count
    blocker_count = 0
    return (
        f"triangles={triangle_count} vertices={vertex_count} "
        f"blockers={blocker_count} polygons={polygon_count} index_nodes={node_count} leaf_nodes={leaf_count}"
    )


@dataclass(frozen=True)
class MapVisibilityContext:
    mode: str
    map_name: str | None
    tri_path: Path | None
    visibility_checker: VisibilityChecker | None
    visibility_artifact_path: Path | None = None

    @classmethod
    def precomputed(
        cls,
        map_name: str | None,
        *,
        visibility_artifact_path: Path | None,
    ) -> "MapVisibilityContext":
        profile_log(
            "visibility_context.mode",
            map_name=map_name,
            note=f"mode=precomputed artifact={visibility_artifact_path}",
        )
        return cls(
            mode="precomputed",
            map_name=map_name,
            tri_path=None,
            visibility_checker=None,
            visibility_artifact_path=visibility_artifact_path,
        )

    @classmethod
    def unavailable(cls, map_name: str | None) -> "MapVisibilityContext":
        profile_log(
            "visibility_context.mode",
            map_name=map_name,
            note="mode=unavailable",
        )
        return cls(
            mode="unavailable",
            map_name=map_name,
            tri_path=None,
            visibility_checker=None,
            visibility_artifact_path=None,
        )

    @classmethod
    def for_map(
        cls,
        map_name: str | None,
        *,
        visibility_profile: VisibilityProfile | None = None,
    ) -> "MapVisibilityContext":
        started_at = time.perf_counter()
        profile_log("visibility_context.mode", map_name=map_name, note="mode=geometry")
        profile_log("visibility_context.start", round_id=None, map_name=map_name)
        if not map_name or VisibilityChecker is None:
            context = cls(mode="geometry", map_name=map_name, tri_path=None, visibility_checker=None)
            profile_log("visibility_context.end", started_at=started_at, map_name=map_name, note="no map or checker")
            return context
        tri_path = awpy_tris_dir() / f"{map_name}.tri"
        if visibility_profile is not None:
            visibility_profile.checker_cache_key = str(tri_path)
        if not tri_path.exists():
            context = cls(mode="geometry", map_name=map_name, tri_path=tri_path, visibility_checker=None)
            profile_log("visibility_context.end", started_at=started_at, map_name=map_name, note="tri missing")
            return context
        cache_key = str(tri_path.resolve())
        if visibility_profile is not None:
            visibility_profile.checker_cache_key = cache_key
        cached = _VISIBILITY_CHECKER_CACHE.get(cache_key)
        if cached is not None:
            if visibility_profile is not None:
                visibility_profile.checker_cache_hits += 1
            context = cls(mode="geometry", map_name=map_name, tri_path=tri_path, visibility_checker=cached)
            profile_log(
                "visibility_geometry_cache.end",
                started_at=started_at,
                map_name=map_name,
                note=f"cache=reused key={cache_key} {_visibility_checker_counts(cached)}",
            )
            profile_log("visibility_context.end", started_at=started_at, map_name=map_name, note="cache hit")
            return context
        if visibility_profile is not None:
            visibility_profile.checker_cache_misses += 1
        checker_started_at = time.perf_counter()
        profile_log("visibility_geometry_cache.start", map_name=map_name, note=f"cache=new key={cache_key}")
        tri_read_started_at = time.perf_counter()
        profile_log("visibility_geometry_tri_file_read.start", map_name=map_name, note=str(tri_path))
        profile_log("visibility_geometry_awpy_parse.start", map_name=map_name, note=str(tri_path))
        triangles = VisibilityChecker.read_tri_file(Path(tri_path))
        profile_log(
            "visibility_geometry_awpy_parse.end",
            started_at=tri_read_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} triangles={len(triangles)} vertices={len(triangles) * 3}",
        )
        profile_log(
            "visibility_geometry_tri_file_read.end",
            started_at=tri_read_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} path={tri_path}",
        )
        profile_log(
            "visibility_geometry_raw_counts",
            map_name=map_name,
            note=f"cache=new key={cache_key} triangles={len(triangles)} vertices={len(triangles) * 3} blockers=0 polygons={len(triangles)} index_nodes=0",
        )
        bvh_started_at = time.perf_counter()
        profile_log("visibility_geometry_spatial_index_build.start", map_name=map_name, note=f"cache=new key={cache_key}")
        checker = VisibilityChecker.__new__(VisibilityChecker)
        checker.n_triangles = len(triangles)
        checker.root = checker._build_bvh(triangles)
        profile_log(
            "visibility_geometry_spatial_index_build.end",
            started_at=bvh_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} {_visibility_checker_counts(checker, triangles)}",
        )
        profile_log(
            "visibility_geometry_blocker_polygon_conversion.start",
            map_name=map_name,
            note=f"cache=new key={cache_key} unavailable_in_awpy_checker=true",
        )
        profile_log(
            "visibility_geometry_blocker_polygon_conversion.end",
            map_name=map_name,
            note=f"cache=new key={cache_key} unavailable_in_awpy_checker=true blockers=0 polygons={len(triangles)}",
        )
        if visibility_profile is not None:
            visibility_profile.checker_construction_seconds += time.perf_counter() - checker_started_at
            visibility_profile.checker_build_count += 1
        assignment_started_at = time.perf_counter()
        profile_log("visibility_geometry_cache_assignment.start", map_name=map_name, note=f"cache=new key={cache_key}")
        _VISIBILITY_CHECKER_CACHE[cache_key] = checker
        profile_log(
            "visibility_geometry_cache_assignment.end",
            started_at=assignment_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} {_visibility_checker_counts(checker, triangles)}",
        )
        cleanup_started_at = time.perf_counter()
        profile_log(
            "visibility_geometry_post_build_cleanup.start",
            map_name=map_name,
            note="dropping raw triangle list; no per-round/per-player/per-tick visibility cache retained",
        )
        del triangles
        profile_log(
            "visibility_geometry_post_build_cleanup.end",
            started_at=cleanup_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} raw_awpy_geometry_retained=false converted_geometry_retained=false spatial_index_retained=true debug_arrays_retained=false per_tick_cache_retained=false",
        )
        context = cls(mode="geometry", map_name=map_name, tri_path=tri_path, visibility_checker=checker)
        profile_log(
            "visibility_geometry_cache.end",
            started_at=checker_started_at,
            map_name=map_name,
            note=f"cache=new key={cache_key} {_visibility_checker_counts(checker)}",
        )
        profile_log("visibility_context.end", started_at=started_at, map_name=map_name)
        return context
