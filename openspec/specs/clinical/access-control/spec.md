# clinical/access-control Specification

## Purpose
Fija quién puede tocar datos clínicos, con qué alcance y cómo queda registrado cada acceso, para cumplir la regla transversal "recepción no accede a datos clínicos" (`03`) y la trazabilidad exigida por Ley 26.529.

## Requirements

### Requirement: Recepción no accede a datos clínicos
Todo endpoint clínico (ficha, anamnesis, odontograma, evoluciones, adjuntos, planes, bitácora de accesos y PDF de presupuesto) SHALL responder `403 forbidden_role` a un principal `recepcion` sin ejecutar el handler ni escribir filas.

#### Scenario: Recepción lee la ficha
- **WHEN** un principal `recepcion` llama `GET /api/patients/{id}/clinical-record` de un paciente de su clínica
- **THEN** responde `403` con `forbidden_role` y no se crea ningún `clinical_access_event`

#### Scenario: Recepción intenta escribir
- **WHEN** un principal `recepcion` llama `POST` de evolución, anamnesis, adjunto, lote de odontograma o plan
- **THEN** responde `403 forbidden_role` y el conteo de filas de esas tablas no cambia

#### Scenario: Ningún endpoint clínico queda sin guarda
- **WHEN** la suite de rutas protegidas enumera todas las rutas bajo los prefijos clínicos
- **THEN** cada una declara roles explícitos y ninguna admite `recepcion`

### Requirement: Alcance del odontólogo y del admin
Un odontólogo SHALL acceder solo a pacientes que tengan al menos un turno con su `professional_id`; fuera de ese alcance SHALL responder `404 patient_not_found`. Un admin SHALL leer toda la clínica. Toda escritura clínica SHALL exigir un principal con `professional_id` y rol `odontologo` o `admin`; sin `professional_id` SHALL responder `403 professional_required`. El rol y el `professional_id` SHALL salir del principal, nunca del cuerpo. (TBD, Open Decisions 1 y 2)

#### Scenario: Odontólogo con turno propio
- **WHEN** el odontólogo A llama `GET /api/patients/{id}/clinical-record` de un paciente con un turno suyo
- **THEN** responde `200`

#### Scenario: Odontólogo sin relación con el paciente
- **WHEN** el odontólogo A consulta la ficha de un paciente que solo tiene turnos con el odontólogo B
- **THEN** responde `404 patient_not_found`, indistinguible de un paciente inexistente, y no se escribe evento de acceso

#### Scenario: Admin sin professional_id no escribe
- **WHEN** un admin sin `professional_id` llama `POST` de evolución
- **THEN** responde `403 professional_required` y no se crea la evolución

#### Scenario: Admin que también atiende
- **WHEN** un admin con `professional_id` crea una evolución para un paciente de la clínica
- **THEN** responde `201` y el `professional_id` de la evolución es el del principal

#### Scenario: Autoría no suplantable por cuerpo
- **WHEN** el cuerpo de una evolución trae `professional_id` ajeno
- **THEN** responde `422` por campo extra (extra='forbid') y no se crea la evolución

### Requirement: Aislamiento por clínica
Toda tabla clínica SHALL llevar `clinic_id` obligatorio y toda consulta SHALL filtrarse por el `clinic_id` del principal; un identificador de otra clínica SHALL responder `404`.

#### Scenario: Ficha de otra clínica
- **WHEN** un odontólogo de la clínica A pide la ficha de un paciente de la clínica B por su UUID
- **THEN** responde `404 patient_not_found` y no se escribe ningún evento de acceso en ninguna clínica

#### Scenario: Cada recurso hijo es hermético
- **WHEN** un principal de la clínica A usa el UUID de una anamnesis, evolución, adjunto, plan o versión de la clínica B en su ruta
- **THEN** responde `404` sin filtrar datos ni existencia

#### Scenario: FK compuesta impide mezclar clínicas
- **WHEN** se intenta insertar en la base una evolución de la clínica A que referencia un turno de la clínica B
- **THEN** Postgres rechaza el INSERT por la FK compuesta `(clinic_id, id)`

### Requirement: Auditoría de acceso en la misma transacción
Cada lectura o escritura clínica exitosa SHALL insertar un `clinical_access_event` append-only (actor, `record_id`, acción, tipo e id del objeto, instante), en la misma transacción que la operación, sin contenido clínico ni PII. Si el insert falla, la operación SHALL fallar entera.

#### Scenario: Lectura auditada
- **WHEN** un odontólogo lee el odontograma de un paciente
- **THEN** existe exactamente un evento con acción `odontogram_read`, su `user_id` y el `record_id`, y su `payload` no contiene nombre, teléfono, DNI ni texto clínico

#### Scenario: Descarga y PDF auditados
- **WHEN** se descarga un adjunto o se exporta un PDF de presupuesto
- **THEN** se inserta un evento `attachment_download` o `plan_pdf_export` con el id del objeto

#### Scenario: Falla de auditoría revierte la operación
- **WHEN** el INSERT del evento de acceso falla durante `POST` de evolución
- **THEN** no queda la evolución ni ningún otro efecto, y la respuesta es el 500 uniforme `internal_error`

#### Scenario: Bitácora inmutable
- **WHEN** se intenta `UPDATE` o `DELETE` sobre `clinical_access_event`, como dueño del schema y con el usuario `app_writer`
- **THEN** Postgres lo rechaza (trigger y falta de privilegio)

### Requirement: Consulta de la bitácora solo para admin
`GET /api/clinical-records/{record_id}/access-log` SHALL devolver los eventos con paginación por cursor y SHALL ser exclusivo del admin; odontólogo y recepción SHALL recibir `403 forbidden_role`.

#### Scenario: Admin pagina la bitácora
- **WHEN** el admin pide `limit=50` y hay 120 eventos
- **THEN** recibe 50 ordenados por `created_at` descendente y un `next_cursor`; el último lote no trae cursor

#### Scenario: Odontólogo no ve la bitácora
- **WHEN** un odontólogo llama el endpoint
- **THEN** responde `403 forbidden_role`

### Requirement: Respuestas clínicas sin caché ni PII en logs
Toda respuesta clínica SHALL incluir `Cache-Control: no-store`. Los logs y los mensajes de error SHALL no contener texto clínico, nombres, teléfonos ni DNI.

#### Scenario: Header no-store
- **WHEN** se lee cualquier recurso clínico
- **THEN** la respuesta lleva `Cache-Control: no-store`

#### Scenario: Error de validación sin eco
- **WHEN** una evolución inválida devuelve `422`
- **THEN** el cuerpo no incluye `input` ni el texto enviado

#### Scenario: Logs sin contenido clínico
- **WHEN** se crea una evolución con el texto sintético "Paciente Prueba Ficticio refiere dolor"
- **THEN** ningún registro de log capturado durante el request contiene ese texto
