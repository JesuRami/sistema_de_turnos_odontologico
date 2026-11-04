# Tasks — C-13 `reportes-admin-export`

> **Estado:** código y tests escritos, **sin ejecutar** (el entorno donde se
> generaron no tenía Postgres, Redis, Docker, pytest ni node_modules). Ninguna
> casilla de verificación se marca hasta correr el gate local (7.2).

> TDD rojo → verde por rebanada vertical: un seam, un test que se corre y se ve
> fallar, el mínimo código, repetir (skill `tdd`). Backend contra Postgres 15 +
> Redis 7 reales (regla 9). Datos solo sintéticos (regla 13). TypeScript sin
> `any` (regla 5). Governance ALTO: cada grupo cierra con evidencia pegada en el
> PR (comando + resultado).

## 0. Seams a confirmar antes de escribir tests (skill `tdd`)

| # | Seam (interfaz pública) | Atrapa | No atrapa |
|---|---|---|---|
| S1 | `GET /api/reports/*` con pytest + httpx, Postgres real | números desde eventos, RBAC, aislamiento, rango, CSV | render de la UI |
| S2 | `GET /api/audit/appointments` y `GET /api/exports/full` (misma pila) | filtros, cursor, ZIP, formatos, traza `data_exported` | rendimiento de red |
| S3 | API de turnos existente (crear, mover, transicionar) leyendo `/events` | sellado de la instantánea en cada evento | internos de `record_event` |
| S4 | Esquema: `tests/models` + `test_migrations.py` | columnas, FKs, índice, trigger intacto, upgrade/downgrade | consultas de negocio |
| S5 | Página `ReportsPage` con Testing Library, borde HTTP simulado | pestañas, estados, descargas, rol | contratos reales del backend |
| S6 | Volumen sintético vía API + `EXPLAIN` | uso de índice y tiempos | carga real de producción |

- [x] 0.1 Confirmar los seams S1–S6 y las definiciones de métricas (D4) y de
  `data_exported` (D8) con el PO antes de empezar la sección 1.

## 1. Migración `c13_event_slot` y sellado de instantánea (S4, S3)

- [ ] 1.1 Test de esquema: `appointment_event` tiene `slot_starts_at`,
  `slot_ends_at`, `professional_id`, `chair_id` nulables, FKs compuestas
  intra-tenant y el trigger sigue rechazando UPDATE/DELETE. Verifica:
  `tests/models/test_appointment_event_slot_db.py` en rojo y luego verde.
- [ ] 1.2 Implementar la revisión con encabezado de reglas 3/11: columnas, FK
  `NOT VALID` → `VALIDATE`, `CREATE INDEX CONCURRENTLY (clinic_id,
  slot_starts_at)`, `ALTER TYPE auth_event_type ADD VALUE 'data_exported'` en
  bloque autocommit; actualizar `test_migrations.py`. Verifica: `upgrade →
  downgrade -1 → upgrade` limpio y drift vacío.
- [ ] 1.3 Test por API: crear, reprogramar, marcar `present` y cancelar un
  turno; cada evento de `/events` trae la instantánea esperada (literales del
  spec, no recalculados). Verifica: `tests/modules/test_appointment_event_slot.py`.
- [ ] 1.4 Sellar la instantánea en `record_event` (único punto de escritura) y
  agregar `AuthEventType.DATA_EXPORTED`. Verifica: 1.3 verde y suites de C-05
  sin regresiones.

## 2. Reportes: base común y ocupación (S1)

- [ ] 2.1 Test: RBAC (admin 200, recepción y odontólogo 403, sin sesión 401),
  aislamiento entre clínicas, `invalid_range`, `range_too_large`, parámetros
  desconocidos 422. Verifica: `tests/modules/test_reports_access.py`.
- [ ] 2.2 Implementar schemas (`extra='forbid'`), dependencia admin, parseo de
  rango en zona de la clínica y router fino. Verifica: 2.1 verde.
- [ ] 2.3 Test del estado final por último evento, incluido el caso "se altera
  `appointment.status` a mano y el reporte no cambia". Verifica:
  `tests/modules/test_reports_event_derived.py`.
- [ ] 2.4 Test de ocupación con los escenarios del spec (25 %, cancelado, bloqueo
  de 2 h, sin capacidad, sobreturnos aparte, `group_by` profesional y sillón).
  Verifica: `tests/modules/test_reports_occupancy.py`.
