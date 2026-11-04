#!/usr/bin/env bash
# Verificación local de C-13. Requiere el stack de desarrollo (Postgres 15 + Redis 7).
set -euo pipefail
cd "$(dirname "$0")"

echo "== Backend =="
cd backend
ruff check .
black --check .
mypy app
pytest tests/test_migrations.py tests/models/test_appointment_event_slot_db.py \
  tests/modules/test_appointment_event_slot.py -q
pytest tests/modules/test_reports_access.py tests/modules/test_reports_event_derived.py \
  tests/modules/test_reports_occupancy.py tests/modules/test_reports_absenteeism.py \
  tests/modules/test_reports_cancellations.py tests/modules/test_reports_csv.py \
  tests/modules/test_audit_feed_api.py tests/modules/test_export_full_api.py \
  tests/modules/test_reports_perf.py -q
pytest -q   # regresión completa (C-03..C-06)
cd ..

echo "== Frontend =="
cd frontend
npm ci
npm run typecheck
npx vitest run
cd ..

echo "== OpenSpec =="
openspec validate c-13-reportes-admin-export || true
echo "OK: si todo pasó, marcá las tasks en tasks.md y ejecutá /opsx-archive."
