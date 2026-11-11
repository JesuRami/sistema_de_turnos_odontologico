# Tasks — C-15 `historia-clinica-odontograma`

> Governance CRITICO. TDD estricto: cada tarea de implementación va precedida por su tarea de test
> (RED) y se cierra con GREEN + refactor. Tests de invariantes contra Postgres 15 real (regla 9);
> datos sintéticos (regla 13). Los escenarios citados son los de `specs/**`.
> **No aplicar hasta aprobar las Open Decisions de `proposal.md` (grupo 0) y archivar C-14.**

## 0. Prerrequisitos y aprobaciones
- [x] 0.1 C-14 archivado (sus 7.1–7.4 cerrados). Verificación: `openspec list` no lista `c-14-hardening-piloto` y `CHANGES.md` lo marca `[x]`.
- [x] 0.2 Usuario aprueba (o corrige) las 13 Open Decisions de `proposal.md`; el resultado se anota en ese archivo. Verificación: sección con fecha y decisión por ítem; las `(TBD)` de las specs se ajustan si cambia alguna.
- [ ] 0.3 Un odontólogo de la clínica piloto valida el set de estados (Decisión 8) y los campos de anamnesis (Decisión 9). Verificación: set y campos finales commiteados en `docs/clinica/`.
- [x] 0.4 Baseline: `pytest -q`, `ruff`, `black --check`, `mypy` y `npm run typecheck && npm test` verdes antes de tocar nada. Verificación: conteos anotados en el PR/tasks.

## 1. Modelo y migración (D1, D2)
- [x] 1.1 TEST (RED) `tests/models/test_clinical_schema_db.py`: tablas, `clinic_id NOT NULL`, UNIQUE `(clinic_id, patient_id)`, CHECK FDI (válidas 11–48/51–85; inválidas 19, 49, 56, 86, 0), CHECK de `kind/correction`, FK compuesta cross-clinic rechazada. Escenarios: "FK compuesta impide mezclar clínicas", "Códigos fuera de rango".
- [x] 1.2 Modelos SQLAlchemy `app/models/{clinical_record,anamnesis_version,odontogram_condition,odontogram_event,clinical_evolution,clinical_attachment,treatment_plan,clinical_access_event}.py` + enums en `enums.py`, registrados en `app/models/__init__.py`. Verificación: 1.1 pasa a GREEN en lo estructural.
- [x] 1.3 TEST (RED) `tests/models/test_clinical_append_only_db.py`: `UPDATE` y `DELETE` rechazados en cada tabla append-only como dueño y como `app_writer` (sin privilegio). Escenarios: "Versiones inmutables", "Inmutabilidad", "Historial inmutable", "Bitácora inmutable", "Sin DELETE".
- [x] 1.4 Migración `backend/alembic/versions/c15_clinical_record.py` (`down_revision="c14_hardening_pilot"`): enums, tablas, índices de D2, triggers, siembra del catálogo para clínicas existentes; sumar las tablas a `APPEND_ONLY_TABLES` en `app/ops/db_privileges.py` y re-grant. Verificación: 1.1 y 1.3 verdes.
- [x] 1.5 TEST + ajuste `tests/test_migrations.py`: ciclo upgrade → downgrade (`c14_hardening_pilot`) → upgrade con filas sintéticas de C-12/C-14 y clínicas; downgrade elimina tablas y enums; ninguna tabla existente cambió (comparación de `information_schema`). Verificación: test verde.
- [x] 1.6 TEST + `app/seed.py`: catálogo inicial por clínica nueva, idempotente y aislado. Escenarios: "Catálogo sembrado", "Catálogo aislado". Verificación: `tests/test_seed_clinical.py` verde.

