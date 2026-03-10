import os
import inspect
import json
from typing import Any

from flask import Blueprint, request, jsonify
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel
from flamapy.metamodels.configuration_metamodel.models import Configuration


operations_bp = Blueprint('operations_bp', __name__, url_prefix='/api/v1/operations')

MODEL_FOLDER = './resources/models/'

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Configuration):
            return obj.__dict__
        return super().default(obj)

def _api_call(operation_name: str) -> Any:
    # Get files
    uploaded_model = request.files['model']

    # Check if file is provided
    filename: str = uploaded_model.filename or ''
    if filename != '':
        # Save file
        uploaded_model.save(os.path.join(MODEL_FOLDER, filename))

        fm = FLAMAFeatureModel(os.path.join(MODEL_FOLDER, filename))
        operation = getattr(fm, operation_name)

        # Extract the method signature
        sig = inspect.signature(operation)
        params = sig.parameters

        args = []
        for param in params.values():
            if param.name == 'feature_name':
                args.append(request.form['feature'])
            elif param.name == 'configuration_path':
                configuration = request.files['configuration']
                conf_filename: str = configuration.filename or ''
                configuration.save(os.path.join(MODEL_FOLDER, conf_filename))
                args.append(os.path.join(MODEL_FOLDER, conf_filename))

        result = operation(*args)

        # Remove file
        os.remove(os.path.join(MODEL_FOLDER, filename))

        if 'configuration' in request.files:
            conf_file = request.files['configuration']
            conf_file_name: str = conf_file.filename or ''
            os.remove(os.path.join(MODEL_FOLDER, conf_file_name))

        # Return result
        if result is None:
            return jsonify(error='Not valid result'), 404
        else:
            return jsonify(json.loads(json.dumps(result, cls=CustomJSONEncoder)))


def extract_docstring_with_swagger_info(method: Any) -> str:
    docstring = method.__doc__ or ""
    parameters = """
    parameters:
      - name: model
        in: formData
        type: file
        required: true
    """

    # Extract the method signature
    sig = inspect.signature(method)
    for param in sig.parameters.values():
        if param.name == 'feature_name':
            parameters += """
      - name: feature
        in: formData
        type: string
        required: true
    """
        elif param.name == 'configuration_path':
            parameters += """
      - name: configuration
        in: formData
        type: file
        required: true
    """

    swagger_info = """
    ---
    tags:
      - {operation_name}
    {parameters}
    responses:
      200:
        description: Result of the operation
        examples:
          result: Example result
    """.format(operation_name=method.__name__, parameters=parameters)
        # Replace new lines with HTML line breaks
    docstring = docstring.replace('\n', '')
    return docstring + swagger_info

def create_route(operation_name: str, docstring: str) -> Any:
    def route_function() -> Any:
        return _api_call(operation_name)

    route_function.__name__ = operation_name
    route_function.__doc__ = docstring
    return route_function

# Introspect FLAMAFeatureModel class to find all callable methods and create routes dynamically
for name, method in inspect.getmembers(FLAMAFeatureModel, predicate=inspect.isfunction):
    if name.startswith('_'):
        continue
    docstring = extract_docstring_with_swagger_info(method)
    operations_bp.route(f'/{name}', methods=['POST'])(create_route(name, docstring))