- [ ] 2.5 Implementar consulta agregada (D1/D5) y cálculo de capacidad en Python
  (plantilla activa menos bloqueos, hora local). Verifica: 2.3 y 2.4 verdes.

## 3. Ausentismo y cancelaciones (S1)

- [ ] 3.1 Test de ausentismo: `no_show` ≠ cancelación tardía, tasas (6/1/2/1 →
  0.2), cancelación en ventana fuera del denominador, denominador 0. Verifica:
  `tests/modules/test_reports_absenteeism.py`.
- [ ] 3.2 Implementar el reporte. Verifica: 3.1 verde.
- [ ] 3.3 Test de cancelaciones por motivo: todos los motivos presentes (0 si no
  hay), corte tardía/en ventana. Verifica:
  `tests/modules/test_reports_cancellations.py`.
- [ ] 3.4 Implementar el reporte. Verifica: 3.3 verde.

## 4. CSV de reportes (S1)

- [ ] 4.1 Test: `format=csv` devuelve `text/csv`, encabezados fijos, mismas cifras
  que el JSON, escape de fórmulas, `format=xml` → `422 invalid_format`.
  Verifica: `tests/modules/test_reports_csv.py`.
- [ ] 4.2 Implementar el serializador CSV compartido (`app/common/csv_export.py`).
  Verifica: 4.1 verde.

## 5. Auditoría y exportación (S2)

- [ ] 5.1 Test de auditoría: filtros, cursor sin repetir ni omitir filas, sin PII,
  recepción 403, aislamiento. Verifica: `tests/modules/test_audit_feed_api.py`.
- [ ] 5.2 Implementar `GET /api/audit/appointments` (módulo `appointments`,
  `paginate_entities`). Verifica: 5.1 verde.
- [ ] 5.3 Test de exportación: ZIP con 3 archivos en CSV y JSON, solo la clínica
  propia, archivados/fusionados, escape de fórmulas, 403 para no admin, evento
  `data_exported` sin PII. Verifica: `tests/modules/test_export_full_api.py`.
- [ ] 5.4 Implementar la exportación por lotes con `StreamingResponse` y el
  registro en `auth_event`. Verifica: 5.3 verde.
- [ ] 5.5 Test de volumen (S6): 1 000 turnos sintéticos; los reportes responden
  bajo 2 s (la prueba de `EXPLAIN` queda como verificación manual); el export no carga todo en
  memoria. Verifica: `tests/modules/test_reports_perf.py`.

## 6. Frontend (S5)

> Antes de codear, cargar `frontend-design` (plan de tokens + wireframe),
> `vercel-react-best-practices` y, al final, pasar `web-design-guidelines`.

- [ ] 6.1 Tipos y cliente de API de reportes, auditoría y exportación en
  `features/reports` (sin `any`). Verifica: `tsc --noEmit` limpio.
- [ ] 6.2 Test de `ReportsPage`: solo admin, pestañas, rango por defecto, estados
  de carga/vacío/error, nota de capacidad vigente. Verifica:
  `ReportsPage.test.tsx` rojo → verde.
- [ ] 6.3 Implementar la página, hooks de datos y la ruta `/admin/reportes` con
  su entrada de menú solo para admin. Verifica: 6.2 verde.
- [ ] 6.4 Test y componente de descargas (CSV por reporte, ZIP completo con la
  sesión, sin credenciales en la URL). Verifica: tests de descarga verdes.
- [ ] 6.5 Test y componente de Auditoría con filtros y "Cargar más". Verifica:
  tests verdes.
- [ ] 6.6 Revisión de accesibilidad y diseño (`web-design-guidelines`): foco
  visible, contraste, teclado, `prefers-reduced-motion`. Verifica: hallazgos
  `archivo:línea` resueltos.

## 7. Cierre

- [x] 7.1 Actualizar la ficha C-13 en `CHANGES.md`: quitar WhatsApp mensual y
  conversión de lista de espera, y registrarlos como pendientes de C-10/C-12
  (por ejemplo, como tareas explícitas de esos changes).
- [ ] 7.2 Gate local completo: `pytest`, `ruff check`, `black --check`, `mypy`,
  `npm run lint`, `tsc --noEmit`, tests del frontend. Verifica: todo verde,
  salida pegada en el PR.
- [ ] 7.3 Revisión con la skill `code-review` (ejes Standards y Spec).
- [ ] 7.4 Preparar mensajes de commit (Conventional Commits, sin co-autoría) y
  `/opsx-archive c-13-reportes-admin-export`. No se ejecuta `git commit` sin
  pedido explícito.
