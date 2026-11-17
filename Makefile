PYTHON ?= python3.12

.PHONY: check test
check:
	$(PYTHON) scripts/check_repository.py
	git diff --check
	git diff --cached --check

test:
	$(PYTHON) -m unittest discover -s tests -v
