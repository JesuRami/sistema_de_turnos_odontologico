# Design — C-15 `historia-clinica-odontograma`

## Context

C-01…C-14 dejan un backend FastAPI async + SQLAlchemy 2 + Alembic con: `Principal` construido desde
la fila de `user` (`app/common/principal.py`), `require_roles` como única puerta de rol
(`app/common/dependencies.py`), `patient` con `UNIQUE (id, clinic_id)` y FKs compuestas
`(clinic_id, id)` hacia `appointment`, `user` y `professional`, eventos append-only con trigger
`BEFORE UPDATE OR DELETE` (`appointment_event`, patrón de C-05), paginación por cursor
(`app/common/pagination.py`), el rol de base `app_writer` (C-14: `SELECT/INSERT/UPDATE`, sin
`DELETE`; las tablas append-only se listan en `APPEND_ONLY_TABLES` de `app/ops/db_privileges.py`
y pierden `UPDATE`), logs con redacción y 422 sin eco de `input`.

Restricciones que pesan: reglas duras 1–13 de `AGENTS.md` (en especial 2, 3, 4, 5, 7, 8, 9, 11, 13);
DD-02 (ganchos estables, sin migración rompiente); DD-03 (RBAC simple, guard evolucionable);
`03` (recepción sin clínica); Ley 26.529 (integridad, no alteración de la historia clínica).
Ver proposal.md para motivación y alcance.

## Goals / Non-Goals

**Goals**: dato clínico íntegro (nada se reescribe ni se borra, ni por bug de la app); acceso
mínimo y trazable; sin tocar tablas existentes; una migración; implementable en un change.

**Non-Goals**: firma digital Ley 25.506, FHIR/ReNaPDiS, periodontograma, ortodoncia, DICOM,
portal del paciente, cobros, seguimiento de ítems del plan, edición del catálogo de estados,
purga por retención, antivirus, S3.

## Decisions

### D1 — Todo es append-only; "lo vigente" se deriva
Ninguna tabla clínica tiene `updated_at` ni se actualiza. Cada tabla lleva trigger
`BEFORE UPDATE OR DELETE → RAISE` y está en `APPEND_ONLY_TABLES` (sin `UPDATE` para `app_writer`).
Un "cambio" es una fila nueva: anamnesis N+1, evolución `correction`, evento de odontograma,
versión de plan, `removal` de adjunto, `decision` de plan. La única excepción son los catálogos
(`odontogram_condition`: `active` mutable, tabla operativa, auditada con
`clinical_access_event`) y `clinical_record` (fila de anclaje inmutable).
*Alternativa descartada*: tablas mutables + tabla de historia/auditoría paralela: duplica la
verdad y permite que un bug reescriba (viola reglas 7 y 8).

### D2 — Modelo de datos (una migración `c15_clinical_record`)

Todas con `id uuid DEFAULT gen_random_uuid()`, `clinic_id NOT NULL` con FK a `clinic`, e `UNIQUE
(id, clinic_id)` para FKs compuestas. `created_at timestamptz DEFAULT now()`.

| Tabla | Clave y columnas relevantes | Constraints |
|---|---|---|
| `clinical_record` | `patient_id`, `created_by_user_id` | `UNIQUE (clinic_id, patient_id)`; FK `(clinic_id, patient_id) → patient` |
| `anamnesis_version` | `record_id`, `version int`, `answers jsonb`, `created_by_user_id` | `UNIQUE (record_id, version)`; `CHECK version >= 1`; FK compuesta a `clinical_record` |
| `odontogram_condition` | `code`, `label`, `category`, `scope` (`surface`/`tooth`), `active` | `UNIQUE (clinic_id, code)` |
| `odontogram_event` | `record_id`, `tooth smallint`, `surface` (enum `M,D,O,V,L,W`), `condition_id null`, `note`, `evolution_id null`, `professional_id`, `created_by_user_id` | `CHECK` FDI (`tooth` en 11–18,21–28,31–38,41–48,51–55,61–65,71–75,81–85); `CHECK note length ≤ 500`; FKs compuestas |
| `clinical_evolution` | `record_id`, `appointment_id null`, `professional_id`, `kind` (`entry`/`correction`), `corrects_evolution_id null`, `reason null`, `body`, `signed_at`, `content_sha256 char(64)` | `CHECK` `kind='correction'` ⇔ `corrects_evolution_id` y `reason` no nulos; `CHECK length(body) BETWEEN 1 AND 4000`; FK compuesta a `appointment`, `professional`, `clinical_evolution` |
| `clinical_attachment` | `record_id`, `evolution_id null`, `kind`, `content_type`, `size_bytes`, `sha256`, `display_name`, `storage_key`, `created_by_user_id` | `UNIQUE (storage_key)`; `CHECK size_bytes BETWEEN 1 AND 10485760` |
| `clinical_attachment_removal` | `attachment_id`, `reason`, `removed_by_user_id` | `UNIQUE (attachment_id)` (una baja por adjunto) |
| `treatment_plan` | `record_id`, `title` | — |
| `treatment_plan_version` | `plan_id`, `version`, `created_by_user_id` | `UNIQUE (plan_id, version)` |
| `treatment_plan_item` | `version_id`, `phase smallint`, `position smallint`, `description`, `quantity int`, `unit_price_cents bigint`, `tooth null`, `surface null` | `CHECK quantity >= 1`, `unit_price_cents >= 0`, `phase BETWEEN 1 AND 10`; mismo CHECK FDI |
| `treatment_plan_decision` | `version_id`, `decision` (`accepted`/`rejected`), `note`, `decided_by_user_id` | `UNIQUE (version_id)` |
| `clinical_access_event` | `record_id`, `actor_user_id`, `action` (enum), `object_type`, `object_id null`, `payload jsonb` | `CHECK` sin claves libres de texto: el `payload` solo lo arma el servicio con ids/conteos |

