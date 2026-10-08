# Funcionalidades

Historias de usuario del MVP **agenda-first**. Todo lo clínico, financiero y fiscal está excluido (ver alcance en `01`). Formato US-NNN con criterios de aceptación verificables y reglas trazadas a `05`.

## Épica 1: Configuración de agenda (admin)

### US-001 — Configurar profesionales y sillones
**Como** administrador **Quiero** dar de alta profesionales (nombre, color, duración default, buffer) y sillones **Para** que la agenda refleje los recursos reales de la clínica.

**Criterios de aceptación**:
- [ ] CA-1: Crear/editar/desactivar profesional y sillón; desactivar impide nuevas reservas pero conserva historial.
- [ ] CA-2: El color del profesional se refleja en la vista de agenda.
- [ ] CA-3: Toda operación queda auditada.

**Reglas relacionadas**: RN-AG-05, RN-GL-01.

### US-002 — Definir horarios semanales por profesional y sillón
**Como** administrador **Quiero** cargar la plantilla semanal (día, hora inicio/fin, duración de slot, vigencia) **Para** que el sistema calcule huecos ofrecibles.

**Criterios de aceptación**:
- [ ] CA-1: Reglas por (profesional, sillón, día de semana) con vigencia desde/hasta.
- [ ] CA-2: El sistema rechaza reglas solapadas para el mismo par profesional-sillón-día.
- [ ] CA-3: Sin regla vigente, el profesional no aparece como reservable.

**Reglas relacionadas**: RN-AG-05, RN-AG-03.

### US-003 — Gestionar bloqueos (vacaciones, feriados, mantenimiento)
**Como** administrador **Quiero** bloquear rangos por profesional/sillón con motivo **Para** cerrar la agenda en ausencias y feriados.

**Criterios de aceptación**:
- [ ] CA-1: Bloqueo exige al menos un objetivo (profesional o sillón) y motivo.
- [ ] CA-2: Si el rango pisa turnos vigentes, el sistema los lista y exige reprogramarlos/cancelarlos primero (una transacción).
- [ ] CA-3: Los huecos bloqueados desaparecen de la disponibilidad online inmediatamente.

**Reglas relacionadas**: RN-BL-01, RN-BL-02, RN-BL-03, RN-AG-05.

### US-004 — Configurar políticas de la clínica
**Como** administrador **Quiero** ajustar ventana de cancelación, pasos de recordatorio, tope de sobreturnos y expiración de ofertas **Para** adaptar el sistema a la operatoria real.

**Criterios de aceptación**:
- [ ] CA-1: Parámetros editables con valores por defecto sanos (24 h, 72/24/3 h, 2 sobreturnos, 4 h oferta).
- [ ] CA-2: Cambiar pasos de recordatorio solo afecta turnos futuros, no jobs ya programados.

**Reglas relacionadas**: RN-CX-01, RN-SB-03, RN-LE-03.

## Épica 2: Agenda de recepción (operación diaria)

### US-010 — Ver agenda día/semana por profesional y sillón
**Como** recepción **Quiero** ver la agenda con filtros por profesional, sillón y estado, en vista día y semana **Para** gestionar el día en una sola pantalla.

**Criterios de aceptación**:
- [ ] CA-1: Vista día (default) y semana; código de color por profesional y distintivo por estado.
- [ ] CA-2: Los sobreturnos y bloqueos se distinguen visualmente.
- [ ] CA-3: Carga de una semana completa en < 2 s con 500 turnos (objetivo de performance).

**Reglas relacionadas**: RN-AG-01, RN-SB-01.

### US-011 — Crear turno desde recepción
**Como** recepción **Quiero** crear un turno buscando al paciente o cargándolo nuevo **Para** agendar llamados y presenciales.

