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
