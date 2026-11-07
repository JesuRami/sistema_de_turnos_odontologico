# Informe de Aplicación — TP «Skill propia + MCP»

> **Materia**: Metodología I — Tecnicatura Universitaria en Programación  
> **Proyecto**: Sistema de Turnos Odontológico  
> **Change preparado**: C-11 `timeline-recordatorios`  
> **Fecha**: 2026-11-07  
> **Estado**: Entregable final  

---

## 1. Introducción y alcance del trabajo

Este informe documenta la integración de una **skill propia** (`auditoria-escenarios-turnos`) y un **servidor MCP** (Context7) en la fundación del sistema odontológico, demostrando su utilidad concreta en la preparación del change pendiente **C-11 `timeline-recordatorios`** bajo Spec-Driven Development (SDD).

Conforme a las directivas de la cátedra, el alcance se concentró en la investigación, integración a la fundación, preparación exhaustiva de especificaciones y control crítico de calidad, dejando la implementación y el archivado del change para una fase posterior.

---

## 2. Resultados obtenidos

### 2.1 Servidor MCP: Context7
Se integró **Context7 MCP** como servidor remoto mediante configuración reproducible en `opencode.json` y documentación en `docs/skills-mcp/mcp-context7.md`.
- **Herramientas utilizadas**: `resolve-library-id` y `query-docs`.
- **Resultados técnicos**: Se consultó la documentación oficial de la WhatsApp Cloud API de Meta y de PostgreSQL 15 / SQLAlchemy 2.0. Esto permitió fundamentar:
  1. El cálculo del estado efectivo del timeline ante webhooks de entrega asíncronos y fuera de orden.
  2. La serialización de peticiones concurrentes de reenvío mediante bloqueos `SELECT ... FOR UPDATE` a nivel de fila.
  3. El diseño de índices parciales para la alerta de jobs fallidos sin penalizar la performance operativa de la tabla.
- **Evidencia enlazada**: 👉 [`docs/skills-mcp/evidencias/01-mcp-conexion.md`](evidencias/01-mcp-conexion.md).

### 2.2 Skill propia: `auditoria-escenarios-turnos`
Se desarrolló y versionó la skill en `.agents/skills/auditoria-escenarios-turnos/`, registrándola formalmente en `.atl/skill-registry.md`, `AGENTS.md` y `CLAUDE.md`.
- **Procedimiento ejecutado**: La skill auditó 27 requisitos y 73 escenarios de las 6 delta-specs de C-11.
- **Resultados de la auditoría**: Detectó **3 defectos BLOQUEANTES**, **13 MAYORES** y **14 MENORES**.
- **Aporte determinante**: Descubrió inconsistencias lógicas graves en el flujo de reenvío manual que habrían impedido pasar los tests de integración o causado bloqueos en producción.
- **Evidencias enlazadas**:
  - Informe completo de auditoría: 👉 [`docs/skills-mcp/evidencias/02-auditoria-informe.md`](evidencias/02-auditoria-informe.md).
  - Trazabilidad y registro de invocación: 👉 [`docs/skills-mcp/evidencias/03-skill-uso.md`](evidencias/03-skill-uso.md).

### 2.3 Preparación de C-11 `timeline-recordatorios`
Se completaron y corrigieron todos los artefactos de C-11 en `openspec/changes/c-11-timeline-recordatorios/`:
- `proposal.md`: Justificación operativa, impacto en monorepo y capacidades añadidas/modificadas.
- `design.md`: Arquitectura de timeline, modelo de eventos inmutables, orden de guardas y migración `c11_reminder_timeline`.
- `specs/`: 6 delta-specs con escenarios verificables Given-When-Then categorizados en funcionamiento, error de negocio y borde.
- `tasks.md`: Plan de tareas estructurado bajo TDD estricto (RED/GREEN) sobre PostgreSQL real y datos sintéticos.

---

## 3. Revisión crítica: análisis «Antes y Después»

El aporte más valioso de este trabajo fue el control de calidad cruzado entre la skill y el MCP, que permitió identificar y corregir defectos que el agente introdujo en su primer borrador:

1. **Frontera temporal de generación en el timeline (BLOQUEANTE)**:
   - *Antes*: La spec calculaba el estado vigente evaluando si había un evento `failed` posterior al último `sent`. Al reenviar un recordatorio que había fallado, el job pasaba a `scheduled`, pero la presencia del `failed` anterior hacía que la fórmula siguiera devolviendo `failed`, rompiendo el test unitario.
   - *Después*: Se incorporó la frontera de generación: el estado se deriva únicamente de los eventos posteriores a la última marca de reset (`reminder_manual_resend`). Los eventos previos quedan catalogados como "envío anterior".
2. **Orden de guardas en reenvíos concurrentes (BLOQUEANTE)**:
   - *Antes*: El diseño evaluaba el estado mutable del job (`scheduled` → `409 reminder_pending`) antes del cooldown. La segunda petición de un doble clic caía en `reminder_pending`, haciendo imposible responder `409 resend_cooldown`.
   - *After*: Se reordenaron las guardas evaluando cooldown y tope antes del estado del job, y tipificando `status = scheduled AND manual_resend_at IS NOT NULL` como reenvío en curso.
3. **Reprogramación tras reenvío (BLOQUEANTE)**:
   - *Antes*: La spec exigía cancelar incondicionalmente el job reenviado si el turno se reprogramaba, contradiciendo el motor de reconciliación (`scheduling.py`) que refresca los jobs futuros.
   - *Después*: Se alineó con la spec principal: si el nuevo horario mantiene el paso en el futuro, el job se recalcula; si el paso ya venció, se cancela con `STEP_ELAPSED`.
4. **Determinismo en el reporte de entregas (MAYOR)**:
   - *Antes*: Un escenario asertaba entregados "1 o 0", violando el principio de verificabilidad.
   - *Después*: Se desdobló en dos escenarios con cifras exactas e independientes.

- **Evidencia detallada de revisión crítica**: 👉 [`docs/skills-mcp/evidencias/05-revision-critica.md`](evidencias/05-revision-critica.md).

---

## 4. Archivos modificados en la fundación y justificación

| Archivo | Modificación realizada | Motivo |
|---|---|---|
| `.agents/skills/auditoria-escenarios-turnos/` | Creación de `SKILL.md`, `evals/` y `references/`. | Implementación y versionado de la skill propia en el proyecto. |
| `.atl/skill-registry.md` | Registro de la nueva skill con trigger y compact rules. | Disponibilidad y resolución en runtime para subagentes del monorepo. |
| `AGENTS.md` y `CLAUDE.md` | Actualización de tabla de skills, sección de MCP Context7 y directivas de uso. | Instrucciones de contexto para el agente principal (manteniendo ambos archivos idénticos). |
| `opencode.json` | Declaración del servidor remoto Context7. | Configuración versionada y reproducible del cliente MCP. |
| `README.md` | Adición de sección de desarrollo y enlace a la guía de Context7. | Punto de entrada para cualquier desarrollador que clone el repositorio. |
| `docs/skills-mcp/mcp-context7.md` | Guía de configuración, pruebas y resolución de problemas. | Documentación técnica detallada de la integración del MCP. |
| `CHANGES.md` | Actualización de `[C-11]` a estado `[ ] preparado (2026-11-07)`. | Trazabilidad del roadmap respetando la regla de no marcarlo como implementado. |
| `openspec/changes/c-11-timeline-recordatorios/` | Creación y corrección de `proposal`, `design`, 6 specs y `tasks`. | Preparación completa del change bajo SDD auditada por la skill propia. |

---

## 5. Limitaciones identificadas

1. **Dependencia de documentación pública**: Context7 resuelve contratos de librerías externas de forma excelente, pero no sustituye el modelado de negocio; las reglas clínicas y de agenda provienen exclusivamente de `knowledge-base/`.
2. **Entorno de desarrollo sin credenciales reales**: Por estrictas razones de seguridad y costos (Reglas 6 y 13), el change se diseñó utilizando fixtures sintéticas y emulación de webhooks, sin llamadas reales a la API paga de Meta.
3. **Validación sin base de datos en ejecución**: Dado que el alcance del TP es exclusivamente la preparación del change y no su implementación, los tests definidos en `tasks.md` quedaron formalizados para ejecutarse en la fase de código subsiguiente.

---

## 6. Conclusiones

La incorporación sinérgica de una **skill propia de auditoría** y un **servidor MCP de documentación** elevó drásticamente el estándar de calidad del proyecto. Se logró un cambio cualitativo: pasar de especificaciones preliminares con inconsistencias ocultas a un change maduro, determinista y blindado contra errores de concurrencia y de lógica de negocio.
