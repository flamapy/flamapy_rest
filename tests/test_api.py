import io
from typing import Any, Iterator

import pytest
from flask.testing import FlaskClient

from app import app as flask_app
from flamapy.interfaces.rest import operations_routes
from flamapy.interfaces.rest.extensions import limiter, result_cache
from flamapy.interfaces.rest.runner import OperationTimeout, run_operation

VALID_MODEL = "./resources/models/simple/valid_model.uvl"

SATISFIABLE = '/api/v1/operations/satisfiable'
CONFIGURATIONS = '/api/v1/operations/configurations'


def _model_upload() -> dict[str, Any]:
    with open(VALID_MODEL, 'rb') as model_file:
        content = model_file.read()
    return {'model': (io.BytesIO(content), 'valid_model.uvl')}


@pytest.fixture
def client() -> Iterator[FlaskClient]:
    flask_app.config['TESTING'] = True
    flask_app.config['OPERATION_TIMEOUT'] = 0  # run inline; the runner has its own tests
    limiter.enabled = False
    result_cache.init_app(flask_app)  # fresh cache per test
    yield flask_app.test_client()
    limiter.reset()
    limiter.enabled = True


def test_missing_model_returns_400(client: FlaskClient) -> None:
    response = client.post(SATISFIABLE, data={})
    assert response.status_code == 400
    assert 'error' in response.get_json()


def test_unparseable_model_returns_400(client: FlaskClient) -> None:
    data = {'model': (io.BytesIO(b'this is not a feature model'), 'broken.uvl')}
    response = client.post(SATISFIABLE, data=data)
    assert response.status_code == 400
    assert 'parsed' in response.get_json()['error']


def test_satisfiable_returns_result(client: FlaskClient) -> None:
    response = client.post(SATISFIABLE, data=_model_upload())
    assert response.status_code == 200
    assert response.get_json() is True
    assert response.headers['X-Cache'] == 'MISS'


def test_oversized_upload_returns_413(client: FlaskClient) -> None:
    flask_app.config['MAX_CONTENT_LENGTH'] = 1024
    try:
        data = {'model': (io.BytesIO(b'x' * 4096), 'big.uvl')}
        response = client.post(SATISFIABLE, data=data)
        assert response.status_code == 413
        assert 'error' in response.get_json()
    finally:
        flask_app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024


def test_repeated_request_hits_cache(client: FlaskClient) -> None:
    first = client.post(SATISFIABLE, data=_model_upload())
    second = client.post(SATISFIABLE, data=_model_upload())
    assert first.headers['X-Cache'] == 'MISS'
    assert second.headers['X-Cache'] == 'HIT'
    assert first.get_json() == second.get_json()


def test_different_arguments_miss_cache(client: FlaskClient) -> None:
    client.post(SATISFIABLE, data=_model_upload())
    other = client.post(SATISFIABLE, data={**_model_upload(), 'backend': 'bdd'})
    assert other.headers['X-Cache'] == 'MISS'


def test_rate_limit_returns_429(client: FlaskClient) -> None:
    limiter.enabled = True
    flask_app.config['RATELIMIT_DEFAULT_OPERATION'] = '2 per minute'
    statuses = [client.post(SATISFIABLE, data=_model_upload()).status_code for _ in range(3)]
    assert statuses[:2] == [200, 200]
    assert statuses[2] == 429


def test_expensive_tier_is_stricter(client: FlaskClient) -> None:
    limiter.enabled = True
    flask_app.config['RATELIMIT_DEFAULT_OPERATION'] = '100 per minute'
    flask_app.config['RATELIMIT_EXPENSIVE_OPERATION'] = '1 per minute'
    assert client.post(CONFIGURATIONS, data=_model_upload()).status_code == 200
    assert client.post(CONFIGURATIONS, data=_model_upload()).status_code == 429
    # The cheap tier is unaffected by the expensive one being exhausted.
    assert client.post(SATISFIABLE, data=_model_upload()).status_code == 200


def test_runner_kills_operation_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_execute(model_path: str, operation_name: str, kwargs: dict[str, Any]) -> None:
        import time
        time.sleep(10)

    # The forked child inherits the patched module, so the patch applies there too.
    monkeypatch.setattr('flamapy.interfaces.rest.runner._execute', slow_execute)
    with pytest.raises(OperationTimeout):
        run_operation(VALID_MODEL, 'satisfiable', {}, timeout=1)


