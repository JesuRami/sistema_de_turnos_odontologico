# Evidencia — Revisión Crítica y Análisis «Antes y Después»

> **Change**: C-11 `timeline-recordatorios`  
> **Instrumentos**: Skill propia `auditoria-escenarios-turnos` + Servidor MCP Context7  
> **Fecha**: 2026-11-07  

---

## 1. Introducción y propósito del análisis crítico

En el marco del TP (Metodología I, sección 8), es obligatorio someter los resultados preliminares generados por el agente a una revisión crítica rigurosa. Esta etapa busca evidenciar que el equipo no acepta pasivamente las salidas de la inteligencia artificial, sino que aplica procedimientos formales de auditoría y validación documental para identificar inconsistencias sutiles, contratos insatisfacibles o colisiones con las reglas del sistema.

La ejecución de la skill propia `auditoria-escenarios-turnos` sobre el borrador inicial de C-11 arrojó **3 defectos BLOQUEANTES** y **1 defecto MAYOR de verificabilidad**. A continuación se detalla cómo se detectó cada uno, qué fuente técnica permitió su corrección y la comparación explícita del **Antes y Después**.

---

## 2. Defecto Crítico 1: La frontera de generación en el estado efectivo del timeline

### 2.1 Cómo se detectó y qué regla infringía
- **Componente**: `openspec/changes/c-11-timeline-recordatorios/specs/reminders/delivery-timeline/spec.md`
- **Regla / Fuente**: RN-WA-04 (máquina de estados de recordatorios) y diseño D2 (`design.md`).
- **Problema detectado**: La regla de cálculo del estado efectivo decía textualmente:
  > *"estado `failed` si hay un evento `failed` posterior al último `sent`"*.
  
  Cuando recepción reenvía manualmente un recordatorio que falló, el job vuelve al estado `scheduled` para el próximo tick del worker. Sin embargo, en la base de datos inmutable de eventos (`delivery_event`), el job aún conserva los eventos `sent` y `failed` del intento fallido previo. Dado que ese `failed` es posterior al `sent` del primer intento, la fórmula del requisito evaluaba siempre `failed`, contradiciendo el escenario que exigía que la UI mostrara `scheduled` (reenvío en curso). El test propuesto en `tasks.md` (3.2) estaba condenado a fallar irremediablemente.

### 2.2 Comparativa Antes y Después

| Elemento | ANTES (Borrador con defecto) | DESPUÉS (Corregido tras auditoría) |
|---|---|---|
| **Requisito en Spec** (`spec.md`) | *"Para el último envío SHALL aplicar esta precedencia: `read` si hay `read` posterior al último `sent`; si no `delivered`; si no `failed` si hay `failed` posterior; si no, el estado del job."* | *"El cálculo SHALL considerar únicamente los eventos posteriores al último reset de reenvío (`reminder_manual_resend` o `manual_resend_at`). Los eventos anteriores SHALL mostrarse como `envío anterior` y SHALL NOT incidir en el estado efectivo."* |
| **Escenario** (`spec.md`) | **THEN** el paso muestra estado `scheduled`, el evento `sent` anterior y el evento `manual_resend`, en orden. | **THEN** el paso muestra `scheduled` porque el `failed` anterior es previo al reset; el `sent` anterior y el `manual_resend` aparecen marcados como envío anterior en el historial. |
| **Diseño D2** (`design.md`) | Contenía la noción de "última generación" pero no estaba formalizada en el contrato de la especificación. | Se formalizó el contrato matemático de frontera temporal entre generaciones de envío. |

---

## 3. Defecto Crítico 2: Orden de guardas en reenvíos concurrentes (Carrera de doble clic)

### 3.1 Cómo se detectó y qué regla infringía
- **Componente**: `specs/reminders/manual-actions/spec.md` frente a `design.md:165-181`.
- **Regla / Fuente**: RN-WA-04, DD-05 y checklist de concurrencia.
- **Problema detectado**: El diseño preliminar proponía evaluar las guardas del reenvío en este orden:
  1. Turno vigente.
  2. Turno no iniciado.
  3. Job existe.
  4. Paso aplicable.
  5. *Estado del job: si está `scheduled` → `409 reminder_pending`*.
  ...
  8. *Cooldown de 60 segundos y tope diario → `409 resend_cooldown`*.

  Bajo este orden, si una recepcionista hace doble clic rápido o dos recepcionistas reenvían al mismo tiempo, la primera petición procesa el reenvío y coloca el job en estado `scheduled`. La segunda petición concurrente, al evaluar la guarda 5, encontraba el job en `scheduled` y respondía inmediatamente `409 reminder_pending`. En consecuencia, el código `409 resend_cooldown` (con el header/campo `retry_after_s > 0`) era **técnicamente inalcanzable**. El escenario de doble clic fallaba la aserción de negocio.

### 3.2 Comparativa Antes y Después