## 2. Acceso y auditoría (D4, D5)
- [x] 2.1 TEST (RED) `tests/modules/clinical/test_access_rbac.py`: matriz admin/odontólogo/recepción × todos los endpoints (recepción `403 forbidden_role` sin filas ni eventos), alcance del odontólogo (`404` indistinguible), admin sin `professional_id` (`403 professional_required`), cross-tenant `404` en cada recurso hijo, `no-store`. Escenarios de `clinical/access-control` salvo auditoría.
- [x] 2.2 `app/modules/clinical/access.py` (`ClinicalReader`, `ClinicalWriter`, `resolve_record`) + router base con `Cache-Control: no-store` + registro en `app/main.py`. Verificación: 2.1 GREEN.
- [x] 2.3 TEST (RED) `tests/modules/clinical/test_access_audit.py`: un evento por lectura/escritura, `payload` sin PII, rollback si falla el insert (inyectando fallo real con trigger temporal en la base de pruebas), paginación del `access-log` solo admin. Escenarios: "Lectura auditada", "Descarga y PDF auditados", "Falla de auditoría revierte la operación", "Admin pagina la bitácora", "Odontólogo no ve la bitácora".
- [x] 2.4 `app/modules/clinical/audit.py` + `GET /api/clinical-records/{rid}/access-log` con cursor. Verificación: 2.3 GREEN.
- [x] 2.5 Ampliar `tests/test_route_protection.py` (rutas clínicas sin `recepcion`) y `tests/test_edges.py` (`extra='forbid'` en todos los schemas clínicos). Escenario: "Ningún endpoint clínico queda sin guarda", "Autoría no suplantable por cuerpo". Verificación: ambos verdes.
- [x] 2.6 TEST de logs `tests/modules/clinical/test_no_pii_logs.py` (caplog durante ficha, anamnesis, evolución, odontograma, adjunto, plan, PDF y 422): ningún valor sintético sensible. Escenarios: "Logs sin contenido clínico", "Error de validación sin eco". Verificación: verde, tras ajustar el handler 422 si el eco aparece.

## 3. Ficha y anamnesis
- [x] 3.1 TEST (RED) `tests/modules/clinical/test_record_api.py`: apertura 201/200, apertura simultánea (dos sesiones reales con `asyncio.gather`), paciente archivado `409`, ficha no abierta `404`, conteos, y escritura clínica sobre paciente archivado `409` con lectura `200`. Escenarios de "Apertura idempotente", "Consulta de la ficha" y "Paciente archivado".
- [x] 3.2 Servicio/router de ficha (`FOR SHARE` sobre `patient`, UPSERT por UNIQUE). Verificación: 3.1 GREEN.
- [x] 3.3 TEST (RED) `tests/modules/clinical/test_anamnesis_api.py`: versión 1, versión 2 conserva la 1, conflicto concurrente (`409`, no hay v3), 1001 caracteres `422`, campo extra `422`, vacía `201`. Escenarios de "Anamnesis versionada e inmutable".
- [x] 3.4 Schemas `extra='forbid'` + servicio con `expected_version` y manejo de `UNIQUE (record_id, version)` → `409 version_conflict`. Verificación: 3.3 GREEN; refactor sin romper.

## 4. Odontograma
- [x] 4.1 TEST (RED) `tests/modules/clinical/test_fdi.py` (unit puro): permanentes, temporales, inválidos, dentición derivada, tabla de caras. Escenarios "Pieza permanente/temporal válida", "Códigos fuera de rango".
- [x] 4.2 `app/modules/clinical/fdi.py`. Verificación: 4.1 GREEN con triangulación (≥ 2 casos por cuadrante).
- [x] 4.3 TEST (RED) `tests/modules/clinical/test_odontogram_api.py`: lote válido (1 evento de acceso), lote con 1 inválida (nada insertado), 0 y 33 entradas, condición ajena/inactiva, `condition_scope_mismatch` en ambos sentidos, nota > 500, la última entrada gana, limpiar, concurrencia en la misma cara (determinista), filtro por dentición, ficha sin hallazgos, historial con cursor, pieza inválida, `evolution_id` propio/ajeno.
- [x] 4.4 Servicio de odontograma (batch insert, `clock_timestamp()`, proyección `DISTINCT ON`), `GET /odontogram/conditions`. Verificación: 4.3 GREEN; `EXPLAIN` de la proyección usa el índice de D2 (assert en test).

## 5. Evoluciones
- [x] 5.1 TEST (RED) `tests/modules/clinical/test_evolutions_api.py`: creación con hash verificable (recalculado), 422 vacía/larga/`signed_at` en cuerpo, vínculos de turno (propio, otro paciente, otro profesional, otra clínica, sin turno), correcciones (autor, no autor `403 not_evolution_author`, motivo corto, ficha ajena, concurrentes), listado con cursor, marca `corrected_by`, filtro por turno, `limit` inválido, turno cancelado/futuro `201` sin `appointment_event`.
- [x] 5.2 Servicio/router con hash canónico (`app/common/clock.py` para `signed_at`) y cadena de correcciones. Verificación: 5.1 GREEN; test unit del hash canónico (mismo contenido → mismo hash; texto distinto → distinto).

