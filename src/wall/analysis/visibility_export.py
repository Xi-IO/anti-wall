from wall.visibility import export as _impl

ProcessPoolExecutor = _impl.ProcessPoolExecutor
as_completed = _impl.as_completed
VisibilityResultRow = _impl.VisibilityResultRow
VisibilityResultSet = _impl.VisibilityResultSet
VisibilityExportResult = _impl.VisibilityExportResult
VisibilityBatchRoundResult = _impl.VisibilityBatchRoundResult
VisibilityBatchExportResult = _impl.VisibilityBatchExportResult
LosOverlapResult = _impl.LosOverlapResult


def _sync_impl_globals() -> None:
    _impl.ProcessPoolExecutor = ProcessPoolExecutor
    _impl.as_completed = as_completed


def _result_rows_to_pair_table(*args, **kwargs):
    return _impl._result_rows_to_pair_table(*args, **kwargs)


def _result_rows_to_summary_table(*args, **kwargs):
    return _impl._result_rows_to_summary_table(*args, **kwargs)


def build_visibility_result_set(*args, **kwargs):
    return _impl.build_visibility_result_set(*args, **kwargs)


def build_visibility_table(*args, **kwargs):
    return _impl.build_visibility_table(*args, **kwargs)


def build_visibility_summary_table(*args, **kwargs):
    return _impl.build_visibility_summary_table(*args, **kwargs)


def run_visibility_export(*args, **kwargs):
    _sync_impl_globals()
    if "loaded_data" in kwargs and "dataset" not in kwargs:
        kwargs["dataset"] = kwargs.pop("loaded_data")
    return _impl.run_visibility_export(*args, **kwargs)


def run_visibility_exports(*args, **kwargs):
    _sync_impl_globals()
    if "loaded_data" in kwargs and "dataset" not in kwargs:
        kwargs["dataset"] = kwargs.pop("loaded_data")
    return _impl.run_visibility_exports(*args, **kwargs)


def export_visibility_table(*args, **kwargs):
    _sync_impl_globals()
    return _impl.export_visibility_table(*args, **kwargs)


def profile_los_overlap(*args, **kwargs):
    _sync_impl_globals()
    if "loaded_data" in kwargs and "dataset" not in kwargs:
        kwargs["dataset"] = kwargs.pop("loaded_data")
    return _impl.profile_los_overlap(*args, **kwargs)
