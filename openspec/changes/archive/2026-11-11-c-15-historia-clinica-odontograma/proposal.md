# Proposal — C-15 `historia-clinica-odontograma`

> Governance **CRITICO** (datos de salud, Ley 26.529 / 27.706 / 25.326). Este change solo
> produce artefactos de planificación; no se escribe código hasta que el usuario apruebe las
> Open Decisions y pida `/opsx:apply`.

## Precondición para aplicar

C-14 `hardening-piloto` está **implementado pero sin archivar** (pendientes 7.1–7.4: gate de
pytest/ruff/black/mypy, `npm run typecheck && test && build`, Playwright en CI y aprobación de sus 8
Open Decisions). C-15 depende de lo que C-14 dejó: rol de base `app_writer` (sin `DELETE`; los
triggers append-only más el `REVOKE UPDATE` de `app/ops/db_privileges.py`), logs con redacción de
PII, envolvente de errores sin eco de `input`, `Cache-Control`/headers seguros y el E2E en CI.
**No aplicar C-15 hasta que C-14 esté archivado.** Este change no toca C-14.

## Why

El MVP agenda-first (C-01…C-14) ordena turnos pero no guarda nada clínico (DD-02, `03` §Reglas
transversales). El Discovery (§D3, §C4.5) marca la ficha clínica con odontograma FDI, evoluciones,
adjuntos y presupuestos por fases como imprescindible para competir en AR, y la clínica del
piloto hoy lleva todo eso en papel o en otro sistema. DD-02 dejó `patient_id` y `appointment_id`
estables justamente para enganchar esta fase **sin migración rompiente**: C-15 solo agrega tablas
nuevas.

Es CRITICO porque introduce el primer dato de salud del producto: la regla "recepción no accede a
datos clínicos" deja de ser una frase y pasa a ser un control que hay que probar; la historia
clínica debe ser íntegra e inalterable (Ley 26.529: las correcciones se agregan, no reescriben) y
cada acceso debe ser auditable.

## What Changes

### Backend (FastAPI + PostgreSQL) — módulo nuevo `app/modules/clinical/`

- **Ficha clínica** por paciente (`clinical_record`, 1:1 con `patient`), que se abre
  explícitamente; engancha por `(clinic_id, patient_id)` y, opcionalmente, por
  `(clinic_id, appointment_id)`.
- **Anamnesis versionada** (`anamnesis_version`, append-only): cada guardado crea la versión N+1
  con control optimista (`expected_version`); la vigente es la mayor; las anteriores se leen.
- **Odontograma FDI** permanente (11–48) y temporal (51–85), por pieza y cara (M, D, O/I, V, L y
  pieza completa), con **catálogo de estados** por clínica (`odontogram_condition`, sembrado con
  un set inicial). Se guarda como **eventos append-only** (`odontogram_event`); el estado
  vigente es una proyección por la última entrada de cada (pieza, cara), nunca una fila mutada
  (regla 8). Alta por lotes en una transacción; historial por pieza con cursor.
- **Evoluciones** append-only (`clinical_evolution`), firmadas por el odontólogo autenticado
  (sello de tiempo del servidor + hash SHA-256 del contenido). Una corrección es una entrada
  nueva que referencia a la original; la original sigue visible.
- **Adjuntos** (`clinical_attachment` + `clinical_attachment_removal`): metadatos en Postgres y
  bytes tras una **abstracción de almacenamiento** (`AttachmentStorage`) con una implementación
  de disco por volumen de Docker; descarga solo autenticada por la API; baja lógica con motivo
  (el archivo no se borra).
- **Plan de tratamiento / presupuesto por fases**: `treatment_plan` + `treatment_plan_version`
  (inmutables) + `treatment_plan_item` + `treatment_plan_decision` (aceptado/rechazado,
  append-only); importes en centavos de ARS cargados a mano; **export a PDF** generado al vuelo
  (no se persiste el archivo).
- **Auditoría de acceso** (`clinical_access_event`, append-only): toda lectura o escritura
  clínica deja un evento (actor, acción, objeto) en la misma transacción, sin contenido ni PII.
  Consulta para admin.
- **Control de acceso**: recepción recibe `403 forbidden_role` en **todos** los endpoints
  clínicos; el odontólogo solo accede a pacientes con al menos un turno propio (fuera de su
  alcance → `404`, sin filtrar existencia); escribir exige `professional_id` en el principal
  (odontólogo, o admin que también atiende). Respuestas con `Cache-Control: no-store`.
