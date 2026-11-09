.PHONY: install api web seed test test-emulator lint synth eval

install:
	cd api && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
	cd web && npm install
	cd firestore-tests && npm install

api:
	cd api && APP_ENV=local DEMO_MODE=true .venv/bin/uvicorn loopcloser.main:create_app --factory --reload --port 8080

web:
	cd web && NEXT_PUBLIC_API_URL=http://localhost:8080 npm run dev

seed:
	curl -s -X POST localhost:8080/api/demo/seed -H 'x-demo-role: supervisor' -H 'content-type: application/json' -d '{"n":1000}'

lint:
	cd api && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd web && npm run lint && npm run typecheck

test:
	cd api && .venv/bin/python -m pytest
	cd web && npm test

test-emulator:
	firebase emulators:exec --only firestore --project demo-loopcloser \
	  "cd firestore-tests && npm test && cd ../api && .venv/bin/python -m pytest -m emulator"

synth:
	cd api && .venv/bin/python -m loopcloser.synth.generator --n 1000 --seed 42 --out ../data/synthetic

eval:
	cd api && .venv/bin/python ../eval/run_eval.py
