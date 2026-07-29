PYTHON ?= .venv/bin/python
BOOTSTRAP_PYTHON ?= python3

.PHONY: bootstrap sandbox-image sandbox-check test validate package

bootstrap:
	@$(BOOTSTRAP_PYTHON) -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ is required (set BOOTSTRAP_PYTHON)"'
	$(BOOTSTRAP_PYTHON) -m venv --clear .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -e '.[dev]'

sandbox-image:
	$(PYTHON) -m tycho.workspace.sandbox build

sandbox-check:
	$(PYTHON) -m tycho.workspace.sandbox doctor

test:
	$(PYTHON) -m pytest -q -ra

package:
	mkdir -p dist
	$(PYTHON) -m pip wheel . --no-deps --wheel-dir dist
	$(PYTHON) scripts/validate_wheel.py dist

validate: test package
	$(PYTHON) scripts/validate_public.py
