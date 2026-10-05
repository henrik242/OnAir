# uv run creates and syncs .venv from uv.lock; --locked fails if the lock is stale.
RUN := uv run --locked

default: typecheck
	$(RUN) python setup.py py2app

# Run from source using the project venv (the system Python has no rumps).
run:
	$(RUN) python OnAir.py

debug:
	$(RUN) python OnAir.py --debug

archive:
	cd dist && tar czvf OnAir.app.tgz *.app

clean:
	rm -rf dist build .venv

format:
	$(RUN) black .

typecheck:
	$(RUN) pyright

.PHONY: default run debug archive clean format typecheck