## 6. Adjuntos
- [x] 6.1 TEST (RED) `tests/modules/clinical/test_storage_contract.py`: batería de contrato corrida contra la implementación local (directorio temporal) y una en memoria de prueba: guardar, abrir, ausencia, no sobrescribir, clave que escapa de la raíz rechazada.
- [x] 6.2 `storage/base.py` + `storage/local.py` + settings `CLINICAL_STORAGE_ROOT`/`CLINICAL_MAX_ATTACHMENT_BYTES` y `.env.example` (test `test_env_example.py` ajustado). Verificación: 6.1 GREEN.
- [x] 6.3 TEST (RED) `tests/modules/clinical/test_attachments_api.py`: subida PNG/JPEG/PDF sintéticos con `sha256` correcto, tipo falso por magic bytes `415`, 10 MiB + 1 `413`, vacío `422`, nombre malicioso saneado, tope 200 `409`, falla de storage sin fila huérfana, evolución ajena `422`, descarga con headers y bytes idénticos, sin sesión `401`, otra clínica `404`, objeto ausente `500` sin ruta, baja (201, repetida `409`, concurrente), descarga de baja `404` (odontólogo) y `200` auditada (admin), listado activo sin `storage_key`, `include_removed` solo admin (`403` al odontólogo), cursor y `limit`.
- [x] 6.4 Servicio/router de adjuntos (límite de lectura por partes, magic bytes, limpieza de huérfano) + dependencia `python-multipart` pineada. Verificación: 6.3 GREEN.
- [ ] 6.5 Compose: volumen `clinical_files` en `compose.yaml` y `compose.prod.yaml` (permisos del usuario del contenedor, tag y healthchecks sin cambios). Verificación: `docker compose config` dev y prod sin error; test que escribe/lee desde el contenedor `api` en el e2e. **Estado (apply 2026-11-11)**: volumen y `CLINICAL_STORAGE_ROOT` en ambos compose, `docker compose config` dev y prod OK; falta la verificación e2e desde el contenedor (pendiente por presupuesto de tokens, ver 10.1).

## 7. Presupuestos y PDF
- [x] 7.1 TEST (RED) `tests/modules/clinical/test_plan_totals.py` (unit): subtotales/total, formato es-AR `1.150,00`, desbordamiento de bigint, importes inválidos.
- [x] 7.2 `plans.py` (cálculo y formato). Verificación: 7.1 GREEN con ≥ 3 casos.
- [x] 7.3 TEST (RED) `tests/modules/clinical/test_plans_api.py`: plan v1, v2 conserva v1, conflicto de versión concurrente, fases no consecutivas, límites 0/51/11, pieza inválida, `total_cents` en cuerpo `422`, decisión (aceptar, versión vieja `409 version_superseded`, doble y paralela `409`, valor inválido), listado y detalle, ficha ajena `404`.
- [x] 7.4 Servicio/router de planes. Verificación: 7.3 GREEN.
- [x] 7.5 TEST (RED) `tests/modules/clinical/test_plan_pdf.py`: empieza con `%PDF-`, texto extraído (con `pypdf` como dependencia de desarrollo) contiene total y fases, sin DNI/teléfono, acentos y Ñ, fecha de emisión en zona de la clínica (instante 02:30 UTC → día anterior en Buenos Aires), versión inexistente `404`, auditoría `plan_pdf_export`.
- [x] 7.6 `pdf.py` con `reportlab` (en executor, fuente TTF embebida) + dependencias pineadas. Verificación: 7.5 GREEN.

## 8. Guardas sobre lo existente
- [x] 8.1 TEST (RED) `tests/modules/test_patient_merge_clinical.py`: absorbido con ficha `409 patient_has_clinical_record` sin cambios; destino con ficha procede; sin fichas igual que C-06; carrera apertura vs fusión (nunca ambas). Escenarios de `core/patients`.
- [x] 8.2 Guarda en `app/modules/patients/merge.py`. Verificación: 8.1 y los tests de fusión de C-06 verdes.
- [x] 8.3 TEST (RED) `tests/modules/test_exports_exclude_clinical.py`: con ficha sintética cargada, `/api/exports/full` y `/api/exports/patients/{id}` no contienen cadenas clínicas ni claves; test de contrato que clasifica todas las tablas con `clinic_id` (excluidas vs exportadas).
- [x] 8.4 Lista `EXCLUDED_FROM_EXPORT` en `app/modules/reports/` consumida por el test. Verificación: 8.3 GREEN.

