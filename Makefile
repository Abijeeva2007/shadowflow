# ShadowFlow - hackathon demo Makefile (macOS/Linux).
# Windows: see scripts\setup_windows.bat and scripts\run_windows.ps1

# Prefer an interpreter that satisfies the pinned deps (3.11), fall back to
# python3. Override with:  make setup PY=/path/to/python3.11
PY       ?= $(shell command -v python3.11 || command -v python3.12 || command -v python3.10 || command -v python3)
BACKEND  := backend
FRONTEND := frontend
# VPY is relative to backend/ (always used after 'cd backend &&')
VPY      := ./.venv/bin/python

.PHONY: help setup data test run run-backend run-frontend verify demo-metrics benchmark clean dev-urls

help:
	@echo "ShadowFlow targets:"
	@echo "  make setup         create venv, install backend + frontend deps"
	@echo "  make data          generate synthetic data + run the detection pipeline"
	@echo "  make test          run the pytest suite"
	@echo "  make run           backend :8000 + frontend :3000 (blocking; Ctrl-C stops both)"
	@echo "  make run-backend   backend only (foreground)"
	@echo "  make run-frontend  frontend only (foreground)"
	@echo "  make verify        health-check both servers"
	@echo "  make demo-metrics  print pipeline + adversary + federation numbers"
	@echo "  make benchmark     run the 10-seed x 3-noise benchmark (~2-3 min)"
	@echo "  make clean         remove venv, node_modules, and generated data"

setup:
	@echo "==> creating backend venv and installing backend deps"
	@$(PY) -c 'import sys; ok = sys.version_info >= (3, 10); print("using python", sys.version.split()[0]) if ok else sys.exit(f"Python 3.10+ required (found {sys.version.split()[0]}); rerun with PY=/path/to/python3.11")'
	cd $(BACKEND) && $(PY) -m venv .venv
	$(BACKEND)/.venv/bin/pip install --upgrade pip
	$(BACKEND)/.venv/bin/pip install -r $(BACKEND)/requirements-dev.txt
	@echo "==> installing frontend deps (npm install)"
	cd $(FRONTEND) && npm install
	@echo "==> done. Next: make data && make run"

data:
	cd $(BACKEND) && $(VPY) generate_data.py
	cd $(BACKEND) && $(VPY) -c "from engine.pipeline import run_pipeline; st = run_pipeline(); print('pipeline ok:', len(st.rings), 'rings,', st.filter_counts['alerts_before'], '->', st.filter_counts['alerts_after'], 'alerts')"

test:
	cd $(BACKEND) && $(VPY) -m pytest tests/ -q

# One blocking command that starts both servers; Ctrl-C stops them.
run:
	cd $(BACKEND) && ./.venv/bin/uvicorn main:app --port 8000 & \
	cd $(FRONTEND) && npx next dev -p 3000 & \
	sleep 2 && echo "" && echo "  backend  -> http://localhost:8000  (first start needs ~15s)" && \
	echo "  frontend -> http://localhost:3000" && echo "" && wait

run-backend:
	cd $(BACKEND) && ./.venv/bin/uvicorn main:app --port 8000

run-frontend:
	cd $(FRONTEND) && npx next dev -p 3000

verify:
	@curl -sf http://localhost:8000/api/health > /dev/null && echo "backend  OK  http://localhost:8000" || echo "backend  DOWN (make run-backend)"
	@curl -sf http://localhost:3000 > /dev/null && echo "frontend OK  http://localhost:3000" || echo "frontend DOWN (make run-frontend)"

demo-metrics:
	cd $(BACKEND) && $(VPY) print_metrics.py

benchmark:
	cd $(BACKEND) && $(VPY) benchmark.py

clean:
	rm -rf $(BACKEND)/.venv $(FRONTEND)/node_modules
	rm -f $(BACKEND)/data/transactions_*.csv $(BACKEND)/data/ground_truth.json $(BACKEND)/data/metrics.json
	rm -rf $(BACKEND)/data/dossiers

dev-urls:
	@echo "Overview:   http://localhost:3000"
	@echo "Rings:      http://localhost:3000/rings"
	@echo "Case view:  http://localhost:3000/case/CYCLE-01"
	@echo "Federation: http://localhost:3000/federation"
	@echo "Adversary:  http://localhost:3000/adversary"
	@echo "Backend:    http://localhost:8000/api/summary"
