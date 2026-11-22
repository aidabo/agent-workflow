.PHONY: test check migration-check behavior-lock

test:
	python3 -m unittest discover -s tests -v
	python3 -m unittest cross-review/test_status.py -v

check: test
	bash scripts/check-syntax.sh

migration-check:
	bash scripts/check-copy-manifest.sh

behavior-lock:
	bash scripts/behavior-lock.sh
