.ONESHELL:

.PHONY: build
build:
	rm -rf dist
	python -m build

upload-testpypi:
	python3 -m twine upload --repository testpypi dist/*

upload-pypi:
	python3 -m twine upload --repository pypi dist/*

lint:
	ruff check .

mypy:
	mypy app.py flamapy

test:
	python -m pytest -sv

cov:
	coverage run --source=flamapy,app -m pytest
	coverage report
	coverage html

start:
	./start-server.sh
