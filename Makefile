PYTHON ?= python3
SUDO ?= sudo
RUNS ?= 1
CONDITIONS ?= heavy

.PHONY: help check-env smoke experiments aggregate plots clean-mininet

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

check-env: ## Check Python and required project scripts
	$(PYTHON) --version
	@test -f experiments/run_experiments.py
	@test -f topology/topo.py
	@echo "Project files found. Ensure Mininet, Open vSwitch, Ryu, and iperf are installed."

smoke: ## Run one short heavy-load trial (override RUNS/CONDITIONS as needed)
	$(SUDO) $(PYTHON) experiments/run_experiments.py --runs $(RUNS) --conditions $(CONDITIONS)

experiments: ## Run the full experiment matrix
	$(SUDO) $(PYTHON) experiments/run_experiments.py

aggregate: ## Aggregate experiment output into docs/results/
	$(PYTHON) experiments/aggregate.py

plots: ## Generate figures from aggregated experiment output
	$(PYTHON) experiments/plot_results.py

clean-mininet: ## Remove stale Mininet network state
	$(SUDO) mn -c
