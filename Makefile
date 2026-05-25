.PHONY: test release-test

test:
	python3 -m pytest -q

release-test: test
