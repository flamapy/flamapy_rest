import os
import hashlib
import inspect
import json
import shutil
import tempfile
import typing
from typing import Any, Callable, Optional

from flask import Blueprint, Response, current_app, request, jsonify, abort
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from flamapy.core.exceptions import FlamaException
from flamapy.core.models.language_level import LanguageLevel
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel, Backend
from flamapy.metamodels.configuration_metamodel.models import Configuration
from flamapy.metamodels.fm_metamodel.models import FeatureModel
from flamapy.metamodels.fm_metamodel.transformations import UVLWriter

from flamapy.interfaces.rest.extensions import (
    limiter,
    result_cache,
    default_operation_limit,
    expensive_operation_limit,
)
from flamapy.interfaces.rest.runner import (
    ModelParseError,
    OperationTimeout,
    run_operation,
    run_plan,
)


operations_bp = Blueprint('operations_bp', __name__, url_prefix='/api/v1/operations')

# Operations that enumerate or repeatedly invoke a solver; they get the stricter
# rate-limit tier because a single call can monopolize a CPU for a long time.
_EXPENSIVE_OPERATIONS = {
    'attribute_optimization',
    'commonality',
    'generate_random_feature_model',
    'configurations',
    'covering_array',
    't_wise_sampling',
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

# The provenance of every result (the facade's ``last_result``: plugin, backend, exact,
# planner rationale, wall time of the run that computed it, hash of the model, whether the
# backend model came from the artifact cache) travels in response headers, so the body stays
# the bare value the Python facade returns.
PROVENANCE_HEADERS = (
    ('X-Flamapy-Plugin', 'plugin'),
    ('X-Flamapy-Backend', 'backend'),
    ('X-Flamapy-Exact', 'exact'),
    ('X-Flamapy-Planner', 'planner'),
    ('X-Flamapy-Wall-Time', 'wall_time'),
    ('X-Flamapy-Model-Hash', 'model_hash'),
    ('X-Flamapy-Artifact-Cache', 'cache_hit'),
)


class CustomJSONEncoder(json.JSONEncoder):
    """JSON for the facade's return types: configurations as their fields, feature models
    (``generate_random_feature_model``, ``generate_random_attribute``) as UVL text, language
    levels as their major/minor names."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Configuration):
            return obj.__dict__
        if isinstance(obj, FeatureModel):
            return UVLWriter(path=None, source_model=obj).transform()
        if isinstance(obj, LanguageLevel):
            return {'major': obj.major.name, 'minors': sorted(m.name for m in obj.minors)}
        if isinstance(obj, (set, frozenset)):
            return sorted(obj, key=str)
        return super().default(obj)


def _facade_kind(method: Any) -> str:
    """'operation' (runs on an uploaded model), 'transformer' (returns the modified model)
    or 'producer' (builds a model from parameters; no upload)."""
    return str(getattr(method, '_facade_kind', 'operation'))


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


def _is_json_param(param: inspect.Parameter) -> bool:
    """Untyped facade inputs take structured values (``objectives``: an attribute name or
    {attribute: min|max}; ``configurations``: a list of {feature: bool}); over HTTP they
    arrive as JSON text."""
    return param.annotation is typing.Any


def _convert_param(raw: str, param: inspect.Parameter) -> Any:
    if _is_json_param(param) and raw.lstrip()[:1] in ('[', '{'):
        return json.loads(raw)
    return _convert(raw, _scalar_type(param.annotation))


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
                    kwargs[param.name] = _convert_param(raw, param)
                except (TypeError, ValueError):
                    abort(400, f"Invalid value for '{field}'")
            elif required:
                abort(400, f"Missing required parameter '{field}'")
    return kwargs


def _cache_key(
    operation_name: str, operation: Any, model_path: Optional[str], kwargs: dict[str, Any]
) -> str:
    """Digest of everything that determines the result: the operation, the model
    contents and every argument (file arguments by content, not by temp path)."""
    file_params = {p.name for p in _operation_params(operation) if _is_file_param(p)}
    digest = hashlib.sha256()
    digest.update(operation_name.encode())
    if model_path is not None:
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


def _header_value(value: Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _respond(entry: dict[str, Any], cache_status: str) -> Response:
    """The response for a cached or fresh ``{'value': ..., 'provenance': ...}`` entry: the
    bare value as the body, the provenance in the headers."""
    provenance: dict[str, Any] = entry.get('provenance') or {}
    response: Response = jsonify(entry['value'])
    response.headers['X-Cache'] = cache_status
    for header, field in PROVENANCE_HEADERS:
        if provenance.get(field) is not None:
            response.headers[header] = _header_value(provenance[field])
    return response


def _uploaded_model() -> FileStorage:
    uploaded_model = request.files.get('model')
    if uploaded_model is None or not uploaded_model.filename:
        abort(400, "Missing required file 'model'")
    return uploaded_model


def _api_call(operation_name: str) -> Any:
    operation = getattr(FLAMAFeatureModel, operation_name)
    # Producers build a model from their parameters: nothing to upload.
    uploaded_model = None if _facade_kind(operation) == 'producer' else _uploaded_model()

    # Each request gets its own directory so concurrent requests cannot collide
    # on (or delete) each other's uploads; the whole tree is removed afterwards.
    work_dir = tempfile.mkdtemp(prefix='flamapy_')
    try:
        model_path = _save_upload(uploaded_model, work_dir) if uploaded_model else None
        kwargs = _resolve_kwargs(operation, work_dir)

        key = _cache_key(operation_name, operation, model_path, kwargs)
        cached = result_cache.get(key)
        if cached is not None:
            return _respond(cached, 'HIT')

        try:
            value, provenance = run_operation(
                model_path, operation_name, kwargs, current_app.config['OPERATION_TIMEOUT']
            )
        except ModelParseError:
            abort(400, "The uploaded model could not be parsed")
        except OperationTimeout as exc:
            abort(504, str(exc))
        except FlamaException as exc:
            # The operation could not run: an unknown backend, invalid inputs, or no
            # installed plugin able to run it on this model (backend=auto). 404 as in 2.6,
            # with the reason; 3.0 moves this to 422.
            abort(404, str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if value is None:
        return jsonify(error='Not valid result'), 404
    entry = {
        'value': json.loads(json.dumps(value, cls=CustomJSONEncoder)),
        'provenance': provenance,
    }
    result_cache.set(key, entry)
    return _respond(entry, 'MISS')


def _plan_call(operation_name: str) -> Any:
    """Which backend ``backend=auto`` would pick for the operation on the uploaded model."""
    uploaded_model = _uploaded_model()
    raw = request.form.get('allow_approximate')
    allow_approximate = _convert(raw, bool) if raw not in (None, '') else None
    work_dir = tempfile.mkdtemp(prefix='flamapy_')
    try:
        model_path = _save_upload(uploaded_model, work_dir)
        try:
            chosen = run_plan(model_path, operation_name, allow_approximate,
                              current_app.config['OPERATION_TIMEOUT'])
        except ModelParseError:
            abort(400, "The uploaded model could not be parsed")
        except OperationTimeout as exc:
            abort(504, str(exc))
        except FlamaException as exc:
            abort(404, str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return jsonify(chosen)


def extract_docstring_with_swagger_info(method: Any) -> str:
    """Build the flasgger YAML spec for a facade method by introspecting its
    signature: a required ``model`` file (except for producers) plus one field per
    parameter."""
    lines = [
        "    ---",
        "    tags:",
        f"      - {method.__name__}",
        "    consumes:",
        "      - multipart/form-data",
        "    parameters:",
    ]
    if _facade_kind(method) != 'producer':
        lines += [
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
        if _is_json_param(param):
            lines.append("        description: JSON (an object or a list) or a plain string")
        if param.name == 'allow_approximate':
            lines.append("        description: Only with backend=auto, let the planner choose"
                         " approximate implementations")
        if param.name in _ENUM_VALUES:
            lines.append("        enum:")
            lines += [f"          - {value}" for value in _ENUM_VALUES[param.name]]
    returns_model = _facade_kind(method) in ('producer', 'transformer')
    lines += [
        "    responses:",
        "      200:",
        "        description: " + (
            "A JSON string holding the resulting feature model in UVL" if returns_model
            else "Result of the operation; its provenance travels in the X-Flamapy-* headers"),
        "        headers:",
    ]
    for header, _ in PROVENANCE_HEADERS:
        lines += [f"          {header}:", "            type: string"]
    lines += [
        "      404:",
        "        description: The operation could not run (unknown backend, invalid input,"
        " or no installed plugin can run it on this model); the body says why",
    ]
    docstring = (method.__doc__ or "").replace('\n', ' ').strip()
    return docstring + "\n" + "\n".join(lines) + "\n"


def _plan_docstring(operation_name: str) -> str:
    """The flasgger spec of an operation's ``/plan`` endpoint."""
    lines = [
        f"Which backend backend=auto would run {operation_name} on the uploaded model, and"
        " why: the plugin, its model extension, the transformation chain, the estimated"
        " cost in milliseconds, the rationale and the alternatives. Nothing is executed.",
        "    ---",
        "    tags:",
        f"      - {operation_name}",
        "    consumes:",
        "      - multipart/form-data",
        "    parameters:",
        "      - name: model",
        "        in: formData",
        "        type: file",
        "        required: true",
        "      - name: allow_approximate",
        "        in: formData",
        "        type: boolean",
        "        required: false",
        "        description: Also consider approximate implementations",
        "    responses:",
        "      200:",
        "        description: The planner's choice",
        "      404:",
        "        description: No installed plugin can run the operation on this model",
    ]
    return "\n".join(lines) + "\n"


def create_route(operation_name: str, docstring: str) -> Callable[[], Any]:
    def route_function() -> Any:
        return _api_call(operation_name)

    route_function.__name__ = operation_name
    route_function.__doc__ = docstring
    return route_function


def create_plan_route(operation_name: str) -> Callable[[], Any]:
    def route_function() -> Any:
        return _plan_call(operation_name)

    route_function.__name__ = f'{operation_name}_plan'
    route_function.__doc__ = _plan_docstring(operation_name)
    return route_function


def _selects_backend(method: Any) -> bool:
    return any(param.name == 'backend' for param in _operation_params(method))


# Introspect FLAMAFeatureModel to expose every public method as a POST route,
# generating its Swagger spec from the method signature. Limits are passed as
# callables so they read the app config of whichever app the blueprint joins.
for name, method in inspect.getmembers(FLAMAFeatureModel, predicate=inspect.isfunction):
    if name.startswith('_') or getattr(method, '_facade_descriptor', None) is None:
        continue  # plan/run_async/iter_configurations are Python-API helpers, not operations
    docstring = extract_docstring_with_swagger_info(method)
    limit = expensive_operation_limit if name in _EXPENSIVE_OPERATIONS else default_operation_limit
    route_view = limiter.limit(limit)(create_route(name, docstring))
    operations_bp.route(f'/{name}', methods=['POST'])(route_view)
    if _selects_backend(method):
        # Operations with more than one backend also answer which one the planner would pick.
        plan_view = limiter.limit(default_operation_limit)(create_plan_route(name))
        operations_bp.route(f'/{name}/plan', methods=['POST'])(plan_view)
