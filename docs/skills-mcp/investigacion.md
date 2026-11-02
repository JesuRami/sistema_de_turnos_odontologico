# Ficha de Investigación: Integración de Skills y MCP

## 1. Necesidad Detectada y Change Elegido
En el desarrollo del sistema odontológico se identificó la necesidad de automatizar la verificación de consistencia en las reglas de agenda e historia clínica (detección de sobreturnos, huecos operativos y validación de entidades).
- **Change Seleccionado:** `C-03: Gestión de Agenda y Reglas de Disponibilidad` (referenciado en `CHANGES.md`).

## 2. Investigación de Skill Creadora y Skill Propia
- **Skill Creadora:** `system:skill-creator` (compatible con OpenCode / Claude Agent harness).
- **Skill Propia Creada:** `agenda-schedule-validator`.
- **Propósito:** Validar automáticamente que los rangos horarios de atención de profesionales no entren en conflicto con turnos existentes y respeten los límites físicos de los sillones odontológicos.
- **Ubicación:** `.agents/skills/agenda-schedule-validator/SKILL.md` (o `.opencode/skills/agenda-schedule-validator/SKILL.md`).

## 3. Comparación y Selección de Servidor MCP
| Criterio | Postgres MCP Server | Fetch / Web Search MCP Server |
| :--- | :--- | :--- |
| **Propósito** | Inspeccionar bases de datos PostgreSQL en tiempo real. | Consultar documentación externa del stack. |
| **Capacidades** | Ejecutar consultas de lectura sobre tablas, esquemas e índices. | Realizar peticiones HTTP GET y parsear contenido web. |
| **Elección** | **Seleccionado:** Postgres MCP Server. | Descartado para este cambio. |

**Justificación:** Permite al agente verificar directamente sobre PostgreSQL la integridad de las tablas `schedules`, `appointments` y `chairs` durante el flujo Spec-Driven Development.

## 4. Fuentes
- Model Context Protocol Specs: https://modelcontextprotocol.io (Consultado: 2026-11-02)
- OpenSpec Repository Architecture: https://github.com/openspec (Consultado: 2026-11-02)