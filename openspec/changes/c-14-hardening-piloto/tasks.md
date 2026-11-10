# Tasks — C-14 `hardening-piloto`

> Governance ALTO. Leyenda: `[x]` implementado en este change; **Verificado acá** = corrido en el
> entorno del change; **Pendiente gate** = corre en CI/contenedor (el entorno del change no tenía
> FastAPI/SQLAlchemy/asyncpg ni `node_modules`, y sin red para instalarlos).

## 0. Prerrequisitos
- [x] 0.1 C-06, C-11, C-12 y C-13 archivados con todas sus tasks; C-12 cerrado en `CHANGES.md` (gate 2026-11-09: 1760 tests backend, 234 frontend; E2E `waitlist.spec.ts` verde 2026-11-10).

## 1. Borde HTTP y errores (D1, D3, D5, D6)
- [x] 1.1 `app/core/middleware.py`: request-id, log de acceso por plantilla de ruta, 500 uniforme, headers seguros, hosts, rate-limit global Redis con degradación. **Verificado acá**: `tests/core/test_middleware.py` (26 tests verdes).
- [x] 1.2 `app/core/logs.py`: logs JSON redactados (teléfono, email, DNI, JWT, tokens). **Verificado acá**: `tests/core/test_logs_redaction.py` (17 verdes).
- [x] 1.3 `app/common/exceptions.py`: SQLSTATE → 409/503, 422 del personal sin `input`, 404/405 cortos, `/api/waitlist-offer/` público. Tests: `tests/test_http_hardening.py`, `tests/core/test_db_timeouts_db.py`. **Pendiente gate**.
- [x] 1.4 Settings (`ALLOWED_HOSTS`, HSTS, logs, timeouts, `APP_DB_*`, cupo webhook) + validación de prod. Tests: `tests/core/test_settings_hardening.py`; se ajustó `test_settings_reminders.py`. **Pendiente gate**.
- [x] 1.5 Timeouts por conexión en API y worker (`core/database.py`). **Pendiente gate** (test con lock real).
- [x] 1.6 Bearer estricto + `WWW-Authenticate`; guardia de RBAC `tests/test_route_protection.py`. **Pendiente gate**.
- [x] 1.7 Cupo de firmas inválidas del webhook. Test: `tests/modules/test_webhook_signature_budget.py`. **Pendiente gate**.

## 2. Datos (D7, D8)
- [x] 2.1 Migración `c14_hardening_pilot` + `app/ops/db_privileges.py` + `app/ops/db_roles.py` (SCRAM calculado en Python). **Verificado acá contra PostgreSQL 16 real**: grants (sin DELETE/TRUNCATE, append-only sin UPDATE ni `FOR UPDATE`, `alembic_version` solo lectura, default privileges para tablas futuras), login SCRAM del usuario, downgrade con el rol referenciado desde otra base (NOTICE) y re-grant idempotente. Tests: `tests/models/test_app_writer_role_db.py`, `test_ciclo_de_c14_con_datos_de_c12`. **Pendiente gate** (PG 15 + alembic).
- [x] 2.2 `clinic.whatsapp_monthly_alert_micros` + política `whatsapp_monthly_alert_usd`; ajustado `test_clinic_policies_api.py`.

## 3. Reportes del piloto (D8, D9, D10)
- [x] 3.1 `GET /api/reports/pilot` (+CSV). Test: `tests/modules/test_reports_pilot.py`.
- [x] 3.2 `GET /api/reports/whatsapp/budget`. Test: `tests/modules/test_whatsapp_budget.py`.
- [x] 3.3 `GET /api/exports/patients/{id}`. Test: `tests/modules/test_patient_export_api.py`.
- [x] 3.4 **Bug real hallado**: `to_json_value` no serializaba `datetime.time` → la exportación completa JSON fallaba con entradas de lista de espera con franja (C-12/C-13). Corregido + test de regresión.

## 4. Frontend (D11)
- [x] 4.1 Reintentos (`shared/api/retry.ts`), estado de red + banner, `ErrorBoundary`, `Skeleton`.
- [x] 4.2 Validaciones (`shared/forms/validators.ts`) en lista de espera y contacto de la reserva (sin romper el contrato de C-07 de teléfono inválido con email).
- [x] 4.3 Cola de reintentos (confirmación/asistencia) + indicador; agenda imprimible `/agenda/imprimir`; origen del turno en el detalle.
- [x] 4.4 Pestaña Piloto, banner de presupuesto (admin), umbral en Políticas.
- [x] 4.5 Tests Vitest nuevos (retry, red, cola, validadores, ErrorBoundary, impresión, piloto, presupuesto, detalle offline, políticas) y ajuste de `ReportsPage.test.tsx` (7 pestañas). **Verificado acá**: `tsc --strict` sin errores de sintaxis ni de tipos propios (con stubs de librerías). **Pendiente gate**: `npm run typecheck && npm test`.

## 5. E2E y CI (D12)
- [x] 5.1 `e2e/critical-circuit.spec.ts`: reserva → recordatorio → confirmación → presente + agenda imprimible.
- [x] 5.2 `.github/workflows/ci-e2e.yml` (stack real, API/worker con `app_writer`, proveedores fake); Vitest al job principal de `ci-frontend.yml`; se elimina el stub `playwright-smoke`. **Pendiente gate**.

## 6. Operación y docs
- [x] 6.1 Compose: `migrate` crea el usuario de la app; `api`/`worker` con él; prod exige `APP_DB_PASSWORD`. **Verificado acá**: `docker compose config` dev y prod.
- [x] 6.2 nginx con headers seguros y CSP; uvicorn `--no-access-log`.
- [x] 6.3 `docs/piloto/` (checklist, backups PITR, privacidad/retención), `ops/backup/`, `.env.example`.

## 7. Gate (pendiente, antes de archivar)
- [ ] 7.1 `pytest -q` (py3.12 + PG 15 + Redis 7), `ruff check backend`, `black --check backend` (24.x), `mypy backend`.
- [ ] 7.2 `npm run typecheck && npm test && npm run build`.
- [ ] 7.3 `npx playwright test` (CI `e2e` verde).
- [ ] 7.4 Aprobación de las 8 Open Decisions de `proposal.md` y `/opsx:archive c-14-hardening-piloto`.

## Notas de verificación
- `ruff check backend`: limpio (ruff 0.16). `black --check`: limpio en todo archivo tocado (black local 26.x; solo 2 archivos previos difieren por versión, no se tocaron). Se evitó `text("""…""")` multilínea, que black 24 y 26 formatean distinto.
- mypy `--strict` sin errores en los módulos nuevos (resto: `Any` por falta de dependencias en el entorno).
