import os
import inspect
import json
import typing

from flask import Blueprint, request, jsonify, abort
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel
from flamapy.metamodels.configuration_metamodel.models import Configuration


operations_bp = Blueprint('operations_bp', __name__, url_prefix='/api/v1/operations')

MODEL_FOLDER = './resources/models/'

# Backward-compatible multipart field names for parameters that the API exposed
# before the dispatcher became generic. Any other parameter derives its field
# name from the parameter itself (file params drop the trailing "_path").
_LEGACY_FIELD = {
    'feature_name': 'feature',
}

_SWAGGER_TYPES = {int: 'integer', float: 'number', bool: 'boolean', str: 'string'}


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Configuration):
            return obj.__dict__
        return super().default(obj)


def _operation_params(method):
    """Call-relevant parameters of a facade method (excluding ``self``)."""
    return [p for p in inspect.signature(method).parameters.values() if p.name != 'self']


def _is_file_param(param):
    """Parameters whose value is a path are supplied as uploaded files."""
    return param.name.endswith('_path')


def _field_name(param):
    """The multipart field name a client sends for this parameter."""
    if _is_file_param(param):
        return param.name[: -len('_path')]      # configuration_path -> configuration
    return _LEGACY_FIELD.get(param.name, param.name)


def _scalar_type(annotation):
    """Resolve the scalar type of a (possibly ``Optional[...]``) annotation."""
    if annotation is inspect.Parameter.empty:
        return str
    if typing.get_origin(annotation) is typing.Union:
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        annotation = non_none[0] if non_none else str
    return annotation if annotation in (int, float, bool, str) else str


def _convert(raw, scalar_type):
    if scalar_type is bool:
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    if scalar_type is int:
        return int(raw)
    if scalar_type is float:
        return float(raw)
    return raw


def _resolve_kwargs(operation, saved_files):
    """Build the keyword arguments for a facade method from the request, saving
    any uploaded files (their paths are appended to ``saved_files``)."""
    kwargs = {}
    for param in _operation_params(operation):
        field = _field_name(param)
        required = param.default is inspect.Parameter.empty
        if _is_file_param(param):
            uploaded = request.files.get(field)
            if uploaded is not None and uploaded.filename:
                path = os.path.join(MODEL_FOLDER, uploaded.filename)
                uploaded.save(path)
                saved_files.append(path)
                kwargs[param.name] = path
            elif required:
                abort(400, f"Missing required file '{field}'")
        else:
            raw = request.form.get(field)
            if raw is not None and raw != '':
                try:
                    kwargs[param.name] = _convert(raw, _scalar_type(param.annotation))
                except (TypeError, ValueError):
                    abort(400, f"Invalid value for '{field}'")
            elif required:
                abort(400, f"Missing required parameter '{field}'")
    return kwargs


def _api_call(operation_name: str):
    uploaded_model = request.files.get('model')
    if uploaded_model is None or uploaded_model.filename == '':
        abort(400, "Missing required file 'model'")

    saved_files: list[str] = []
    model_path = os.path.join(MODEL_FOLDER, uploaded_model.filename)
    uploaded_model.save(model_path)
    saved_files.append(model_path)

    try:
        fm = FLAMAFeatureModel(model_path)
        operation = getattr(fm, operation_name)
        kwargs = _resolve_kwargs(operation, saved_files)
        result = operation(**kwargs)
    finally:
        for path in saved_files:
            if os.path.exists(path):
                os.remove(path)

    if result is None:
        return jsonify(error='Not valid result'), 404
    return jsonify(json.loads(json.dumps(result, cls=CustomJSONEncoder)))


def extract_docstring_with_swagger_info(method):
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
    lines += [
        "    responses:",
        "      200:",
        "        description: Result of the operation",
    ]
    docstring = (method.__doc__ or "").replace('\n', ' ').strip()
    return docstring + "\n" + "\n".join(lines) + "\n"


def create_route(operation_name: str, docstring: str):
    def route_function():
        return _api_call(operation_name)

    route_function.__name__ = operation_name
    route_function.__doc__ = docstring
    return route_function


# Introspect FLAMAFeatureModel to expose every public method as a POST route,
# generating its Swagger spec from the method signature.
for name, method in inspect.getmembers(FLAMAFeatureModel, predicate=inspect.isfunction):
    if name.startswith('_'):
        continue
    docstring = extract_docstring_with_swagger_info(method)
    operations_bp.route(f'/{name}', methods=['POST'])(create_route(name, docstring))
