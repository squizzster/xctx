.PHONY: test test-fast test-unit test-integration release-test

test-fast:
	python3 -m pytest -q -m "not slow" --durations=20

test-unit:
	python3 -m pytest -q -m unit --durations=20

test-integration:
	python3 -m pytest -q -m "integration and not slow" --durations=20

test:
	python3 -m pytest -q --durations=30

release-test:
	python3 -m pytest -q -m release --durations=30