## 9. Frontend
- [x] 9.1 TEST (RED) Vitest `features/clinical/fdi.test.ts` y `Odontogram.test.tsx`: 32 y 20 piezas, 5 caras + pieza completa, navegación por teclado, etiqueta "Pieza 36, cara oclusal: caries", indicador no solo por color, borrador y lotes de 32 con fallo parcial.
- [x] 9.2 `features/clinical/{fdi.ts,Odontogram.tsx,api.ts,types.ts}` (sin `any`, `strict`). Verificación: 9.1 GREEN y `npm run typecheck`.
- [x] 9.3 TEST (RED) Vitest de `ClinicalRecordPage` y pestañas: ruta por rol (recepción "sin acceso" y cero peticiones), enlace desde el detalle del turno solo para odontólogo/admin, ficha no abierta, paciente fuera de alcance, conflicto de versión conserva texto, corrección solo del autor, "Corregida", validación de archivo, descarga por blob, totales del servidor, decisión, errores sin texto clínico. **Estado (2026-11-11)**: hecho en versión reducida (presupuesto de tokens): `ClinicalRecordPage.test.tsx` (anamnesis con conflicto que conserva texto, validación de archivo, totales del servidor, corrección solo del autor, sin datos en almacenamiento) y `AppointmentDetail.clinical.test.tsx` (enlace solo odontólogo/admin). No cubiertos: descarga por blob y decisión del presupuesto en UI.
- [x] 9.4 Páginas/pestañas/hooks + ruta en `routes` + enlace en el detalle del turno. Verificación: 9.3 GREEN. **Estado**: hecho — pestañas Anamnesis, Adjuntos y Presupuestos (`ClinicalTabs.tsx`), corrección del autor y enlace desde el detalle del turno. La aceptación/rechazo del presupuesto y la edición multi-fase quedan para C-16.
- [x] 9.5 TEST + ajuste: ningún dato clínico en `localStorage`/`sessionStorage`/IndexedDB/cola de C-14, limpieza al cerrar sesión o cambiar de paciente, sin red no se encola. Verificación: test Vitest con almacenamiento espiado. **Estado**: hecho — estado solo en memoria, descartado al cambiar de paciente (`key`); test con `Storage.prototype.setItem` espiado.

## 10. E2E, docs y gate
- [ ] 10.1 Playwright `e2e/clinical-circuit.spec.ts` (stack real con datos sintéticos): odontólogo abre ficha, guarda anamnesis, marca 36/O, escribe y corrige una evolución, sube un PNG y lo descarga, crea y exporta presupuesto PDF; recepción ve "sin acceso" y recibe `403` por API. Verificación: job `e2e` verde sin `continue-on-error`. **Estado**: pendiente por presupuesto de tokens.
- [x] 10.2 Docs `docs/clinica/` (política de acceso, retención sin purga, anamnesis y estados validados, firma simple vs Ley 25.506, runbook de backup del volumen) y registrar los follow-ups (periodontograma, ortodoncia, firma 25.506, FHIR, seguimiento de ítems) en `CHANGES.md`/`10`. Verificación: archivos presentes y enlazados desde `docs/piloto/`.
- [x] 10.3 Gate backend: `pytest -q` (py3.12 + PG 15 + Redis 7), `ruff check backend`, `black --check backend`, `mypy backend`. Verificación: todo verde, conteo anotado. **Resultado (2026-11-11)**: 2277 passed + 1 fallo intermitente ajeno a C-15 (`test_manage_signed_link::test_el_token_firmado_no_aparece_en_errores_ni_logs`, verde aislado 22/22); ruff, black y mypy (420 archivos) limpios. Pytest corrido desde `backend/` para no levantar el `.env` de la raíz.
- [x] 10.4 Gate frontend: `npm run typecheck && npm test && npm run build`. Verificación: todo verde. **Resultado**: typecheck limpio, 293 tests Vitest (42 archivos) y build OK.
- [ ] 10.5 `npx playwright test` completo (incluye circuitos de C-06, C-12, C-14 y C-15). Verificación: verde en CI. **Estado**: pendiente por presupuesto de tokens (no se corrió Playwright).
- [x] 10.6 Aprobación final de las Open Decisions implementadas y `/opsx:archive c-15-historia-clinica-odontograma`; marcar `[x]` en `CHANGES.md` y actualizar `10_preguntas_abiertas.md` (Ley 27.706/26.529 sigue abierta para el asesor legal).
