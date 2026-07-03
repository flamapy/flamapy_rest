import os

bind = '0.0.0.0:8000'
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
# Hard backstop for a wedged worker; must exceed FLAMAPY_OPERATION_TIMEOUT so
# the in-app soft limit (a JSON 504) fires before the worker is killed.
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
accesslog = '-'