**Criterios de aceptación**:
- [ ] CA-1: Búsqueda de paciente por nombre/teléfono; alta rápida con nombre + contacto.
- [ ] CA-2: Si el hueco colisiona, el sistema lo rechaza salvo sobreturno explícito con motivo (rol autorizado).
- [ ] CA-3: El turno de recepción nace `confirmed` y genera jobs de recordatorio.

**Reglas relacionadas**: RN-AG-01, RN-SB-01, RN-SB-02, RN-ST-02, RN-ON-05.

### US-012 — Reprogramar y cancelar con control
**Como** recepción **Quiero** mover o cancelar turnos sin restricción de ventana **Para** resolver urgencias y pedidos por teléfono.

**Criterios de aceptación**:
- [ ] CA-1: Reprogramar revalida solapamientos atómicamente; si falla, el turno queda intacto.
- [ ] CA-2: Cancelar exige motivo y dispara jobs-cancel + evaluación de lista de espera.
- [ ] CA-3: Todo cambio escribe auditoría con antes/después.

**Reglas relacionadas**: RN-AG-06, RN-CX-02, RN-CX-03, RN-CX-04, RN-GL-01.

### US-013 — Registrar presente / ausente del día
**Como** recepción **Quiero** marcar presente/ausente/no-show en los turnos del día **Para** cerrar el día y alimentar ausentismo real.

**Criterios de aceptación**:
- [ ] CA-1: Solo turnos de hoy (o pasados) admiten presente/ausente; futuros no.
- [ ] CA-2: Marcar ausente libera el recurso para sobreturno de último minuto si se configura.

**Reglas relacionadas**: RN-ST-01, RN-ST-03, RN-AG-02.

## Épica 3: Reserva online 24/7 (paciente sin cuenta)

### US-020 — Reservar turno por link público
**Como** paciente **Quiero** elegir profesional, día y hora libres desde el link de la clínica **Para** reservar sin llamar.

**Criterios de aceptación**:
- [ ] CA-1: Flujo en ≤ 4 pasos: profesional → día → hora → datos. Mobile-first.
- [ ] CA-2: Solo huecos reales (horario − bloqueos − turnos vigentes − buffer).
- [ ] CA-3: La disponibilidad no expone datos de otros pacientes.
- [ ] CA-4: La reserva exige nombre + contacto + opt-in WhatsApp si deja teléfono; nace `pending`.
- [ ] CA-5: Rate-limit y anti-abuso activos.

**Reglas relacionadas**: RN-ON-01, RN-ON-02, RN-ON-03, RN-ON-05, RN-ST-02, RN-AG-03.

### US-021 — Confirmar / cancelar / reprogramar con token
**Como** paciente **Quiero** gestionar mi turno desde el link que me llegó (sin contraseña) **Para** confirmar, cancelar o mover mi turno.

**Criterios de aceptación**:
- [ ] CA-1: Confirmar en un toque; cancela jobs innecesarios y actualiza estado.
- [ ] CA-2: Cancelar dentro de la ventana funciona online; fuera de ventana deriva a la clínica con mensaje claro.
- [ ] CA-3: Reprogramar ofrece solo huecos válidos del mismo profesional (o cualquiera si la clínica lo permite).
- [ ] CA-4: Token con TTL; expirado muestra instrucciones para contactar a la clínica.

**Reglas relacionadas**: RN-CX-01, RN-CX-02, RN-ON-04, RN-ST-01.

### US-022 — Anotarse en lista de espera
**Como** paciente **Quiero** anotarme si no hay hueco que me sirva **Para** que me avisen cuando se libere uno.

**Criterios de aceptación**:
- [ ] CA-1: Anotación con preferencia de profesional y rango horario.
- [ ] CA-2: Sin duplicados activos para el mismo profesional.
- [ ] CA-3: La oferta llega por WhatsApp/email con expiración visible; aceptar crea el turno.

**Reglas relacionadas**: RN-LE-01, RN-LE-02, RN-LE-03, RN-LE-04.

## Épica 4: Recordatorios y confirmaciones (motor)

