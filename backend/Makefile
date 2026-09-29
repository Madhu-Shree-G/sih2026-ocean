# OceanView3D backend (macOS / Linux)
PYTHON := .venv/bin/python

.PHONY: setup data serve test smoke clean

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt cmocean
	@echo "\nSetup complete. Next: make data"

data:
	$(PYTHON) scripts/generate_sample_data.py

serve:
	$(PYTHON) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	$(PYTHON) -m pytest tests

smoke:
	$(PYTHON) scripts/smoke_test.py

clean:
	rm -rf data/zarr/*.zarr data/cache/* data/*.db data/*.db-wal data/*.db-shm
