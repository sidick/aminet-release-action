# Local dev + CI use the same targets. Override PYTHON if you want to skip
# the auto-created .venv (e.g. `make test PYTHON=python3` when something
# else already manages your interpreter).

PYTHON ?= .venv/bin/python
IMAGE  ?= aminet-release-action:dev

.PHONY: help test compile docker-build smoke ci clean lftp-check

help:
	@echo "Targets:"
	@echo "  test          run pytest (auto-creates .venv on first run)"
	@echo "  compile       py_compile syntax check on action/*.py"
	@echo "  docker-build  build the action's Docker image as $(IMAGE)"
	@echo "  smoke         end-to-end FTP smoke test against pyftpdlib"
	@echo "  ci            compile + test + docker-build + smoke"
	@echo "  clean         remove .venv, caches, and __pycache__ dirs"
	@echo ""
	@echo "PYTHON=$(PYTHON)  (override to use a different interpreter)"

test: .venv/.installed
	$(PYTHON) -m pytest

compile: .venv/.installed
	$(PYTHON) -m py_compile action/*.py

docker-build:
	docker build -t $(IMAGE) action

smoke: .venv/.installed lftp-check
	PYTHON=$(PYTHON) scripts/smoke.sh

ci: compile test docker-build smoke

clean:
	rm -rf .venv .pytest_cache action/__pycache__ tests/__pycache__
	find . -name '*.pyc' -delete

# The sentinel file is touched after a successful install; re-edits of
# requirements-dev.txt invalidate it via Make's normal timestamp logic.
.venv/.installed: requirements-dev.txt
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements-dev.txt
	touch $@

lftp-check:
	@command -v lftp >/dev/null 2>&1 || { \
		echo "lftp not found. Install:" >&2; \
		echo "  macOS:  brew install lftp" >&2; \
		echo "  Ubuntu: sudo apt-get install -y lftp" >&2; \
		exit 1; \
	}
