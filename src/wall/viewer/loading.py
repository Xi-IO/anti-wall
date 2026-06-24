from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Literal, TypeVar

from wall.dataset.index import DatasetIndex
from wall.profile import profile_log


T = TypeVar("T")


@dataclass(frozen=True)
class ViewerLoadResult(Generic[T]):
    status: Literal["loading", "complete", "failed"]
    value: T | None = None
    error: BaseException | None = None


@dataclass(frozen=True)
class ViewerLoadState(Generic[T]):
    status: Literal["not_started", "loading", "complete", "failed"]
    value: T | None = None
    error: BaseException | None = None


class ViewerDatasetLoader:
    def __init__(
        self,
        data_dir: Path,
        *,
        load_fn: Callable[[Path], DatasetIndex] = DatasetIndex.from_data_dir,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.load_fn = load_fn
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future[DatasetIndex] | None = None
        self.state: ViewerLoadState[DatasetIndex] = ViewerLoadState(status="not_started")

    def start(self) -> ViewerLoadState[DatasetIndex]:
        if self._future is not None:
            return self.state
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wall-viewer-load")
        self._future = self._executor.submit(self.load_fn, self.data_dir)
        self.state = ViewerLoadState(status="loading")
        profile_log("viewer.load_started", note=str(self.data_dir))
        return self.state

    def poll(self) -> ViewerLoadState[DatasetIndex]:
        if self._future is None:
            return self.state
        if not self._future.done():
            return self.state
        if self.state.status in {"complete", "failed"}:
            return self.state
        try:
            loaded = self._future.result()
        except BaseException as exc:
            self.state = ViewerLoadState(status="failed", error=exc)
            profile_log("viewer.load_failed", note=type(exc).__name__)
            return self.state
        self.state = ViewerLoadState(status="complete", value=loaded)
        profile_log("viewer.load_complete", note=str(self.data_dir))
        return self.state

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
