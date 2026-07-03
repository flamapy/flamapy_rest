import os
import hashlib
import inspect
import json
import shutil
import tempfile
import typing
from typing import Any, Callable

from flask import Blueprint, Response, current_app, request, jsonify, abort
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel, Backend
from flamapy.metamodels.configuration_metamodel.models import Configuration

from flamapy.interfaces.rest.extensions import (
    limiter,
    result_cache,
    default_operation_limit,
    expensive_operation_limit,
)
from flamapy.interfaces.rest.runner import ModelParseError, OperationTimeout, run_operation


operations_bp = Blueprint('operations_bp', __name__, url_prefix='/api/v1/operations')

# Operations that enumerate or repeatedly invoke a solver; they get the stricter
# rate-limit tier because a single call can monopolize a CPU for a long time.
_EXPENSIVE_OPERATIONS = {
    'configurations',
    'configurations_number',
    'configurations_with_n_features',
    'conflict',
    'diagnosis',
    'feature_inclusion_probability',
    'homogeneity',
    'product_distribution',
    'sampling',
    'unique_features',
    'variability',
    'variant_features',
}

# Backward-compatible multipart field names for parameters that the API exposed
# before the dispatcher became generic. Any other parameter derives its field
# name from the parameter itself (file params drop the trailing "_path").
_LEGACY_FIELD = {
    'feature_name': 'feature',
}

# Parameters with a constrained set of values, surfaced as a Swagger enum so the
# UI offers a dropdown instead of a free-text field.
_ENUM_VALUES = {
    'backend': [b.value for b in Backend],
}

_SWAGGER_TYPES = {int: 'integer', float: 'number', bool: 'boolean', str: 'string'}


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Configuration):
            return obj.__dict__
        return super().default(obj)


def _operation_params(method: Any) -> list[inspect.Parameter]:
    """Call-relevant parameters of a facade method (excluding ``self``)."""
    return [p for p in inspect.signature(method).parameters.values() if p.name != 'self']


def _is_file_param(param: inspect.Parameter) -> bool:
    """Parameters whose value is a path are supplied as uploaded files."""
    return param.name.endswith('_path')


def _field_name(param: inspect.Parameter) -> str:
    """The multipart field name a client sends for this parameter."""
    if _is_file_param(param):
        return param.name[: -len('_path')]      # configuration_path -> configuration
    return _LEGACY_FIELD.get(param.name, param.name)


def _scalar_type(annotation: Any) -> type:
    """Resolve the scalar type of a (possibly ``Optional[...]``) annotation."""
    if annotation is inspect.Parameter.empty:
        return str
    if typing.get_origin(annotation) is typing.Union:
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        annotation = non_none[0] if non_none else str
    return annotation if annotation in (int, float, bool, str) else str


def _convert(raw: str, scalar_type: type) -> Any:
    if scalar_type is bool:
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    if scalar_type is int:
        return int(raw)
    if scalar_type is float:
        return float(raw)
    return raw


def _save_upload(uploaded: FileStorage, work_dir: str) -> str:
    """Save an uploaded file into ``work_dir`` under a sanitized name and return
    its path. ``secure_filename`` strips any directory components, so a client
    cannot escape ``work_dir`` via crafted names like ``../../etc/passwd``."""
    filename = secure_filename(uploaded.filename or '')
    if not filename:
        abort(400, "Uploaded file has an invalid name")
    path = os.path.join(work_dir, filename)
    uploaded.save(path)
    return path


def _resolve_kwargs(operation: Any, work_dir: str) -> dict[str, Any]:
    """Build the keyword arguments for a facade method from the request, saving
    any uploaded files into ``work_dir``."""
    kwargs: dict[str, Any] = {}
    for param in _operation_params(operation):
        field = _field_name(param)
        required = param.default is inspect.Parameter.empty
        if _is_file_param(param):
            uploaded = request.files.get(field)
            if uploaded is not None and uploaded.filename:
                kwargs[param.name] = _save_upload(uploaded, work_dir)
            elif required:
                abort(400, f"Missing required file '{field}'")
        else:
            raw = request.form.get(field)
            if raw is not None and raw != '':
                allowed = _ENUM_VALUES.get(param.name)
                if allowed is not None and raw not in allowed:
                    abort(400, f"Invalid value for '{field}'; choose from {allowed}")
                try:
                    kwargs[param.name] = _convert(raw, _scalar_type(param.annotation))
                except (TypeError, ValueError):
                    abort(400, f"Invalid value for '{field}'")
            elif required:
                abort(400, f"Missing required parameter '{field}'")
    return kwargs


