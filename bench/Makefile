.PHONY: help bench bench-static bench-spa bench-web3 analyze balances \
        setup-mm setup-mm-force verify-mm ab clean
.DEFAULT_GOAL := help

# Run from project root so module imports resolve.
PY := cd .. && python

help:
	@echo "bench targets:"
	@echo "  make bench               run every fixture the wallet/funding allows"
	@echo "  make bench-static        run static_ui fixtures only"
	@echo "  make bench-spa           run spa_dynamic fixtures only"
	@echo "  make bench-web3          run web3_defi fixtures (needs funding + setup-mm)"
	@echo "  make analyze             aggregate latest results into a table"
	@echo "  make balances            print bench wallet balances on every testnet"
	@echo "  make setup-mm            bootstrap MM in bench_profile/ with BENCH_SEED"
	@echo "  make setup-mm-force      same but wipe bench_profile/ first"
	@echo "  make verify-mm           confirm MM shows BENCH_ADDRESS_0"
	@echo "  make ab A=path B=path    A/B harness on two SYSTEM_PROMPT files"
	@echo "  make clean               wipe results/runs/"

bench:
	$(PY) -m bench.runner --all

bench-static:
	$(PY) -m bench.runner --category static_ui

bench-spa:
	$(PY) -m bench.runner --category spa_dynamic

bench-web3:
	$(PY) -m bench.runner --category web3_defi

analyze:
	$(PY) -m bench.analyze

balances:
	$(PY) -m bench.runner.web3_assert

setup-mm:
	$(PY) -m bench.setup_mm --headless -v

setup-mm-force:
	$(PY) -m bench.setup_mm --headless -v --force

verify-mm:
	$(PY) -m bench.verify_mm

ab:
	@if [ -z "$(A)" ] || [ -z "$(B)" ]; then \
		echo "usage: make ab A=path/to/promptA.txt B=path/to/promptB.txt"; \
		exit 1; \
	fi
	$(PY) -m bench.ab $(A) $(B)

clean:
	rm -rf results/runs/*.jsonl
	@echo "results/runs/ wiped"