def test_timeout_maps_to_504(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def timing_out(model_path: str, operation_name: str, kwargs: dict[str, Any], timeout: int) -> Any:
        raise OperationTimeout('too slow')

    flask_app.config['OPERATION_TIMEOUT'] = 1
    monkeypatch.setattr(operations_routes, 'run_operation', timing_out)
    response = client.post(SATISFIABLE, data=_model_upload())
    assert response.status_code == 504
    assert 'error' in response.get_json()


# --- parity with the Python facade: backend selection, provenance, plan, every method -------

import inspect

from flamapy.core.exceptions import FlamaException
from flamapy.interfaces.python.flamapy_feature_model import FLAMAFeatureModel

CONFIGURATIONS_NUMBER = '/api/v1/operations/configurations_number'


def test_every_facade_method_has_a_route() -> None:
    rules = {rule.rule for rule in flask_app.url_map.iter_rules()}
    for name, method in inspect.getmembers(FLAMAFeatureModel, predicate=inspect.isfunction):
        if name.startswith('_') or getattr(method, '_facade_descriptor', None) is None:
            continue
        assert f'/api/v1/operations/{name}' in rules, name
        has_backend = 'backend' in inspect.signature(method).parameters
        assert (f'/api/v1/operations/{name}/plan' in rules) == has_backend, name


def test_result_carries_its_provenance_in_headers(client: FlaskClient) -> None:
    response = client.post(SATISFIABLE, data=_model_upload())
    assert response.status_code == 200
    assert response.get_json() is True
    assert response.headers['X-Flamapy-Plugin'] == 'pysat_metamodel'
    assert response.headers['X-Flamapy-Backend'] == 'pysat'
    assert response.headers['X-Flamapy-Exact'] == 'true'
    assert 'X-Flamapy-Planner' not in response.headers  # historical default, no planner


def test_auto_backend_reports_the_planner(client: FlaskClient) -> None:
    response = client.post(CONFIGURATIONS_NUMBER, data={**_model_upload(), 'backend': 'auto'})
    assert response.status_code == 200
    assert response.get_json() == 816
    assert response.headers['X-Flamapy-Backend'] == 'bdd'
    assert response.headers['X-Flamapy-Planner'].startswith('auto: bdd')


def test_cache_hit_keeps_the_provenance(client: FlaskClient) -> None:
    client.post(SATISFIABLE, data=_model_upload())
    hit = client.post(SATISFIABLE, data=_model_upload())
    assert hit.headers['X-Cache'] == 'HIT'
    assert hit.headers['X-Flamapy-Backend'] == 'pysat'


def test_allow_approximate_is_a_parameter(client: FlaskClient) -> None:
    data = {**_model_upload(), 'backend': 'auto', 'allow_approximate': 'true'}
    response = client.post('/api/v1/operations/core_features', data=data)
    assert response.status_code == 200
    assert response.headers['X-Flamapy-Planner'].startswith('auto:')


def test_plan_endpoint_explains_the_choice(client: FlaskClient) -> None:
    response = client.post(CONFIGURATIONS_NUMBER + '/plan', data=_model_upload())
    assert response.status_code == 200
    plan = response.get_json()
    assert plan['plugin'] == 'bdd_metamodel'
    assert plan['backend'] == 'bdd'
    assert plan['transformation_chain'] == ['fm', 'bdd']
    assert 'historical default backend' in plan['rationale']
    assert 'pysat_metamodel' in plan['alternatives']
    assert isinstance(plan['estimated_cost_ms'], int)


def test_plan_only_exists_for_backend_selectable_operations(client: FlaskClient) -> None:
    response = client.post('/api/v1/operations/explain_void_model/plan', data=_model_upload())
    assert response.status_code == 404


def test_operation_errors_are_reported_as_422(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(model_path: Any, operation_name: str, kwargs: dict[str, Any], timeout: int) -> Any:
        raise FlamaException("No installed backend can run 'configurations_number' on this model")

    monkeypatch.setattr(operations_routes, 'run_operation', failing)
    response = client.post(CONFIGURATIONS_NUMBER, data={**_model_upload(), 'backend': 'auto'})
    assert response.status_code == 422
    assert 'No installed backend' in response.get_json()['error']


def test_unknown_backend_is_rejected(client: FlaskClient) -> None:
    response = client.post(SATISFIABLE, data={**_model_upload(), 'backend': 'nope'})
    assert response.status_code == 400


def test_producer_needs_no_model_and_returns_uvl(client: FlaskClient) -> None:
    response = client.post('/api/v1/operations/generate_random_feature_model',
                           data={'num_features': '6', 'seed': '1'})
    assert response.status_code == 200
    assert response.get_json().startswith('features')


def test_transformer_returns_the_modified_model_as_uvl(client: FlaskClient) -> None:
    response = client.post('/api/v1/operations/generate_random_attribute',
                           data={**_model_upload(), 'name': 'cost', 'max_value': '9'})
    assert response.status_code == 200
    assert 'cost' in response.get_json()
    assert response.headers['X-Flamapy-Plugin'] == 'fm_metamodel'


def test_language_level_is_serialised(client: FlaskClient) -> None:
    response = client.post('/api/v1/operations/language_level', data=_model_upload())
    assert response.status_code == 200
    assert response.get_json() == {'major': 'BOOLEAN', 'minors': []}


def test_json_parameters_are_parsed(client: FlaskClient) -> None:
    data = {**_model_upload(), 'configurations': '[{"A": true}, {"B": true}]', 't': '2'}
    response = client.post('/api/v1/operations/coverage', data=data)
    assert response.status_code == 200
    assert 0.0 < response.get_json() <= 1.0


def test_swagger_spec_lists_every_route(client: FlaskClient) -> None:
    spec = client.get('/apispec_1.json').get_json()
    assert '/api/v1/operations/generate_random_feature_model' in spec['paths']
    assert '/api/v1/operations/configurations_number/plan' in spec['paths']
    params = spec['paths']['/api/v1/operations/configurations_number']['post']['parameters']
    backend = next(p for p in params if p['name'] == 'backend')
    assert 'auto' in backend['enum']
    assert any(p['name'] == 'allow_approximate' for p in params)
