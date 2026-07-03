import logging
import time

from flask import Flask, Response, g, jsonify, request
from flask_cors import CORS
from flasgger import Swagger
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

# Importing routes
from flamapy.interfaces.rest.operations_routes import operations_bp
from flamapy.interfaces.rest.config import load_config
from flamapy.interfaces.rest.extensions import limiter, result_cache

# Creating the app and configuring the cors
app = Flask(__name__)
CORS(app)
# Abuse controls (upload size, rate limits, operation timeout, result cache);
# every value is overridable through FLAMAPY_* env vars.
app.config.update(load_config())

if app.config['TRUST_PROXY']:
    # Honor X-Forwarded-For so per-IP rate limits see the real client address
    # when the API runs behind a reverse proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # type: ignore[method-assign]

limiter.init_app(app)
result_cache.init_app(app)

# One structured line per request on stdout (Docker-friendly).
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
request_logger = logging.getLogger('flamapy.rest.requests')


@app.before_request
def _start_timer() -> None:
    g.start_time = time.monotonic()


@app.after_request
def _log_request(response: Response) -> Response:
    duration_ms = (time.monotonic() - g.get('start_time', time.monotonic())) * 1000
    request_logger.info(
        'remote=%s method=%s path=%s status=%s duration_ms=%.1f bytes_in=%s cache=%s',
        request.remote_addr,
        request.method,
        request.path,
        response.status_code,
        duration_ms,
        request.content_length or 0,
        response.headers.get('X-Cache', '-'),
    )
    return response


@app.errorhandler(HTTPException)
def _json_http_error(error: HTTPException) -> tuple[Response, int]:
    # Covers 400/404/413/429/504...; keeps API errors as JSON instead of HTML.
    return jsonify(error=error.description), error.code or 500


@app.errorhandler(Exception)
def _json_unexpected_error(error: Exception) -> tuple[Response, int]:
    request_logger.exception('Unhandled error on %s: %s', request.path, error)
    return jsonify(error='Internal server error'), 500


#Now we are configuring the self generation of swagger by means of flasgger
config = {
     "specs_route": "/docs/"
}
swag = Swagger(app,config=config,merge=True)

# Adding blueprints
app.register_blueprint(operations_bp)

@app.route("/", methods=['GET'])
def home() -> Response:
    return app.send_static_file('home.html')

if __name__ == '__main__':
    app.run()