### US-030 — Recibir recordatorios multicanal
**Como** paciente **Quiero** recibir recordatorios (72/24/3 h) por WhatsApp con respaldo por email **Para** no olvidar mi turno.

**Criterios de aceptación**:
- [ ] CA-1: Tres pasos configurables; cada envío idempotente y trazable.
- [ ] CA-2: Sin opt-in de WhatsApp no hay envío por ese canal; el email cubre si existe.
- [ ] CA-3: El mensaje incluye confirmar/cancelar en un toque (botones o link con token).

**Reglas relacionadas**: RN-WA-01, RN-WA-02, RN-WA-04, RN-WA-05.

### US-031 — Confirmar por WhatsApp con SÍ/NO
**Como** paciente **Quiero** responder SÍ para confirmar o NO/pedir reprogramar **Para** resolver sin abrir el navegador.

**Criterios de aceptación**:
- [ ] CA-1: "SÍ" confirma el turno y actualiza agenda + cancela jobs futuros innecesarios.
- [ ] CA-2: "NO" o "reprogramar" deriva al link de gestión o a la clínica según ventana.
- [ ] CA-3: "STOP"/opt-out bloquea el canal inmediatamente con confirmación.

**Reglas relacionadas**: RN-WA-01, RN-WA-03, RN-CX-01, RN-ST-01.

### US-032 — Operar recordatorios desde recepción
**Como** recepción **Quiero** ver qué recordatorios se enviaron/entregaron/leyeron/fallaron por turno **Para** llamar a quien no confirmó.

**Criterios de aceptación**:
- [ ] CA-1: Timeline de entregas por turno con estados del proveedor.
- [ ] CA-2: Reenvío manual y confirmación manual con auditoría.
- [ ] CA-3: Fallos reiterados escalan a email o alerta visible.

**Reglas relacionadas**: RN-WA-04, RN-WA-05, RN-GL-01.

## Épica 5: Lista de espera operativa (recepción)

### US-040 — Gestionar cola y ofertas
**Como** recepción **Quiero** ver la cola, ofrecer huecos manualmente y seguir ofertas pendientes/vencidas **Para** llenar cancelaciones el mismo día.

**Criterios de aceptación**:
- [ ] CA-1: Cola ordenada por antigüedad con filtros por profesional y rango.
- [ ] CA-2: Ofrecimiento manual o automático con expiración; vencida rota al siguiente.
- [ ] CA-3: Aceptar convierte a turno con origen `waitlist`; todo auditado.

**Reglas relacionadas**: RN-LE-02, RN-LE-03, RN-LE-04, RN-LE-05.

## Épica 6: Reportes mínimos y administración

### US-050 — Reportes de ocupación, ausentismo y cancelaciones
**Como** administrador **Quiero** ver ocupación por profesional/sillón, ausentismo, cancelaciones por motivo y conversión de lista de espera **Para** decidir horarios y dotación.

**Criterios de aceptación**:
- [ ] CA-1: Cuatro reportes con rango de fechas y exportación CSV.
- [ ] CA-2: Ausentismo distingue `no_show` de cancelación tardía.
- [ ] CA-3: Números calculados sobre `appointment_event` (auditoría), no sobre estados mutados.

**Reglas relacionadas**: RN-ST-04, RN-CX-04, RN-GL-01.

### US-051 — Usuarios, auditoría y exportación
**Como** administrador **Quiero** gestionar usuarios, consultar auditoría por turno y exportar los datos de agenda **Para** operar con control y sin lock-in.

**Criterios de aceptación**:
- [ ] CA-1: Alta/baja de usuarios con rol; el odontólogo queda atado a su profesional.
- [ ] CA-2: Auditoría por turno con actor, antes/después y timestamp; inmutable.
- [ ] CA-3: Exportación completa (turnos, pacientes operativos, eventos) en CSV/JSON con un clic.

**Reglas relacionadas**: RN-GL-01, RN-GL-04.
