# Entrega — Trabajo Práctico: Integrar una Skill Propia y un MCP

> **Materia**: Metodología I — Tecnicatura Universitaria en Programación  
> **Proyecto**: Sistema de Turnos Odontológico  
> **Fecha de entrega**: 2026-11-07  

---

## 1. Datos del equipo y repositorio

- **Integrantes**:
  - [Nombre y Apellido 1 - Completar]
  - [Nombre y Apellido 2 - Completar si aplica]
  - [Nombre y Apellido 3 - Completar si aplica]
- **Repositorio**: `[URL del repositorio GitHub - Completar]`
- **Rama**: `main`
- **Commit de entrega**: `[Hash del commit final - Completar tras commit]`
- **Enlace al video de demostración (≤ 5 min)**: `[Enlace público YouTube / Drive - Completar]`

---

## 2. Documentos entregables principales

Todos los documentos requeridos por la consigna se encuentran redactados y versionados en el repositorio:

1. **Ficha de investigación (≤ 2 páginas)**:
   - 👉 [`docs/skills-mcp/investigacion.md`](docs/skills-mcp/investigacion.md)
   - Contiene la necesidad detectada, change elegido, investigación de la skill creadora, diseño de la skill propia, tabla comparativa de MCPs (Context7 vs. PostgreSQL MCP), elección justificada, pasos de instalación, archivos de fundación afectados y fuentes oficiales consultadas.
2. **Informe de aplicación (≤ 2 páginas)**:
   - 👉 [`docs/skills-mcp/aplicacion.md`](docs/skills-mcp/aplicacion.md)
   - Contiene los resultados obtenidos con la skill y el MCP, enlaces a las evidencias, lista de archivos modificados con su justificación, resumen del análisis crítico (antes y después) y limitaciones.
3. **Carpeta de evidencias**:
   - `docs/skills-mcp/evidencias/`
   - [`01-mcp-conexion.md`](docs/skills-mcp/evidencias/01-mcp-conexion.md): Comprobación de disponibilidad, consultas a Context7 sobre WhatsApp Cloud API / PostgreSQL 15 / SQLAlchemy 2.0 y aportes al diseño.
   - [`02-auditoria-informe.md`](docs/skills-mcp/evidencias/02-auditoria-informe.md): Informe formal generado por la skill propia sobre las 6 delta-specs de C-11 (30 hallazgos: 3 BLOQUEANTES, 13 MAYORES, 14 MENORES).
   - [`03-skill-uso.md`](docs/skills-mcp/evidencias/03-skill-uso.md): Registro de invocación de la skill, prompt exacto y trazabilidad.
   - [`05-revision-critica.md`](docs/skills-mcp/evidencias/05-revision-critica.md): Análisis crítico en profundidad con tablas comparativas «Antes y Después» de los defectos bloqueantes y de verificabilidad detectados.
4. **Change preparado bajo SDD**:
   - `openspec/changes/c-11-timeline-recordatorios/`
   - Contiene `proposal.md`, `design.md`, 6 delta-specs en `specs/` (con escenarios de funcionamiento, error de negocio y borde) y `tasks.md` estructurado bajo TDD estricto.
   - Estado reflejado en `CHANGES.md`: `[ ] preparado (2026-11-07)` (sin marcar `[x]`, conforme a la consigna).

---

## 3. Guion del Video de Demostración (Estructura de 5 minutos)

