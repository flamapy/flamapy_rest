<div align="center">

  <a href="https://github.com/flamapy/flamapy-rest/actions/workflows/main.yml">![Python analysis](https://github.com/flamapy/flamapy-rest/actions/workflows/main.yml/badge.svg?branch=main)</a>
  <a href="https://github.com/flamapy/flamapy-rest/actions/workflows/conventionalpr.yml">![Conventional Commits](https://github.com/flamapy/flamapy-rest/actions/workflows/conventionalpr.yml/badge.svg?branch=main)</a>
  <a href="https://github.com/flamapy/flamapy-rest/actions/workflows/docker-image.yml">![Docker Image CI](https://github.com/flamapy/flamapy-rest/actions/workflows/docker-image.yml/badge.svg)</a>
  <a href="https://pypi.org/project/flamapy-rest/">![PyPI](https://img.shields.io/pypi/v/flamapy-rest?label=pypi%20package)</a>
  <a href="https://hub.docker.com/r/flamapy/flamapy-rest">![Docker Pulls](https://img.shields.io/docker/pulls/flamapy/flamapy-rest)</a>
  <a href="https://pypi.org/project/flamapy-rest/">![PyPI - Downloads](https://img.shields.io/pypi/dm/flamapy-rest)</a>
</div>

<div id="top"></div>
<br />
<div align="center">

  <h3 align="center">FLAMAPY REST API</h3>

  <p align="center">
    A new and easy way to use FLAMA
    <br />
    <a href="https://github.com/flamapy/flamapy-rest/issues">Report Bug</a>
    ·
    <a href="https://github.com/flamapy/flamapy-rest/issues">Request Feature</a>
  </p>
</div>

<!-- ABOUT THE PROJECT -->
## About The Project

`flamapy-rest` is a [Flask](https://flask.palletsprojects.com/) REST API that wraps the
[FLAMAPY](https://flamapy.github.io/) framework for **feature model analysis**. It dynamically
exposes FLAMAPY operations (dead features, false-optional features, configurations, satisfiability,
diagnosis, …) as HTTP endpoints, with self-generated [Swagger](https://swagger.io/) documentation.

Feature model analysis has a crucial role in software product line engineering, enabling us to
understand, design, and validate the complex relationships among features in a software product
line. These models can be complex and challenging to analyze due to their variability, making it
difficult to identify conflicts, dead features, and potential optimizations. This REST API makes
that analysis available to any tool or language that can speak HTTP.

Please note: this is a living document and we will continue to update and improve it as we release
new versions of the plugins and receive feedback from our users. If there's anything you don't
understand or if you have any suggestions for improvement, don't hesitate to
[open an issue](https://github.com/flamapy/flamapy-rest/issues). We're here to help!

### Built With

* [Docker](https://www.docker.com/)
* [Flask](https://flask.palletsprojects.com/)
* [FLAMAPY](https://github.com/flamapy)
* [Flasgger](https://github.com/flasgger/flasgger)

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

There are three supported ways to run the API. **Using the published Docker image is the easiest** —
nothing to build, and it already bundles FLAMAPY and all of its analysis plugins.

### Option 1 — Run the published Docker image (recommended)

The CI publishes a multi-arch image (`linux/amd64` and `linux/arm64`) to Docker Hub at
[`flamapy/flamapy-rest`](https://hub.docker.com/r/flamapy/flamapy-rest) on every version tag.

```bash
# Pull and run the latest release
docker run --rm -p 8000:8000 flamapy/flamapy-rest
```

Then open:

* API home: <http://localhost:8000/>
* Swagger UI / API docs: <http://localhost:8000/docs/>

To pin a specific version, use its tag (matching a release, e.g. `v2.6.0`):

```bash
docker run --rm -p 8000:8000 flamapy/flamapy-rest:v2.6.0
```

Run it detached and give the container a name so it's easy to stop later:

```bash
docker run -d --name flamapy-rest -p 8000:8000 flamapy/flamapy-rest
docker logs -f flamapy-rest   # follow the logs
docker stop flamapy-rest      # stop it
docker rm flamapy-rest        # remove it
```

### Option 2 — Build the Docker image from source

If you want to run your local changes, clone the repo and build the image yourself. A helper script
is provided that builds, runs, and (on exit) cleans up the container and image:

```bash
# Linux / macOS
./start-server.sh

# Windows
start-server.cmd
```

Or do it by hand:

```bash
docker build --tag flamapy-rest .
docker run --rm -p 8000:8000 flamapy-rest
```

### Option 3 — Install from PyPI and run locally

The API is also published on PyPI as [`flamapy-rest`](https://pypi.org/project/flamapy-rest/)
(requires **Python 3.11+**). Because the WSGI entrypoint lives in `app.py`, clone the repo to get it:

```bash
git clone https://github.com/flamapy/flamapy-rest.git
cd flamapy-rest
pip install .

# Production server
gunicorn --bind 0.0.0.0:8000 app:app

# …or the Flask development server
python -m flask run --host=0.0.0.0
```

<p align="right">(<a href="#top">back to top</a>)</p>

## Usage

Every public operation of FLAMAPY's `FLAMAFeatureModel` facade is exposed as a `POST` endpoint under
`/api/v1/operations/<operation_name>`. Each call uploads a feature model file (e.g. UVL) as
multipart form data; some operations also accept an optional `feature` or `configuration` parameter.

```bash
# Example: count the number of valid configurations of a model
curl -X POST http://localhost:8000/api/v1/operations/configurations_number \
  -F "model=@resources/models/simple/valid_model.uvl"
```

The full, interactive list of endpoints — with parameters and "try it out" support — is available
in the Swagger UI at <http://localhost:8000/docs/>.

<p align="right">(<a href="#top">back to top</a>)</p>

## API Documentation

All documentation is registered with Swagger UI and OAS 3.0, served at
[`/docs/`](http://localhost:8000/docs/). It is generated dynamically by
[Flasgger](https://github.com/flasgger/flasgger) from the route docstrings and method signatures, so
**don't forget to document your code in the route files** — new operations show up automatically.

<p align="right">(<a href="#top">back to top</a>)</p>

## Contributing

Contributions are welcome. This repo enforces
[Conventional Commits](https://www.conventionalcommits.org/) on pull request titles, and runs Ruff,
mypy, and pytest in CI.

```bash
pip install .[dev]   # install dev tooling

ruff check .         # lint
mypy -p flamapy      # static type checking
pytest               # tests
```

<p align="right">(<a href="#top">back to top</a>)</p>
