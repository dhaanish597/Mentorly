.PHONY: test-foundations test-backend test-worker test-isolation-live test-frontend check-contracts check-secrets regenerate-openapi check

test-foundations:
	PYTHONPATH=backend:. python3 -m unittest discover -s backend/tests/unit -p "test_exercises_oracles.py" -v
	python3 -m compileall -q backend exec_worker

test-backend:
	PYTHONPATH=backend:. pytest backend/tests -v

test-worker:
	PYTHONPATH=backend:. python3 -m unittest discover -s exec_worker/tests -p "test_*.py" -v
	PYTHONPATH=backend:. pytest exec_worker/tests -v -rs

test-isolation-live:
	VCC_RUN_LIVE_GVISOR_ACCEPTANCE=1 PYTHONPATH=backend:. pytest exec_worker/tests/test_sandbox_isolation.py -v

test-frontend:
	cd frontend && npm run typecheck && npx vitest run && npm run build

check-contracts:
	PYTHONPATH=backend:. python3 backend/scripts/export_openapi.py --check
	PYTHONPATH=backend:. python3 scripts/check_schema_drift.py --self-test

regenerate-openapi:
	PYTHONPATH=backend:. python3 backend/scripts/export_openapi.py

check-secrets:
	python3 scripts/check_secrets.py

check: check-contracts check-secrets test-foundations test-backend test-worker test-frontend