def _cache_key(
    operation_name: str, operation: Any, model_path: str, kwargs: dict[str, Any]
) -> str:
    """Digest of everything that determines the result: the operation, the model
    contents and every argument (file arguments by content, not by temp path)."""
    file_params = {p.name for p in _operation_params(operation) if _is_file_param(p)}
    digest = hashlib.sha256()
    digest.update(operation_name.encode())
    with open(model_path, 'rb') as model_file:
        digest.update(model_file.read())
    for name in sorted(kwargs):
        digest.update(b'\x00' + name.encode() + b'\x00')
        if name in file_params:
            with open(kwargs[name], 'rb') as uploaded_file:
                digest.update(uploaded_file.read())
        else:
            digest.update(repr(kwargs[name]).encode())
    return digest.hexdigest()


def _api_call(operation_name: str) -> Any:
    uploaded_model = request.files.get('model')
    if uploaded_model is None or not uploaded_model.filename:
        abort(400, "Missing required file 'model'")

    # Each request gets its own directory so concurrent requests cannot collide
    # on (or delete) each other's uploads; the whole tree is removed afterwards.
    work_dir = tempfile.mkdtemp(prefix='flamapy_')
    try:
        model_path = _save_upload(uploaded_model, work_dir)
        operation = getattr(FLAMAFeatureModel, operation_name)
        kwargs = _resolve_kwargs(operation, work_dir)

        key = _cache_key(operation_name, operation, model_path, kwargs)
        payload = result_cache.get(key)
        if payload is not None:
            response: Response = jsonify(payload)
            response.headers['X-Cache'] = 'HIT'
            return response

        try:
            result = run_operation(
                model_path, operation_name, kwargs, current_app.config['OPERATION_TIMEOUT']
            )
        except ModelParseError:
            abort(400, "The uploaded model could not be parsed")
        except OperationTimeout as exc:
            abort(504, str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if result is None:
        return jsonify(error='Not valid result'), 404
    payload = json.loads(json.dumps(result, cls=CustomJSONEncoder))
    result_cache.set(key, payload)
    response = jsonify(payload)
    response.headers['X-Cache'] = 'MISS'
    return response


def extract_docstring_with_swagger_info(method: Any) -> str:
    """Build the flasgger YAML spec for a facade method by introspecting its
    signature: a required ``model`` file plus one field per parameter."""
    lines = [
        "    ---",
        "    tags:",
        f"      - {method.__name__}",
        "    consumes:",
        "      - multipart/form-data",
        "    parameters:",
        "      - name: model",
        "        in: formData",
        "        type: file",
        "        required: true",
    ]
    for param in _operation_params(method):
        ptype = 'file' if _is_file_param(param) else _SWAGGER_TYPES.get(
            _scalar_type(param.annotation), 'string'
        )
        required = param.default is inspect.Parameter.empty
        lines += [
            f"      - name: {_field_name(param)}",
            "        in: formData",
            f"        type: {ptype}",
            f"        required: {str(required).lower()}",
        ]
        if param.name in _ENUM_VALUES:
            lines.append("        enum:")
            lines += [f"          - {value}" for value in _ENUM_VALUES[param.name]]
    lines += [
        "    responses:",
        "      200:",
        "        description: Result of the operation",
    ]
    docstring = (method.__doc__ or "").replace('\n', ' ').strip()
    return docstring + "\n" + "\n".join(lines) + "\n"


def create_route(operation_name: str, docstring: str) -> Callable[[], Any]:
    def route_function() -> Any:
        return _api_call(operation_name)

    route_function.__name__ = operation_name
    route_function.__doc__ = docstring
    return route_function


# Introspect FLAMAFeatureModel to expose every public method as a POST route,
# generating its Swagger spec from the method signature. Limits are passed as
# callables so they read the app config of whichever app the blueprint joins.
for name, method in inspect.getmembers(FLAMAFeatureModel, predicate=inspect.isfunction):
    if name.startswith('_'):
        continue
    if getattr(method, '_facade_kind', 'operation') != 'operation':
        continue  # producers/transformers return models; Python-API only for now
    docstring = extract_docstring_with_swagger_info(method)
    limit = expensive_operation_limit if name in _EXPENSIVE_OPERATIONS else default_operation_limit
    route_view = limiter.limit(limit)(create_route(name, docstring))
    operations_bp.route(f'/{name}', methods=['POST'])(route_view)