| Bloque | Tiempo | Contenido a exponer |
|---|---|---|
| **1. Introducción** | 0:00 – 0:40 | Explicación de la necesidad en el sistema odontológico tras cerrar C-10: visibilidad operativa de recordatorios para recepción (US-032). Justificación de por qué se requiere una skill de auditoría y un MCP de documentación técnica para preparar C-11. |
| **2. Skill Propia** | 0:40 – 1:40 | Mostrar la skill creadora utilizada (`skill-creator`), la estructura generada en `.agents/skills/auditoria-escenarios-turnos/`, su registro en `.atl/skill-registry.md` y las instrucciones en `AGENTS.md` / `CLAUDE.md`. |
| **3. Auditoría en Vivo** | 1:40 – 2:40 | Mostrar la invocación de la skill sobre C-11, el informe resultante (`02-auditoria-informe.md`) y cómo detectó los 3 defectos bloqueantes (frontera de generación en timeline, orden de guardas en reenvío concurrente, y reprogramación). |
| **4. Conexión del MCP** | 2:40 – 3:40 | Mostrar `opencode.json`, `README.md` y la guía `mcp-context7.md`. Ejecutar o mostrar la consulta a Context7 sobre webhooks de Meta y bloqueos `FOR UPDATE` en PostgreSQL. |
| **5. Artefactos y Aporte**| 3:40 – 4:30 | Recorrer los artefactos corregidos de `c-11-timeline-recordatorios` (`proposal`, `design`, `specs`, `tasks`), mostrando escenarios verificables (Given-When-Then) y el estado en `CHANGES.md`. |
| **6. Cierre Crítico** | 4:30 – 5:00 | Resumen del análisis crítico (Antes vs. Después), límites identificados en el uso de IA y MCP, y próximos pasos para la implementación de C-11. |

---

## 4. Instrucciones para Reproducir la Configuración

Cualquier integrante o evaluador puede comprobar la disponibilidad de ambas incorporaciones siguiendo estos pasos:

### Comprobación de la Skill Propia
1. Clonar el repositorio.
2. Verificar que `.agents/skills/auditoria-escenarios-turnos/SKILL.md` está presente y que `.atl/skill-registry.md` la referencia.
3. En una sesión nueva del agente, solicitar:  
   *"Auditá los escenarios del change C-11"*.  
   El agente localizará la skill por su trigger e instrucciones en `AGENTS.md` y ejecutará la auditoría.

### Comprobación del Servidor MCP Context7
1. Contar con OpenCode 1.x / cliente MCP compatible con soporte para servidores remotos.
2. El archivo `opencode.json` en la raíz ya declara el servidor `https://mcp.context7.com/mcp`.
3. Iniciar el cliente. En la lista de herramientas aparecerán `resolve-library-id` y `query-docs`.
4. Ejecutar una consulta de prueba:
   ```json
   {
     "libraryId": "/websites/postgresql",
     "query": "partial indexes"
   }
   ```
   El servidor responderá con los fragmentos de la documentación oficial de PostgreSQL 15.

---

## 5. Checklist de Verificación contra los Criterios de Evaluación

- [x] **Investigación fundamentada**: Ficha `docs/skills-mcp/investigacion.md` (≤ 2 páginas) con fuentes oficiales contrastadas, comparación de 2 MCPs y elección justificada.
- [x] **Skill propia**: Desarrollada con skill creadora, adaptada al dominio odontológico, versionada en el repo y con evidencia de uso real.
- [x] **MCP operativo**: Conexión remota reproducible en `opencode.json`, documentada en `README.md` y `mcp-context7.md`, con ejecución comprobada de herramientas.
- [x] **Integración a la fundación**: Ubicaciones, registros (`.atl/skill-registry.md`), referencias e instrucciones coherentes e idénticas en `AGENTS.md` y `CLAUDE.md`.
- [x] **Aplicación y revisión crítica**: Aporte concreto a C-11, escenarios de funcionamiento, error y borde, y análisis exhaustivo «Antes y Después» documentado en `05-revision-critica.md`.
- [x] **Seguridad y datos sintéticos**: Ningún dato real de pacientes, ningún secreto en el repositorio (`.env` ignorado, API keys vía variables de entorno).
- [x] **Roadmap respetado**: C-11 marcado como `[ ] preparado` en `CHANGES.md`, sin marcarlo como implementado ni archivado.