| Elemento | ANTES (Borrador con defecto) | DESPUÉS (Corregido tras auditoría) |
|---|---|---|
| **Orden de Guardas** (`design.md`) | 1..4 preliminares → 5. Estado mutable del job (`scheduled` → `reminder_pending`) → 8. Cooldown / tope. | 1..4 preliminares → **5. Consentimiento y cooldown/tope** → **6. Estado del job**. Si el job está `scheduled` pero `manual_resend_at IS NOT NULL`, se trata como reenvío en curso → `409 resend_cooldown`. |
| **Escenario Doble Clic** (`spec.md`) | Inconsistente con el orden del diseño (arrojaba `reminder_pending` en tiempo de ejecución). | Responde determinísticamente `409 resend_cooldown` con `retry_after_s > 0`. |
| **Escenario Concurrente** (`spec.md`) | Exigía `resend_cooldown` sin especificar que `reminder_pending` no debía emitirse. | Aserta explícitamente: *"la segunda responde `409 resend_cooldown` con `retry_after_s > 0`, no `reminder_pending`"*. |

---

## 4. Defecto Crítico 3: Contradicción de reprogramación tras un reenvío

### 4.1 Cómo se detectó y qué regla infringía
- **Componente**: `specs/reminders/job-scheduling/spec.md` frente a `openspec/specs/reminders/job-scheduling/spec.md` (spec principal de C-09) y `backend/app/modules/reminders/scheduling.py`.
- **Regla / Fuente**: Invariantes de scheduling y reconciliación de agenda.
- **Problema detectado**: El escenario redactado inicialmente establecía:
  > *"WHEN recepción reenvía el paso de 24 h y después mueve el turno a otro día, THEN el job reenviado queda `cancelled` y se programan los pasos del nuevo horario"*.

  Al contrastar esto con la implementación del motor en `scheduling.py:166-171` y la spec principal de C-09 ("Turno movido una semana adelante"), se descubrió que el motor **no cancela** los jobs de pasos futuros cuando el turno se reprograma; los **refresca** recalculando su `scheduled_for` respecto a la nueva fecha de inicio. Cancelar el job violaba el contrato principal e impedía que `_insert` pudiera recrearlo debido a la constraint única existente `(appointment_id, step, channel)`.

### 4.2 Comparativa Antes y Después

| Elemento | ANTES (Borrador con defecto) | DESPUÉS (Corregido tras auditoría) |
|---|---|---|
| **Comportamiento ante reprogramación** | Cancelación forzada e incondicional del job de recordatorio. | **Recálculo contextual**: Si el nuevo horario permite que el paso quede en el futuro, el job se recalcula (`scheduled_for` nuevo, `manual_resend_at` limpio); si el paso ya transcurrió en el nuevo horario, se cancela con `STEP_ELAPSED`. |
| **Escenarios de Spec** | Un único escenario contradictorio con el motor. | Dos escenarios claros: 1) Reprogramación con paso en el futuro (recalcula y sigue `scheduled`), y 2) Reprogramación con paso vencido (cancela con `STEP_ELAPSED`). |

---

## 5. Defecto Mayor: Verificabilidad en el Reporte de Costos y Entregas

### 5.1 Cómo se detectó
- **Componente**: `specs/reminders/delivery-report/spec.md`.
- **Regla / Fuente**: Principio fundamental de SDD: *"Ningún THEN puede tener aserciones ambiguas o alternativas"* (criterio de verificabilidad).
- **Problema detectado**: El escenario decía:
  > *"THEN la fila t_24h / whatsapp muestra enviados 2, entregados 1 o 0 según el estado del último mensaje, y fallidos 0"*.
  
  Un test automatizado no puede asertar `1 o 0`. El resultado de una prueba debe ser puramente determinista.

### 5.2 Comparativa Antes y Después

| ANTES | DESPUÉS |
|---|---|
| Un único escenario con resultado condicional (`1 o 0`). | **Dos escenarios independientes y deterministas**:<br>1. *Reenvío manual entregado*: aserta enviados 2, entregados 1, leídos 0, fallidos 0.<br>2. *Reenvío manual pendiente de entrega*: aserta enviados 2, entregados 0, leídos 0, fallidos 0. |

---

## 6. Límites identificados en el uso de IA y MCP

1. **La IA tiende a generar código especulativo o contratos ilusorios**: En la primera iteración, el agente propuso contratos que "sonaban coherentes" en prosa pero que fallaban matemáticamente al cruzarse con el historial inmutable de la base de datos o con las constraints de PostgreSQL.
2. **El MCP aporta documentación técnica, pero no reglas de negocio**: Context7 resolvió perfectamente cómo opera `SELECT ... FOR UPDATE` en PostgreSQL y los webhooks en Meta, pero no puede inferir si un turno `pending` sin WhatsApp debe o no alertar en la agenda de la clínica; esa decisión pertenece exclusivamente al dominio del proyecto (`knowledge-base/`).
3. **El valor del rigor de la skill propia**: Solo un procedimiento de auditoría metódico (la skill `auditoria-escenarios-turnos`), parametrizado con las 13 reglas duras del proyecto, fue capaz de detectar estas fallas antes de escribir una sola línea de código en backend o frontend.