- **Una migración Alembic** (`c15_clinical_record`, `down_revision="c14_hardening_pilot"`):
  solo tablas nuevas (vacías → sin `CONCURRENTLY` ni `NOT VALID`), `clinic_id` en todas, FKs
  compuestas `(clinic_id, id)`, triggers `BEFORE UPDATE OR DELETE` en las append-only, tablas
  sumadas a `APPEND_ONLY_TABLES` (para que `app_writer` no tenga `UPDATE`) y catálogo inicial
  sembrado para las clínicas existentes.
- **Guardas sobre lo existente** (sin cambiar sus contratos públicos): la exportación completa
  (C-13) y la de paciente (C-14) **no incluyen** datos clínicos; la fusión de pacientes (C-06)
  se rechaza si el paciente absorbido tiene ficha clínica.
- **Dependencias nuevas**: `python-multipart` (subida) y una librería de PDF (default
  `reportlab`, pineada) en el archivo de dependencias del backend.

### Frontend (React + TS + Vite + Tailwind)

- Ruta protegida `/pacientes/:patientId/historia-clinica` (solo admin y odontólogo; recepción
  no ve el acceso ni entra por URL) con pestañas: Anamnesis, Odontograma, Evoluciones, Adjuntos,
  Presupuestos. Acceso desde el detalle del turno del odontólogo.
- Componente `Odontogram` en SVG propio (sin librería), 5 caras por pieza, selección por
  teclado, etiquetas accesibles, dentición permanente/temporal.
- Cliente tipado (`features/clinical/api.ts`), sin `any` (regla 5); ningún dato clínico en
  `localStorage`/`sessionStorage`/cola offline (extiende la política de C-14).

### Pruebas y CI

- pytest contra Postgres 15 real (regla 9): matriz RBAC, aislamiento cross-tenant por cada
  tabla, append-only por trigger **y** por `app_writer`, invariantes FDI, concurrencia de
  versiones, adjuntos, PDF, no-PII-en-logs, exclusión de exports, migración up/down.
- Vitest para el odontograma y las pestañas; Playwright `clinical-circuit.spec.ts`.

## Capabilities

### New Capabilities

- `clinical/access-control`: RBAC clínico, alcance del odontólogo, no-store y auditoría de acceso.
- `clinical/patient-record`: ficha clínica y anamnesis versionada.
- `clinical/odontogram`: catálogo de estados y odontograma FDI por pieza y cara.
- `clinical/evolutions`: evoluciones firmadas, append-only, con correcciones.
- `clinical/attachments`: adjuntos con almacenamiento abstracto y baja lógica.
- `clinical/treatment-plans`: planes/presupuestos por fases, decisiones y PDF.
- `web/clinical-record`: SPA de la historia clínica y el odontograma.

### Modified Capabilities

- `core/data-export`: las exportaciones nunca incluyen datos clínicos.
- `core/patients`: la fusión se rechaza si el paciente absorbido tiene ficha clínica.

## Impact

- **Backend nuevo**: `backend/app/modules/clinical/{router,schemas,service,access,audit,fdi,odontogram,evolutions,attachments,plans,pdf}.py`,
  `backend/app/modules/clinical/storage/{base,local}.py`, modelos `backend/app/models/clinical_*.py`
  y `odontogram_*.py`, enums en `backend/app/models/enums.py`.
- **Backend modificado (puntos de reutilización)**: `app/common/dependencies.py` (`require_roles`),
  `app/common/principal.py` (`professional_id`), `app/common/scoping.py` (alcance del odontólogo),
  `app/common/pagination.py` (cursor), `app/modules/patients/merge.py` (guarda),
  `app/modules/reports/{exports,patient_export}.py` (exclusión verificada),
  `app/ops/db_privileges.py` (`APPEND_ONLY_TABLES`), `app/core/settings.py` + `.env.example`
  (`CLINICAL_STORAGE_*`), `app/main.py` (router), `app/seed.py` (catálogo por clínica),
  `backend/tests/test_route_protection.py` y `backend/tests/test_edges.py`.
- **Datos**: migración `c15_clinical_record` (solo `CREATE`; downgrade con `DROP` de tablas
  nuevas — los datos clínicos cargados se pierden, ver design §Migration Plan).
- **API nueva** (todas bajo `/api`): ver `design.md` §D10.
- **Frontend**: `features/clinical/*`, `routes`, enlace desde el detalle del turno del odontólogo.
- **Infra**: volumen `clinical_files` en `compose.yaml`/`compose.prod.yaml` (montado en `api`,
  también en el runbook de backups de `docs/piloto/`).
- **Docs**: `docs/clinica/` (política de acceso, retención, plantilla de anamnesis, set de estados).

## Fuera de alcance (diferido, a registrar como changes futuros)

