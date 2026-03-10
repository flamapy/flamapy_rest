# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`flamapy_rest` is a Flask REST API that wraps the [FLAMAPY](https://flamapy.github.io/) framework for feature model analysis. It dynamically exposes FLAMAPY operations as HTTP endpoints.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for dev tools

# Run development server
python -m flask run --host=0.0.0.0

# Run production server
gunicorn --bind 0.0.0.0:8000 app:app

# Run all tests
pytest

# Run a single test
pytest tests/test_basic_units.py::test_satisfiable -v

# Run with coverage
pytest --cov

# Lint
prospector
mypy .
```

## Architecture

### Dynamic Route Generation

The core design pattern is in `flamapy/interfaces/rest/operations_routes.py`. On startup, it:
1. Introspects `FLAMAFeatureModel` from the flamapy library using `inspect`
2. Automatically creates a POST route under `/api/v1/operations/<method_name>` for every public method
3. Auto-generates Swagger documentation from docstrings and method signatures

### API Call Flow

Every endpoint goes through `_api_call(operation_name)`:
1. Accept uploaded model file → save to `./resources/models/`
2. Instantiate `FLAMAFeatureModel` from the saved file
3. Resolve method via `getattr()` and inspect its signature
4. Extract optional `feature` or `configuration` params from form data based on signature
5. Execute the operation and return JSON
6. Clean up temporary files

`app.py` registers the operations blueprint and configures Flasgger (Swagger UI at `/docs/`).

### Adding New Operations

New operations are automatically available as API endpoints as long as they are public methods on `FLAMAFeatureModel` in the flamapy core library — no route code changes needed.

### Test Resources

Tests use real model files:
- Model: `resources/models/simple/valid_model.uvl`
- Configuration: `resources/configurations/valid_configuration.csvconf`

### API Versioning Note

The app registers routes at both `/api/v1/operations` (blueprint in `operations_routes.py`) and `/api/v2` (referenced in `app.py`). The swagger UI is at `/docs/`.
