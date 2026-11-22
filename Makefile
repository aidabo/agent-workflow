.PHONY: test check

test:
	python3 -m unittest discover -s tests -v
	python3 -m unittest cross-review/test_status.py -v

check: test
	bash scripts/check-syntax.sh
