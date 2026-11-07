# Spec Delta — reminders/job-scheduling

## ADDED Requirements

### Requirement: Un reenvío manual pendiente sobrevive al recálculo

Un job `scheduled` con `manual_resend_at` no nulo SHALL NOT cancelarse por
`STEP_ELAPSED` durante un `reconcile` cuando el `starts_at_snapshot` sigue
coincidiendo con el turno, el turno sigue vigente y el paso sigue configurado.
Si el turno se cancela o el paso se elimina de la configuración, el job SHALL
quedar `cancelled`. El marcador `manual_resend_at` SHALL limpiarse cuando el job
deja de estar `scheduled` (por envío, fallo, skip o cancelación).

#### Scenario: Mutación no relacionada después del reenvío

- **WHEN** se ejecuta un `reconcile` del turno (p. ej. por una confirmación o
  cambio de configuración) después de un reenvío manual y el horario no cambió
- **THEN** el job reenviado sigue `scheduled` con `manual_resend_at` intacto y se
  envía en el próximo tick

#### Scenario: Cancelación después del reenvío

- **WHEN** recepción reenvía el paso de 3 h y después cancela el turno
- **THEN** el job reenviado queda `cancelled` y no se envía

#### Scenario: Paso eliminado de la configuración

- **WHEN** la clínica quita el paso de 24 h después de un reenvío manual
- **THEN** el job reenviado queda `cancelled` con el motivo de paso eliminado

### Requirement: Un reenvío manual se recalcula al reprogramar

Si el turno se reprograma a un horario donde el paso vuelve a quedar en el futuro,
el job SHALL recalcularse conforme a la spec principal (`scheduled_for` sobre el
nuevo `starts_at`, `starts_at_snapshot` actualizado, `manual_resend_at` limpiado);
si el paso ya no queda en el futuro para el nuevo horario, SHALL quedar `cancelled`
con `STEP_ELAPSED`.

#### Scenario: Reprogramación con paso en el futuro

- **WHEN** recepción reenvía el paso de 24 h y después reprograma el turno una
  semana adelante (donde el paso vuelve a ser futuro)
- **THEN** el job se recalcula con `scheduled_for` para la nueva fecha,
  `starts_at_snapshot` actualizado, `manual_resend_at` limpio, y sigue `scheduled`

#### Scenario: Reprogramación con paso vencido

- **WHEN** recepción reenvía el paso de 24 h y después reprograma el turno para
  dentro de 2 h (el paso de 24 h ya transcurrió respecto al nuevo horario)
- **THEN** el job queda `cancelled` con `STEP_ELAPSED` y no se envía
