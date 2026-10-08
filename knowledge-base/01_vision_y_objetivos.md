# Visión y Objetivos

## Propósito del sistema

Los consultorios y clínicas odontológicas argentinas gestionan agenda, historia clínica, cobros y obras sociales con herramientas fragmentadas, lo que genera solapamientos, ausentismo, presupuestos perdidos, débitos de obras sociales y conciliación manual. Falta cerrar el circuito turno → odontograma → cobro → ARCA → liquidación OS → recall por WhatsApp.

Este sistema ataca ese problema por fases. La v1.0 cierra el primer eslabón —el circuito de agenda— con una convicción arquitectónica explícita: **si la agenda no es confiable (sin solapamientos, con estados trazables y recordatorios que efectivamente llegan), todo lo que se construya encima (clínica, cobros, ARCA, obras sociales) hereda datos corruptos**. Por eso la agenda no es "un CRUD de turnos": es el núcleo de consistencia del producto.

## Objetivos por actor

| Actor | Objetivo principal | Objetivos secundarios |
|-------|--------------------|-----------------------|
| Administrador de clínica | Operar la agenda multi-sillón sin solapamientos ni huecos muertos | Configurar profesionales, sillones, horarios y bloqueos; medir ocupación y ausentismo |
| Recepción | Gestionar el día en minutos: confirmar, reprogramar, cubrir huecos | Cargar sobreturnos controlados, operar lista de espera, registrar ausentes |
| Odontólogo | Llegar al sillón con la agenda del día clara y sin sorpresas | Ver sus turnos por día/semana, bloquear vacaciones, señalar inasistencias |
| Paciente | Reservar, confirmar, cancelar o reprogramar sin llamar por teléfono | Recibir recordatorios por WhatsApp, entrar en lista de espera si no hay hueco |

## Alcance v1.0 (MVP agenda-first)

- Agenda multi-profesional y multi-sillón con vista día/semana, duraciones variables por tipo de práctica y prevención dura de solapamientos.
- Reserva online 24/7 por link público (web/redes) con confirmación, cancelación y reprogramación por parte del paciente.
- Gestión de recepción: estados de turno, sobreturnos controlados, bloqueos de agenda, lista de espera con ofrecimiento de huecos.
- Motor de recordatorios por WhatsApp Business API + email de respaldo, con ventana de cancelación configurable y confirmación en un toque.
- Roles y permisos básicos (4 roles), multi-profesional desde el día 1, un tenant por clínica.
- Reportes mínimos de agenda: ocupación, ausentismo, cancelaciones, lista de espera convertida.
- Seguridad mínima auditable y exportación de datos de agenda en formato abierto.

## Fuera de alcance

Explícitamente NO entra en v1.0 (fases posteriores, ver `10_preguntas_abiertas.md`):

- Historia clínica, anamnesis, odontograma, periodontograma, imágenes, evoluciones.
- Planes de tratamiento, presupuestos, señas, caja, Mercado Pago, cuenta corriente.
- Factura electrónica ARCA, nomencladores de obras sociales, validación, autorizaciones, liquidación.
- Portal del paciente con autenticación, app nativa, videoconsulta.
- Multi-sucursal plena, comisiones, laboratorio, stock/esterilización, CRM/marketing.
- IA clínica (CDSS, dictado por voz, análisis de rx), firma digital verificada, API pública, Google Calendar.

## Métricas de éxito

| Métrica | Umbral v1.0 | Cómo se mide |
|---------|-------------|--------------|
| Solapamientos en agenda | 0 (invariante dura, no objetivo) | Auditoría de integridad sobre tabla de turnos |
| Ausentismo | Reducción ≥ 20% vs. línea base de la clínica a 90 días | Reporte de ausentismo (fase pre/post recordatorios) |
| Confirmación vía recordatorio | ≥ 60% de turnos confirmados antes de T-24h | Eventos de confirmación del motor de recordatorios |
| Huecos recuperados por lista de espera | ≥ 10% de cancelaciones reasignadas | Conversión lista de espera → turno confirmado |
| Reserva online sin fricción | ≥ 30% de turnos creados por canal online a 90 días | Origen del turno (recepción vs. online) |
| Tiempo de gestión diaria (recepción) | Agenda del día gestionable en < 15 min | Observación operativa en piloto (cualitativo) |

> Nota de arquitecto: la métrica de ausentismo es la única que justifica el costo de WhatsApp Business API. Si tras el piloto no mueve la aguja, el modelo de costos del recordatorio debe revisarse antes de escalar (ver `11_whatsapp_y_recordatorios.md`).
