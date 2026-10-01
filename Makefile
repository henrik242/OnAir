VENV := .venv
PYTHON := $(VENV)/bin/python

default: $(VENV) typecheck
	$(PYTHON) setup.py py2app

# Create the build virtualenv and install deps into it. Using a venv avoids
# Homebrew's "externally-managed-environment" (PEP 668) error and is what
# py2app expects anyway.
$(VENV): requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	touch $(VENV)

# Run from source using the build venv (the system Python has no rumps).
run: $(VENV)
	$(PYTHON) OnAir.py

debug: $(VENV)
	$(PYTHON) OnAir.py --debug

archive:
	cd dist && tar czvf OnAir.app.tgz *.app

clean:
	rm -rf dist build $(VENV)

format: $(VENV)
	$(PYTHON) -m pip install black
	$(PYTHON) -m black -l 140 .

typecheck: $(VENV)
	$(PYTHON) -m pip install pyright
	$(PYTHON) -m pyright

.PHONY: default run debug archive clean format typecheck
