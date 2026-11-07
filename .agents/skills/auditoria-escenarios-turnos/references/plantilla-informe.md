# Plantilla de informe de auditoría

Copiá esta estructura en la respuesta. No agregues secciones que no aporten.

```markdown
# Auditoría de escenarios — <change>

**Alcance**: <capabilities y archivos revisados>
**Fuentes**: KB 05/06/07/10/11, AGENTS.md, openspec/specs/**
**Fecha**: <YYYY-MM-DD>

## Resumen

<2-4 líneas: cuántos requisitos, cuántos escenarios, cuántos hallazgos por severidad
y cuál es el riesgo principal.>

## Hallazgos

| # | Severidad | Requisito / escenario | Archivo:línea | Regla / fuente | Qué falta | Parche propuesto |
|---|-----------|-----------------------|---------------|----------------|-----------|------------------|
| 1 | BLOQUEANTE | ... | ... | ... | ... | ... |

## Cobertura

| Requisito | Funcionamiento | Error de negocio | Borde | Verificable |
|-----------|----------------|------------------|-------|-------------|
| ... | sí/no | sí/no | sí/no | sí/no |

## Preguntas abiertas

- <pregunta concreta, con la decisión que falta y quién debería tomarla>

## Lo que no es un hallazgo

<Opcional: cosas que revisaste y están bien, para que el autor no las vuelva a tocar.>
```

## Ejemplo de hallazgo bien formado

| # | Severidad | Requisito / escenario | Archivo:línea | Regla / fuente | Qué falta | Parche propuesto |
|---|-----------|-----------------------|---------------|----------------|-----------|------------------|
| 1 | BLOQUEANTE | Requirement: Reenvío manual | specs/reminders/manual-actions/spec.md:18 | RN-WA-04, RN-GL-01 | El escenario dice "se reenvía el recordatorio" sin decir qué pasa con el job ya enviado ni cómo se evita un doble envío si dos recepcionistas hacen clic a la vez. | Agregar: el reenvío toma `FOR UPDATE` del job; si está `sending` → `409 reminder_in_progress`; si el turno está cancelado o iniciado → `409`; el job vuelve a `scheduled` con `available_at=now` y se registra un `delivery_event` `sent` con `manual=true`; dos clics simultáneos no generan dos envíos. |

## Ejemplo de THEN no verificable

Antes:

```markdown
#### Scenario: Reenvío exitoso
- **WHEN** recepción reenvía el recordatorio
- **THEN** el paciente recibe el mensaje correctamente
```

Después:

```markdown
#### Scenario: Reenvío exitoso
- **WHEN** recepción reenvía un job `delivered` de WhatsApp de un turno futuro
- **THEN** el job vuelve a `scheduled` con `available_at = now`, se registra un
  `delivery_event` `sent` con `payload.manual = true` y el worker lo envía una sola vez
```

## Ejemplo de cobertura incompleta

Un requisito de timeline con solo el camino feliz es **MAYOR** si no tiene:

- error de negocio: turno de otra clínica → `404`, o turno cancelado → `409` para acciones;
- borde: turno sin jobs, job `sending`, evento `read` antes de `delivered`, dos eventos en
  el mismo instante.
