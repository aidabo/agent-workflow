.PHONY: test check

test:
	python3 -m unittest discover -s tests -v
	python3 -m unittest cross-review/test_status.py -v

check: test
	bash -n $$(find agent-notify cross-review bin -type f -name '*.sh' -o -type f -path 'bin/*' | sort)
	node --check agent-notify/hooks/native-hook.mjs
	python3 -m py_compile $$(find agent-notify cross-review src tests -type f -name '*.py' | sort)
