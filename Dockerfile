# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container to /app
WORKDIR /flamapy-api

COPY pyproject.toml pyproject.toml
COPY setup.py setup.py
# On a release the flamapy packages were uploaded minutes ago, and PyPI's index is served from
# caches that do not all show a new version at once: retry instead of failing the image.
RUN for attempt in 1 2 3 4 5 6; do \
        pip3 install --no-cache-dir . && exit 0; \
        echo "pip install failed (attempt $attempt of 6); retrying in 30 s" >&2; sleep 30; \
    done; exit 1
COPY . .

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run app.py when the container launches; bind/workers/timeout/logging come
# from gunicorn.conf.py (overridable via WEB_CONCURRENCY / GUNICORN_TIMEOUT).
# In case of wish the dev server use CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0"]
CMD ["gunicorn", "app:app"]
