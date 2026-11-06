import multiprocessing
from typing import Any, Callable, Optional

from flamapy.core.exceptions import FlamaException
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel


class OperationTimeout(Exception):
    """The operation exceeded the configured time budget and was killed."""


class ModelParseError(Exception):
    """The uploaded model could not be parsed."""


# What an operation run hands back: the bare value, plus the provenance of the result
# (``FLAMAFeatureModel.last_result`` as a dict without the value: plugin, backend, exact,
# planner rationale, wall time, model hash), or None when the facade recorded none.
Outcome = tuple[Any, Optional[dict[str, Any]]]


def _load(model_path: str) -> FLAMAFeatureModel:
    try:
        # raise_errors: a failing operation raises its FlamaException (the 3.0 contract)
        # instead of returning None, so the API can report the reason.
        return FLAMAFeatureModel(model_path, raise_errors=True)
    except FlamaException as exc:
        raise ModelParseError(str(exc)) from exc


def _execute(model_path: Optional[str], operation_name: str, kwargs: dict[str, Any]) -> Outcome:
    if model_path is None:
        # A producer (generate_random_feature_model): a static facade method, no model.
        return getattr(FLAMAFeatureModel, operation_name)(**kwargs), None
    feature_model = _load(model_path)
    value = getattr(feature_model, operation_name)(**kwargs)
    envelope = feature_model.last_result
    if envelope is None:
        return value, None
    provenance = envelope.to_dict()
    provenance.pop('value', None)
    return value, provenance


def _plan(model_path: str, operation_name: str,
          allow_approximate: Optional[bool]) -> dict[str, Any]:
    feature_model = _load(model_path)
    chosen = feature_model.plan(operation_name, allow_approximate)
    source = feature_model.fm_model.get_extension()
    return {
        'operation': operation_name,
        'plugin': chosen.plugin_name,
        'backend': chosen.target_extension,
        'transformation_chain': [source, *(dst for _, dst in chosen.transformation_chain)],
        'estimated_cost_ms': chosen.estimated_cost,
        'rationale': chosen.rationale,
        'alternatives': list(chosen.alternatives),
    }


def _child(conn: Any, task: Callable[..., Any], args: tuple[Any, ...]) -> None:
    try:
        conn.send(('ok', task(*args)))
    except ModelParseError as exc:
        conn.send(('parse_error', str(exc)))
    except Exception as exc:  # pylint: disable=broad-except
        conn.send(('error', str(exc)))
    finally:
        conn.close()


def _run_in_child(task: Callable[..., Any], args: tuple[Any, ...], timeout: int,
                  label: str) -> Any:
    """Run ``task(*args)`` enforcing ``timeout`` seconds by executing it in a forked child
    process: solver code is CPU-bound C that threads or signals cannot reliably interrupt,
    but a child process can always be killed. A timeout of 0 runs the task inline.

    Errors come back as :class:`ModelParseError` or :class:`FlamaException` (its message)."""
    if timeout <= 0:
        return task(*args)

    ctx = multiprocessing.get_context('fork')
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(child_conn, task, args))
    process.start()
    child_conn.close()
    try:
        if not parent_conn.poll(timeout):
            raise OperationTimeout(f"Operation '{label}' exceeded the {timeout}s time limit")
        status, payload = parent_conn.recv()
    finally:
        if process.is_alive():
            process.terminate()
        process.join()
        parent_conn.close()

    if status == 'parse_error':
        raise ModelParseError(payload)
    if status == 'error':
        raise FlamaException(payload)
    return payload


def run_operation(
    model_path: Optional[str], operation_name: str, kwargs: dict[str, Any], timeout: int
) -> Outcome:
    """Parse the model (none for a producer) and run the operation under the time budget;
    returns the value and its provenance."""
    result: Outcome = _run_in_child(
        _execute, (model_path, operation_name, kwargs), timeout, operation_name)
    return result


def run_plan(
    model_path: str, operation_name: str, allow_approximate: Optional[bool], timeout: int
) -> dict[str, Any]:
    """Parse the model and ask the query planner which backend would run the operation."""
    chosen: dict[str, Any] = _run_in_child(
        _plan, (model_path, operation_name, allow_approximate), timeout, operation_name)
    return chosen
