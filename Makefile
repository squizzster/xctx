.PHONY: test test-fast test-unit test-integration package-install-smoke release-test

test-fast:
	python3 -m pytest -q -m "not slow" --durations=20

test-unit:
	python3 -m pytest -q -m unit --durations=20

test-integration:
	python3 -m pytest -q -m "integration and not slow" --durations=20

test:
	python3 -m pytest -q --durations=30

package-install-smoke:
	python3 -m pytest -q tests/test_framework_release_gate.py::test_package_install_entrypoint_smoke --durations=10

release-test:
	python3 -m pytest -q -m release --durations=30