Índices (tablas nuevas y vacías: `CREATE INDEX` normal y FKs/CHECK directos son seguros; la regla
11 se cumple porque ninguna tabla existente se altera): `odontogram_event (record_id, tooth,
surface, created_at DESC, id DESC)` para la proyección; `clinical_evolution (record_id,
signed_at DESC, id DESC)`; `clinical_evolution (record_id, appointment_id)`;
`clinical_attachment (record_id, created_at DESC)`; `clinical_access_event (record_id, created_at
DESC, id DESC)`; `appointment (clinic_id, professional_id, patient_id)` **no** se crea (ver D4).
`FK` e índices sobre `clinic_id` siguen la convención de las migraciones previas.

Enums de Postgres nativos (como `appointment_status`) para `surface`, `evolution_kind`,
`attachment_kind`, `plan_decision`, `clinical_action`. El downgrade los elimina.

### D3 — Estado vigente del odontograma sin tabla mutable
La proyección es una consulta `SELECT DISTINCT ON (tooth, surface) ... ORDER BY tooth, surface,
created_at DESC, id DESC` filtrada por ficha (y por rango de `tooth` según dentición), sobre el
índice de D2. Las entradas con `condition_id IS NULL` se descartan *después* de elegir la última
(así "limpiar" tapa un estado previo). Columnas explícitas, sin `SELECT *`. `created_at` usa
`clock_timestamp()` (no `now()`) para que dos entradas del mismo lote se ordenen por posición y
las de transacciones concurrentes por instante real; `id` desempata de forma determinista.
*Alternativa descartada*: tabla `tooth_state` mutable actualizada por trigger: duplica el estado
y reintroduce UPDATE (D1). El costo (lectura de ≤ 32 piezas × 6 caras con `DISTINCT ON`) es
despreciable frente al volumen de una ficha.

### D4 — Control de acceso
Un único módulo `app/modules/clinical/access.py` expone dos dependencies que **envuelven**
`require_roles` (sin duplicar su lógica):

- `ClinicalReader = require_roles(ADMIN, ODONTOLOGO)`; `ClinicalWriter` = lo anterior **más**
  `principal.professional_id is not None` → si no, `403 professional_required`.
- `resolve_record(session, principal, patient_id | record_id)`: carga el paciente/ficha por
  `(id, clinic_id)`; para `ODONTOLOGO` agrega `EXISTS (SELECT 1 FROM appointment WHERE clinic_id =
  :c AND patient_id = :p AND professional_id = :prof)` (usa el índice de agenda existente; si
  `EXPLAIN` en el piloto muestra costo, se evalúa un índice en un change posterior, no aquí).
  Fuera de alcance o inexistente → `404 patient_not_found` idéntico.
- La guarda de rutas (`tests/test_route_protection.py`) se amplía: toda ruta cuyo path contenga
  `clinical-record`, `clinical-records` u `odontogram` debe declarar roles y excluir `recepcion`.

Respuestas clínicas pasan por un `APIRouter` con dependencia que fija `Cache-Control: no-store`.
El `Principal` y `clinic_id` salen del servidor (patrón de C-03); los schemas Pydantic de entrada
llevan `ConfigDict(extra='forbid')` y no incluyen `professional_id`, `signed_at` ni totales.

### D5 — Auditoría de acceso
`ClinicalAudit.record(session, principal, record_id, action, object=None)` agrega un
`clinical_access_event` a la **misma sesión** y hace `flush` inmediato (patrón de
`appointments/audit.py`): si falla, falla la operación. Las lecturas (`GET`) también escriben.
El `payload` solo admite ids, conteos y versiones armados por el servicio (nunca texto libre). Un
`403` por rol no escribe evento (el handler no corre): queda en el log de `app.auth.rbac`, que ya
no lleva PII. Costo: un INSERT por request clínico; aceptable para un uso de decenas de requests
por consulta.

