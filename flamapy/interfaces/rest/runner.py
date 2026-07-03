import multiprocessing
from typing import Any

from flamapy.core.exceptions import FlamaException
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel


class OperationTimeout(Exception):
    """The operation exceeded the configured time budget and was killed."""


class ModelParseError(Exception):
    """The uploaded model could not be parsed."""


def _execute(model_path: str, operation_name: str, kwargs: dict[str, Any]) -> Any:
    try:
        feature_model = FLAMAFeatureModel(model_path)
    except FlamaException as exc:
        raise ModelParseError(str(exc)) from exc
    return getattr(feature_model, operation_name)(**kwargs)


def _child(conn: Any, model_path: str, operation_name: str, kwargs: dict[str, Any]) -> None:
    try:
        conn.send(('ok', _execute(model_path, operation_name, kwargs)))
    except ModelParseError as exc:
        conn.send(('parse_error', str(exc)))
    except Exception as exc:  # pylint: disable=broad-except
        conn.send(('error', str(exc)))
    finally:
        conn.close()


def run_operation(
    model_path: str, operation_name: str, kwargs: dict[str, Any], timeout: int
) -> Any:
    """Run parse + operation, enforcing ``timeout`` seconds by executing in a
    forked child process — solver code is CPU-bound C that threads or signals
    cannot reliably interrupt, but a child process can always be killed.

    A timeout of 0 disables the budget and runs the operation inline.
    """
    if timeout <= 0:
        return _execute(model_path, operation_name, kwargs)

    ctx = multiprocessing.get_context('fork')
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_child, args=(child_conn, model_path, operation_name, kwargs)
    )
    process.start()
    child_conn.close()
    try:
        if not parent_conn.poll(timeout):
            raise OperationTimeout(
                f"Operation '{operation_name}' exceeded the {timeout}s time limit"
            )
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
