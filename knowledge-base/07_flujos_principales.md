# Flujos Principales

Cada flujo extremo a extremo: disparador, actor, pasos por componente, errores. Los códigos RN referencian `05_reglas_de_negocio.md`.

## Flujo 1: Reserva online (paciente nuevo o recurrente)

**Disparador**: el paciente abre `/b/:slug`.
**Actor**: paciente (sin cuenta).

**Pasos**:
1. Frontend público pide disponibilidad (`GET /api/booking/:slug/availability?professional_id&from&to`).
2. API calcula huecos: `schedule_rule` − `block` − turnos vigentes − buffers. Solo devuelve fecha/hora/profesional (RN-ON-01).
3. Paciente elige hueco y deja nombre + contacto + opt-in WhatsApp.
4. API normaliza teléfono a E.164, hace match de paciente existente (RN-ON-05) o crea uno, inserta turno `pending` con `manage_token` en transacción con revalidación de exclusión (RN-AG-01). Si otro lo tomó en el medio, falla con "hueco ya ocupado, elegí otro".
5. API programa `reminder_job` (72/24/3 h) y envía confirmación inmediata con link de gestión.
6. Paciente recibe link; el turno aparece en la agenda de recepción en tiempo real.

```
Paciente → Frontend público → API → DB (turno pending + jobs)
                                        ← huecos / confirmación + token
```

**Casos de error**:
- Hueco tomado entre consulta y reserva → 409 + huecos alternativos cercanos.
- Sin contacto válido → 422, no se crea nada.
- Rate-limit excedido → 429 con reintento indicado.
- Teléfono inválido para WhatsApp → se acepta con email como canal y aviso.

## Flujo 2: Confirmar / cancelar / reprogramar (paciente con token)

**Disparador**: click en link de gestión, botón de WhatsApp o respuesta SÍ/NO.
**Actor**: paciente.

**Pasos**:
1. Frontend o webhook resuelve el token (`manage_token_hash` → appointment). Token expirado o revocado → pantalla de contacto a clínica.
2. Confirmar: `pending → confirmed`, se cancelan jobs redundantes, evento de auditoría.
3. Cancelar: valida ventana (RN-CX-01). Dentro de ventana: `→ cancelled` + motivo + cancela jobs + evalúa lista de espera (RN-LE-02). Fuera de ventana: rechazo amable con teléfono de la clínica.
4. Reprogramar: muestra huecos del mismo profesional; al elegir, transacción atómica que revalida exclusión (RN-AG-06) y reprograma jobs.
5. Respuesta WhatsApp SÍ/NO: el webhook de Meta entra por `POST /webhooks/whatsapp`, valida firma, mapea al turno por `provider_message_id`/contexto y ejecuta el mismo núcleo que el link (idempotente).

```
Paciente → (link | WhatsApp → webhook) → API → DB (estado + auditoría + jobs)
```

**Casos de error**:
- Doble click / doble SÍ → idempotencia: segundo evento es no-op auditado.
- Cancelar turno ya pasado → 422.
- Webhook con firma inválida → 401, se descarta y se loguea.

## Flujo 3: Recordatorios automáticos (motor programado)

**Disparador**: cron del worker (cada minuto).
**Actor**: sistema.

**Pasos**:
1. Worker reclama jobs vencidos (`scheduled_for <= now`, `status=scheduled`) con lock pesimista (`FOR UPDATE SKIP LOCKED`) para no duplicar entre réplicas.
2. Por cada job: verifica que el turno siga vigente (si se canceló, job → `cancelled`, RN-CX-03); verifica opt-in del canal (RN-WA-01); verifica ventana 24 h de Meta para elegir plantilla vs. seguimiento.
3. Envía por Cloud API (WhatsApp) o email; guarda `provider_message_id`; job → `sent`.
4. Webhooks de entrega/lectura actualizan a `delivered/read`; fallos reintentan con backoff hasta N intentos → `failed` + escalado a email.
5. Si el paciente confirma por cualquier vía, los jobs futuros del turno se cancelan.

```
Cron → Worker → DB (reclamo) → Meta/Email → DB (estados) ← webhooks
```

**Casos de error**:
- Caída del worker → los jobs persisten; al volver se procesan los vencidos (con tope de antigüedad: no enviar recordatorio de un turno ya pasado).
- Plantilla rechazada por Meta → job a `failed` con alerta a admin + fallback a email.
- Paciente con opt-out a mitad de secuencia → jobs restantes a `skipped`.

Detalle completo del motor en `11_whatsapp_y_recordatorios.md`.

## Flujo 4: Gestión de agenda por recepción (día operativo)

**Disparador**: inicio del día / llamado / paciente en mostrador.
**Actor**: recepción (autenticada).

**Pasos**:
1. Recepción abre agenda del día (filtro profesional/sillón/estado). Ve pendientes sin confirmar destacados (los que no respondieron T-24 h).
2. Crear turno: busca paciente (trigram) o alta rápida; elige hueco; si colisiona, el sistema ofrece alternativos o sobreturno explícito con motivo (RN-SB-01/02).
3. Confirmación manual / reenvío de recordatorio para no-respondedores (US-032).
4. Marcar presente a la llegada; ausente/no-show al cierre para los no presentados.
5. Cancelación con motivo → jobs cancelados + oferta automática a lista de espera; recepción puede forzar oferta manual a un paciente prioritario (auditado como excepción a FIFO con motivo).
6. Cierre del día: revisión de estados; ningún turno de hoy queda en `pending` sin seguimiento (reporte de "pendientes sin confirmar").

```
Recepción → SPA → API → DB (turnos + eventos + jobs + ofertas)
```

**Casos de error**:
- Sobreturno que supera el tope → exige admin o se rechaza.
- Bloqueo que pisa turnos → operación detenida hasta resolver afectados (RN-BL-02).
- Paciente duplicado (dos fichas mismo teléfono) → fusión asistida por recepción (auditada), no borrado.

## Flujo 5: Hueco liberado → lista de espera → turno (automático + manual)

**Disparador**: cancelación (cualquier origen).
**Actor**: sistema primero, humanos después.

**Pasos**:
1. La cancelación dispara evaluación: buscar entries `waiting` compatibles (profesional + rango) ordenadas por antigüedad.
2. Crear `waitlist_offer` con expiración (default 4 h) y notificar por WhatsApp/email con botones aceptar/rechazar.
3. Aceptar (dentro de expiración): crea turno `confirmed` origen `waitlist`, valida exclusión, cancela otras ofertas de la entry, entry → `converted`.
4. Vencer sin respuesta: offer → `expired`, entry → `waiting`, siguiente de la cola. Tres vencimientos → entry `expired`.
5. Recepción ve todo en el panel de cola y puede intervenir (ofrecer manualmente, retirar, priorizar con motivo auditado).

**Casos de error**:
- Dos ofertas aceptadas para el mismo hueco (carrera) → la primera gana; la segunda recibe "hueco ocupado" + vuelve a cola prioritaria.
- Paciente que ya reservó por otro lado → al aceptar, colisión detectada; se le ofrecen alternativas.