### D6 — Evoluciones y firma simple
`content_sha256 = sha256(canonical_json({record_id, appointment_id, professional_id, kind,
corrects_evolution_id, reason, body, signed_at_iso}))` con serialización canónica (claves
ordenadas, UTF-8, `signed_at` en UTC con microsegundos). Se calcula en el servicio con el
`signed_at` del servidor (`app/common/clock.py`) y es verificable offline. No hay borrador en la
base (sería mutable): el borrador vive en memoria del formulario. Una corrección referencia a la
evolución **corregida más reciente** (cadena lineal) para que el listado marque `corrected_by`
sin recorrer grafos; si la original ya tiene corrección, la nueva apunta a esa corrección. El
autor se valida contra `professional_id` del principal. *Alternativa descartada*: firma
criptográfica con clave por odontólogo: es la firma digital Ley 25.506, explícitamente diferida.

### D7 — Adjuntos: almacenamiento abstracto
`app/modules/clinical/storage/base.py` define `AttachmentStorage` (Protocol async: `put(key,
stream) -> int`, `open(key) -> AsyncIterator[bytes]`, `exists(key)`), y `local.py` la
implementación sobre `CLINICAL_STORAGE_ROOT` (volumen `clinical_files`). `storage_key =
f"{clinic_id}/{uuid4().hex}"` generado por el servidor; la implementación local normaliza la
ruta y rechaza cualquier clave que salga de la raíz; escribe con modo exclusivo (no sobrescribe).
Flujo de subida: lee el stream por partes con tope (10 MiB + 1 → `413`), valida *magic bytes*
(`\xff\xd8\xff`, `\x89PNG\r\n\x1a\n`, `%PDF-`), calcula `sha256` mientras escribe, guarda el archivo
y recién después inserta la fila en la misma transacción de la auditoría; si la transacción falla
se intenta quitar el archivo huérfano (única excepción de borrado, de un objeto que nunca fue
visible) y, si eso falla, se loguea el `storage_key` (sin PII) para limpieza manual. La descarga
es streaming por la API con headers de D4. `python-multipart` para el `UploadFile`; el tope real
lo impone un límite de lectura, no el `Content-Length`.
*Alternativas*: S3/MinIO (más infraestructura que el piloto necesita; la interfaz lo deja
abierto), bytea en Postgres (infla backups y WAL).

### D8 — Presupuestos y PDF
Importes en centavos `bigint` (ARS), sin floats ni descuentos. Totales y subtotales los calcula
el servicio con enteros de Python y se valida contra el máximo de `bigint` (`422 amount_too_large`).
Formato en PDF `1.150,00` (es-AR) con `Intl`-free helper propio y probado. El PDF se genera con
`reportlab` en un thread (`run_in_executor`) para no bloquear el loop; fuente embebida con
soporte de acentos y Ñ (DejaVu o similar de licencia libre, pineada en el repo/imagen). No se
persiste (evita un archivo con PII más para proteger) y no lleva DNI ni teléfono. El estado
"aceptado/rechazado" vive solo en `treatment_plan_decision`.
*Alternativa*: WeasyPrint, descartada por dependencias nativas en la imagen (Open Decision 6).

### D9 — Fusión de pacientes y exports
`patients/merge.py` suma, dentro de su transacción, `SELECT ... FROM clinical_record WHERE
clinic_id AND patient_id = :absorbido` (con el `FOR UPDATE` del paciente que la fusión ya toma) y
responde `409 patient_has_clinical_record`. `POST clinical-record` toma `FOR SHARE` sobre el
`patient` y verifica `archived_at IS NULL`: o la fusión bloquea la apertura (`patient_archived`) o
la apertura bloquea la fusión (`patient_has_clinical_record`). Las exportaciones de C-13/C-14 no
se tocan en su código: una prueba de contrato recorre las tablas con `clinic_id` del metadata y
exige que cada tabla clínica esté en una lista `EXCLUDED_FROM_EXPORT` (una tabla nueva sin
clasificar rompe la prueba).

### D10 — Superficie de API (todo bajo `/api`, todo `no-store`)

