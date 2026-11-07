# Checklist de escenarios — sistema de turnos odontológico

Usá este checklist después de inventariar los requisitos. No todas las filas aplican a
todos los changes: marcá las que sí y justificá por qué una fila crítica no aplica.

## 1. Concurrencia e idempotencia

- [ ] Dos altas simultáneas del mismo hueco: una gana, la otra recibe `409` con
      alternativos; la base impone el `EXCLUDE`, no un pre-chequeo.
- [ ] Doble tick del worker: cada `reminder_job` se envía una vez; el lease `sending`
      y `FOR UPDATE SKIP LOCKED` lo garantizan.
- [ ] Doble webhook de Meta: `provider_event_id` duplicado responde `200` sin efecto.
- [ ] Doble clic de recepción en reenviar/confirmar: no duplica el efecto ni el evento
      de auditoría; si hay carrera, una operación recibe un error de negocio claro.
- [ ] Reintento de programación del mismo turno: no duplica
      `(appointment_id, step, channel)`.
- [ ] Respuesta del paciente repetida (SÍ dos veces): la segunda es no-op auditado.

## 2. Aislamiento multi-tenant

- [ ] Toda tabla operativa nueva o tocada tiene `clinic_id` obligatorio.
- [ ] Las FK son compuestas por `(clinic_id, id)`.
- [ ] Un usuario de la clínica A no puede leer ni mutar un recurso de la clínica B
      (`404 not_found`, no `403`, para no filtrar existencia).
- [ ] Los agregados y reportes filtran por `clinic_id` en SQL, no en memoria.
- [ ] Un test demuestra el aislamiento cross-tenant.

## 3. RBAC

- [ ] Admin: CRUD y reportes.
- [ ] Recepción: agenda, turnos, confirmaciones manuales, lista de espera; no usuarios.
- [ ] Odontólogo: solo sus propios turnos (`professional_id`), lectura; no crea turnos
      ni ve la agenda de otros.
- [ ] Paciente: solo el `appointment_id` firmado por token; no autenticación general.
- [ ] Cada endpoint nuevo declara el rol y tiene un escenario de rol prohibido (`403`).

## 4. Auditoría y trazabilidad

- [ ] Toda mutación de agenda escribe `appointment_event` en la **misma transacción**;
      si la auditoría falla, la mutación falla (RN-GL-01).
- [ ] `appointment_event` y `delivery_event` son append-only (trigger/permisos).
- [ ] El evento lleva actor, timestamp y estado anterior/nuevo.
- [ ] Los payloads no llevan nombre, DNI, teléfono, email, link ni texto del paciente
      (regla 13).
- [ ] La timeline se lee de eventos inmutables, no del estado mutable del job
      (regla 8), cuando la regla lo exige.

## 5. Tiempo y zona horaria

- [ ] Las fechas se interpretan en la timezone de la clínica, no en UTC del servidor.
- [ ] Un turno que cruza medianoche o cambio de día cuenta en el día correcto.
- [ ] Los bordes son inclusivos/exclusivos de forma explícita (`[from, to)`).
- [ ] `now >= starts_at` bloquea operaciones sobre turnos ya iniciados.
- [ ] La ventana de cancelación se calcula con `starts_at - cancellation_window_hours`.
- [ ] La ventana de 24 h de WhatsApp se mide desde el último mensaje entrante y no se
      confunde con la ventana de cancelación.

## 6. Máquina de estados de turnos

- [ ] `pending → confirmed → present`; `present → absent/no_show` solo post-horario y
      por personal.
- [ ] `cancelled`, `absent` y `no_show` liberan el hueco.
- [ ] Un estado final no vuelve atrás; la repetición idempotente se audita como no-op.
- [ ] Un turno de recepción nace `confirmed`; uno online nace `pending`.
- [ ] Cancelar/reprogramar reconcilia los `reminder_job` en la misma transacción.

## 7. Recordatorios y WhatsApp

- [ ] Sin `whatsapp_opt_in=true` no se envía nada (RN-WA-01); el job queda `skipped`
      con motivo `no_consent`.
- [ ] Solo plantillas aprobadas, `es_AR`; nada de texto libre promocional (RN-WA-02).
- [ ] Fuera de la ventana de 24 h solo plantillas; dentro, la respuesta de sesión
      puede ser texto libre (RN-WA-03).
- [ ] Cada envío es idempotente por `(appointment_id, step, channel)` (RN-WA-04).
- [ ] Tras N fallos el job pasa a `failed` y escala a email si hay dirección; la
      timeline muestra el fallo y la escalada.
- [ ] El costo es atribuible por clínica y paso (RN-WA-05).
- [ ] Estados del proveedor: `sent → delivered → read`; `failed` puede llegar después
      de `sent`; el estado del job no retrocede aunque llegue fuera de orden.
- [ ] Deduplicación de mensajes entrantes y de eventos de estado.
- [ ] "NO" no cancela por sí solo; "STOP" da de baja el canal.

## 8. Datos y migraciones

- [ ] Una migración versionada por change; `down_revision` correcto.
- [ ] `CREATE INDEX CONCURRENTLY`; FK/CHECK `NOT VALID` → `VALIDATE`.
- [ ] Cambios de tipo en pasos; nada bloqueante sobre tablas calientes.
- [ ] Sin `SELECT *` en producción; columnas explícitas y paginación por cursor.
- [ ] Los reportes y timelines leen eventos inmutables cuando la regla lo exige.
- [ ] Datos de test sintéticos: nombres inventados, teléfonos ficticios,
      `@example.com`; nunca PII real.

## 9. Verificabilidad de los THEN

Buenos:

- `THEN responde 409 slot_taken y el turno original queda confirmed`
- `THEN existe un solo delivery_event sent para ese job`
- `THEN el job queda skipped con reason no_consent y no se llama al proveedor`
- `THEN el turno del 31/10 a las 23:30 locales cuenta en el rango que termina el 31/10`

Malos:

- `THEN el sistema funciona correctamente`
- `THEN se notifica al paciente` (¿por qué canal, con qué fila, cuántas veces?)
- `THEN no hay duplicados` (¿de qué entidad y con qué clave?)
- `THEN la UI muestra el estado` (¿qué texto/Estado y en qué vista?)

## 10. Cobertura mínima por requisito crítico

| Requisito | Funcionamiento | Error de negocio | Borde |
|-----------|----------------|------------------|-------|
| Invariante de agenda | alta válida | colisión `409` | doble request simultáneo |
| Recordatorio | envío programado | sin consentimiento | doble tick / proveedor caído |
| Webhook | firma válida + SÍ | firma inválida `401` | evento duplicado / fuera de orden |
| Timeline | job con eventos | turno de otra clínica `404` | sin jobs / job `sending` |
| Acción manual | reenvío/confirmación | turno cancelado `409` | doble clic / job en vuelo |