- Periodontograma, ortodoncia/cefalometría, imágenes DICOM/visor de radiografías.
- **Firma digital Ley 25.506** y consentimientos informados firmados: C-15 solo da firma
  **simple** (identidad autenticada + sello + hash) y no la presenta como firma digital.
- ReNaPDiS, HL7 FHIR e interoperabilidad (Ley 27.706): se deja el modelo exportable, sin
  endpoints FHIR.
- Seguimiento de ítems del plan como "realizados", vínculo con cobros (C-16), nomenclador y
  coseguros (C-18), facturación (C-17).
- Edición del catálogo de estados por la clínica (en C-15 es de solo lectura, sembrado).
- Purga por retención, antivirus de adjuntos, almacenamiento S3, acceso del paciente a su
  historia (portal), firma de presupuesto por el paciente.
- Entrega del presupuesto por recepción (ver Open Decision 3).

## Open Decisions (defaults propuestos, todas `(TBD)` hasta aprobación del usuario)

> La KB no decide estos puntos; se implementan los defaults solo tras aprobación (CRITICO). Las
> preguntas legales de `10` (Ley 27.706/26.529) siguen abiertas para el asesor legal.

1. **Acceso del admin a datos clínicos** — *Default*: lectura total; escritura solo si el
   principal tiene `professional_id` (admin que también atiende). Alternativa: admin sin acceso.
2. **Alcance del odontólogo** — *Default*: pacientes con al menos un turno (cualquier estado) con
   ese profesional; el resto responde `404`. Alternativa: todos los pacientes de la clínica.
3. **Recepción y presupuestos** — *Default*: `403` también en presupuestos (estricto con `03`);
   la entrega al paciente la hace el odontólogo/admin y se revisa en C-16 (cobros).
4. **Quién corrige una evolución** — *Default*: solo su autor, sin límite de tiempo, como entrada
   nueva de tipo `correction` con motivo obligatorio. Alternativa: ventana de N horas o también admin.
5. **Almacenamiento de adjuntos** — *Default*: disco en volumen Docker tras `AttachmentStorage`
   (S3-compatible después, sin migración). Tope 10 MiB por archivo y tipos `jpeg/png/pdf`
   (verificados por contenido, no por extensión); sin antivirus en C-15.
6. **Librería de PDF** — *Default*: `reportlab` (Python puro, sin dependencias del sistema en la
   imagen). Alternativa: WeasyPrint (mejor maquetado HTML, requiere librerías nativas).
7. **Retención** — *Default*: sin purga en C-15; coherente con la Open Decision 7 de C-14 (10
   años, Ley 26.529 art. 18), pendiente del asesor legal. Nada se borra físicamente.
8. **Set inicial de estados del odontograma** — *Default*: sano, caries, obturación, corona,
   endodoncia, ausente, implante, extracción indicada, sellador, fractura, prótesis fija. Debe
   validarlo un odontólogo de la clínica piloto antes del apply.
9. **Anamnesis** — *Default*: campos estructurados fijos (alergias, medicación, condiciones
   sistémicas por casillero, embarazo, tabaquismo, anticoagulantes, observaciones ≤ 1000
   caracteres) a validar con la clínica piloto. Alternativa: formulario configurable (más scope).
10. **Fusión de pacientes con ficha** — *Default*: bloquear la fusión (`409 patient_has_clinical_record`)
    hasta definir el procedimiento de unificación de historias. Alternativa: mover la ficha.
11. **Datos clínicos en exports y backups** — *Default*: fuera de las exportaciones de C-13/C-14;
    la portabilidad clínica (Ley 27.706) queda como follow-up. Los backups PITR (C-14) sí
    cubren las tablas nuevas y el volumen de adjuntos.
12. **Límites de contenido** — *Default*: evolución ≤ 4000 caracteres, ≤ 200 adjuntos por ficha,
    lote de odontograma ≤ 32 entradas, presupuesto ≤ 10 fases y ≤ 50 ítems por versión.
13. **Evolución y estado del turno / paciente archivado** — *Default*: una evolución puede
    vincularse a un turno en cualquier estado (el hecho clínico no depende del estado de agenda);
    las lecturas de la ficha de un paciente archivado se permiten y toda escritura clínica sobre
    él responde `409 patient_archived`. Alternativa: exigir turno `present` o ya iniciado.

### Resolución (2026-11-11)

El usuario aprobó las 13 Open Decisions con sus defaults, sin cambios. Dejan de ser `(TBD)` como
decisiones de producto; siguen pendientes las validaciones externas indicadas en 7 (asesor legal) y
8–9 (odontólogo de la clínica piloto, task 0.3).