| Método y ruta | Rol |
|---|---|
| `POST/GET /patients/{pid}/clinical-record` | lector (POST: escritor) |
| `POST /clinical-records/{rid}/anamnesis`, `GET .../anamnesis`, `GET .../anamnesis/versions` | escritor / lector |
| `GET /odontogram/conditions` | lector |
| `POST /clinical-records/{rid}/odontogram/events`, `GET .../odontogram`, `GET .../odontogram/teeth/{tooth}/history` | escritor / lector |
| `POST/GET /clinical-records/{rid}/evolutions`, `POST .../evolutions/{eid}/corrections` | escritor / lector |
| `POST/GET /clinical-records/{rid}/attachments`, `GET .../attachments/{aid}/content`, `POST .../attachments/{aid}/removal` | escritor / lector |
| `POST/GET /clinical-records/{rid}/treatment-plans`, `GET .../{plan}`, `POST .../{plan}/versions`, `POST .../versions/{v}/decision`, `GET .../versions/{v}/pdf` | escritor / lector |
| `GET /clinical-records/{rid}/access-log` | solo admin |

### D11 — Frontend
`features/clinical/` con `api.ts` tipado (tipos de los schemas; sin `any`), un hook por recurso, y
estado en memoria (sin `localStorage`; la cola de reintentos de C-14 **no** incluye operaciones
clínicas). `Odontogram.tsx` dibuja cada pieza como un `<svg>` de 5 polígonos (M, D, O, V, L) más un
botón de pieza completa; foco por *roving tabindex*; el borrador de cambios es un `Map` en estado y
se envía en lotes ≤ 32. El acceso se oculta por rol con el `Principal` del cliente, pero la
seguridad es del backend (la UI nunca es el control). Descarga con `fetch` + `Blob` y
`URL.createObjectURL` que se revoca al terminar.

### D12 — Datos de prueba y PII
Toda fixture/seed clínica usa nombres, DNI y teléfonos ficticios (`example.com`, `+54 11 5550-xxxx`)
y textos obviamente sintéticos ("Paciente Prueba Ficticio"). Hay una prueba que captura logs
durante todas las operaciones clínicas y falla si aparece cualquier valor sintético sensible
(texto de evolución, nombre, teléfono). El texto clínico libre **no** pasa por `free_text.py`
(pensado para motivos sin datos personales): aquí el dato personal/clínico es legítimo y se
protege por acceso, no por validación de contenido.

## Risks / Trade-offs

- [Una anamnesis o evolución errónea no se puede borrar] → es intencional (Ley 26.529); la
  corrección con motivo es el camino; documentado en `docs/clinica/`.
- [Admin lee toda la historia] → decisión 1 abierta; la bitácora de accesos la hace auditable.
- [Subida de archivos = superficie de ataque] → tipos por contenido, tope duro, nombre opaco,
  descarga `attachment` + `nosniff`, sin URL pública; sin antivirus (riesgo aceptado hasta C-xx).
- [Disco local no escala ni es redundante] → volumen cubierto por el runbook de backups;
  `AttachmentStorage` permite migrar a S3 sin tocar tablas.
- [Lecturas escriben (auditoría) → más carga y locks] → INSERT sin contención (tabla append-only,
  sin unique entre requests); medir en el piloto.
- [Downgrade destruye datos clínicos] → ver Migration Plan; se exige backup previo.
- [Proyección `DISTINCT ON` crece con el historial] → índice dedicado; si una ficha supera ~10⁵
  eventos se evalúa una vista materializada (no previsto en el piloto).
- [Odontograma por teclado con 192 caras] → pruebas de accesibilidad y roving tabindex; riesgo de
  UX, se valida con la clínica piloto.
- [Firma simple puede confundirse con firma digital] → rotulada "firma simple" en UI y docs;
  Ley 25.506 diferida.

## Migration Plan

1. Precondición: C-14 archivado y desplegado (rol `app_writer`, usuario `turnos_app`).
2. `alembic upgrade head` (usuario de migración, `MIGRATION_DATABASE_URL`): crea enums, tablas,
   triggers, índices; `INSERT ... SELECT` del catálogo inicial para cada clínica existente;
   re-ejecuta `grant_app_writer` para que las tablas nuevas queden como append-only.
3. Desplegar `api` con el volumen `clinical_files` montado (permisos del usuario no root del contenedor).
4. Rollback: `alembic downgrade c14_hardening_pilot` elimina las tablas y enums nuevos. **Destruye
   los datos clínicos ya cargados**: antes de bajar con datos reales se exige un dump y no se
   recomienda; la mitigación operativa es desactivar el acceso por rol/flag y corregir hacia
   adelante. El downgrade se prueba con datos sintéticos en CI.
5. Backups: sumar las tablas y el volumen al runbook `docs/piloto/` (PITR cubre la base; el
   volumen requiere snapshot o `rsync` cifrado).

## Open Questions (deferibles sin cambiar specs ni tasks)

- Ubicación y rotación de la fuente TTF del PDF dentro de la imagen.
- Texto exacto de las leyendas del PDF y de la UI ("firma simple") a validar con el asesor legal.
- Si el set de estados incluye códigos de nomenclador (se resuelve en C-18).
