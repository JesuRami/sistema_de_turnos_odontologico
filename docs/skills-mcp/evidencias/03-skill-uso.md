# Evidencia — Invocación y Uso de la Skill Propia

> **Skill**: `auditoria-escenarios-turnos`  
> **Ubicación**: `.agents/skills/auditoria-escenarios-turnos/SKILL.md`  
> **Change auditado**: C-11 `timeline-recordatorios`  
> **Fecha de ejecución**: 2026-11-07  

---

## 1. Contexto de activación y comando de invocación

Una vez preparados los artefactos iniciales de C-11 bajo OpenSpec (`proposal.md`, `design.md`, 6 delta-specs en `specs/` y `tasks.md`), se invocó a la skill propia para realizar el control de calidad previo a la implementación.

### Solicitud de invocación (Prompt)
```markdown
Usa la skill auditoria-escenarios-turnos para auditar los escenarios del change C-11
timeline-recordatorios contra la base de conocimiento (knowledge-base/04, 05, 06, 07, 10, 11),
las 13 reglas duras de AGENTS.md y los principios de Spec-Driven Development.

Analiza proposal.md, design.md, las 6 delta-specs y tasks.md.
Clasifica cada escenario en funcionamiento, error de negocio o borde; verifica que los THEN
sean observables; detecta reglas huérfanas o contradicciones internas y emite la tabla de
hallazgos por severidad con parches propuestos.
```

---

## 2. Resultado y trazabilidad de la auditoría

La skill auditó **27 requisitos** y **73 escenarios** distribuidos en las 6 delta-specs del change:
- `reminders/delivery-timeline`
- `reminders/manual-actions`
- `reminders/followup-board`
- `reminders/job-scheduling`
- `reminders/delivery-report`
- `web/agenda-board`

El informe exhaustivo generado por la skill se encuentra preservado como evidencia primaria en:
👉 [`docs/skills-mcp/evidencias/02-auditoria-informe.md`](02-auditoria-informe.md)

### Resumen cuantitativo de hallazgos
| Severidad | Cantidad | Impacto en el Change |
|---|---|---|
| **BLOQUEANTE** | 3 | Contradicciones lógicas que hacían insatisfacibles los tests o rompían la máquina de estados. |
| **MAYOR** | 13 | Guardas faltantes en contratos, escenarios con criterios no deterministas y discrepancias de APIs. |
| **MENOR** | 14 | Casos de borde de RBAC (`401`/`403`), precisión en payloads y alineación de routers. |
| **Total** | **30** | — |

---

## 3. Síntesis de los 3 hallazgos Bloqueantes detectados

1. **Hallazgo 1 (BLOQUEANTE) — Frontera de generación en el estado efectivo (`delivery-timeline`)**:
   - *Problema*: La regla exigía que el estado sea `failed` si hay un evento `failed` posterior al último `sent`. Al reenviar un job que falló, el job vuelve a `scheduled`, pero conserva en su historial el `sent` y `failed` del intento anterior. La regla original devolvía `failed` a pesar de que el nuevo intento estaba en curso (`scheduled`).
   - *Parche adoptado*: Limitar la derivación de estado a los eventos posteriores a la última marca de reset (`reminder_manual_resend`), catalogando los eventos anteriores como histórico de generación previa.
2. **Hallazgo 2 (BLOQUEANTE) — Orden de guardas en reenvío concurrente (`manual-actions`)**:
   - *Problema*: El diseño evaluaba el estado del job (`scheduled` → `409 reminder_pending`) antes del cooldown (guarda 8). Tras el primer clic, el job quedaba `scheduled`. El segundo clic concurrente caía en `reminder_pending` en vez de `resend_cooldown`, haciendo inalcanzable el escenario de doble clic.
   - *Parche adoptado*: Evaluar consentimiento, cooldown y tope **antes** del estado mutable del job, tratando `status = scheduled AND manual_resend_at IS NOT NULL` como reenvío en curso → `409 resend_cooldown`.
3. **Hallazgo 3 (BLOQUEANTE) — Contradicción al reprogramar tras un reenvío (`job-scheduling`)**:
   - *Problema*: El escenario inicial exigía que el job reenviado se cancelara siempre al mover el turno. Esto contradecía la spec principal y el comportamiento real del motor `reconcile` (que recalcula jobs pendientes si el nuevo horario los admite en el futuro). Además, si se cancelaba, `_insert` no podía volver a crearlo por el índice único existente.
   - *Parche adoptado*: Alinear la spec delta con la spec principal: si el turno se mueve a un horario futuro donde el paso vuelve a aplicar, el job se recalcula; si el paso ya transcurrió respecto al nuevo horario, se cancela con `STEP_ELAPSED`.

---

## 4. Aporte concreto de la skill al proyecto

La aplicación de `auditoria-escenarios-turnos` demostró un valor determinante:
- Evitó implementar código con bugs arquitectónicos graves que hubieran roto el pipeline de tests o causado bloqueos en producción.
- Obligó a que cada requisito tenga escenarios verificables con aserciones exactas (por ejemplo, eliminando alternativas ambiguas como *"1 o 0"* en el reporte de costos de entrega).
- Garantizó el cumplimiento estricto de las 13 reglas duras del proyecto, en especial el aislamiento multitenant (`clinic_id`), el manejo de concurrencia en base de datos real y la no exposición de PII en logs ni respuestas de timeline.
