# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container to /app
WORKDIR /flamapy-api

COPY pyproject.toml pyproject.toml
COPY setup.py setup.py
RUN pip3 install .
COPY . .

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run app.py when the container launches; bind/workers/timeout/logging come
# from gunicorn.conf.py (overridable via WEB_CONCURRENCY / GUNICORN_TIMEOUT).
# In case of wish the dev server use CMD [ "python3", "-m" , "flask", "run", "--host=0.0.0.0"]
CMD ["gunicorn", "app:app"]
