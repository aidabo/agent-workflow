.PHONY: test check migration-check behavior-lock merge-gate-help merge-observe-help

test:
	for test in tests/test_*.py; do python3 -m unittest "$$test" -v || exit 1; done
	python3 -m unittest cross-review/test_status.py -v

check: test
	bash scripts/check-syntax.sh

migration-check:
	bash scripts/check-copy-manifest.sh

behavior-lock:
	bash scripts/behavior-lock.sh

merge-gate-help:
	bin/agent-merge-gate --help

merge-observe-help:
	bin/agent-merge-observe --help
