VENV := .venv
PYTHON := $(VENV)/bin/python

default: $(VENV)
	$(PYTHON) setup.py py2app

# Create the build virtualenv and install deps into it. Using a venv avoids
# Homebrew's "externally-managed-environment" (PEP 668) error and is what
# py2app expects anyway.
$(VENV): requirements.txt
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	touch $(VENV)

archive:
	cd dist && tar czvf OnAir.app.tgz *.app

clean:
	rm -rf dist build $(VENV)

format: $(VENV)
	$(PYTHON) -m pip install black
	$(PYTHON) -m black -l 140 .

.PHONY: default archive clean format
