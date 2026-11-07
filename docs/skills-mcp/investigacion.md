# Ficha de Investigación — TP «Skill propia + MCP»

> **Materia**: Metodología I — Tecnicatura Universitaria en Programación  
> **Proyecto**: Sistema de Turnos Odontológico  
> **Fecha de elaboración**: 2026-11-07  
> **Estado**: Completada  

---

## 1. Necesidad real detectada en el proyecto

El proyecto cuenta con la fundación completada y los changes C-01 al C-10 y C-13 archivados. Tras cerrar C-10 (canal oficial WhatsApp Cloud API y webhook de respuestas), el backend dispone del motor de recordatorios (`reminder_job`) y de eventos inmutables de entrega (`delivery_event`). Sin embargo, recepción carece de visibilidad operativa: no cuenta con un timeline para saber si un mensaje salió, se entregó, se leyó o falló, ni con herramientas para reenviar manualmente o gestionar turnos no respondidos (US-032, Flujo 4).

Esta necesidad introduce dos problemas técnicos de alta fricción:
1. **Reglas de negocio complejas y casos de borde en la especificación**: El flujo de reenvío manual y cálculo de estado efectivo combina asincronismo de proveedores externos (Meta Cloud API), locks de concurrencia (`FOR UPDATE`), cooldowns, topes diarios por huso horario de la clínica, auditoría append-only y recálculo con `reconcile`. Cualquier omisión en las specs genera contratos insatisfacibles o colisiones en producción.
2. **Dependencia de contratos externos y APIs oficiales**: El diseño del timeline y del reenvío exige contrastar la semántica exacta de los webhooks de Meta (reintentos, idempotencia, estados fuera de orden como `read` sin `delivered`) y patrones de base de datos en PostgreSQL 15 / SQLAlchemy 2.0 (índices parciales, transacciones concurrentes y queries de agregación sobre eventos inmutables).

---

## 2. Change elegido: C-11 `timeline-recordatorios`

Se seleccionó **C-11 `timeline-recordatorios`** (Governance: MEDIO), cuyas dependencias (C-09 y C-10) están archivadas.
- **Por qué C-11**: Es el paso natural del roadmap para cerrar la brecha operativa de recordatorios antes del endurecimiento y salida a piloto (C-14). Permite preparar el change completo bajo Spec-Driven Development (SDD) sin requerir tablas o funcionalidades de fases posteriores.
- **Aporte conjunto**: La **skill propia** audita los escenarios de las 6 delta-specs de C-11 para asegurar que no existan contratos ambiguos ni criterios no verificables; el **servidor MCP** aporta la consulta a la documentación técnica de Meta y PostgreSQL para fundamentar las decisiones de diseño.

---

## 3. Skill creadora y diseño de la skill propia

### 3.1 Skill creadora investigada
Se investigó la skill creadora oficial **`skill-creator`** (ecosistema Agent Skills / Anthropic, licencia Apache 2.0).
- **Compatibilidad**: 100 % compatible con el estándar Agent Skills / OpenCode (`SKILL.md` con frontmatter YAML `name` y `description`).
- **Instalación y comprobación**: Disponible globalmente en el entorno (`~/.config/opencode/skills/skill-creator/`). Se comprobó su disponibilidad generando un andamiaje con estructura estricta (`SKILL.md`, `references/`, `evals/`).
- **Alternativa analizada**: Se evaluó `writing-skills` del paquete Superpowers (`obra/superpowers`). Se descartó porque se enfoca en redacción general de prompts y no en la arquitectura modular de directivas, checklists de dominio y evaluación sintética requerida.

### 3.2 Diseño de la skill propia: `auditoria-escenarios-turnos`
- **Ubicación**: `.agents/skills/auditoria-escenarios-turnos/SKILL.md` (project-local, versionada en el repo).
- **Propósito**: Auditar exhaustivamente los escenarios de un change OpenSpec contra las 13 reglas duras del proyecto, la base de conocimiento (`knowledge-base/04..07, 10, 11`) y el formato verificable Given-When-Then.
- **Cuándo se activa (Trigger)**: Al preparar o revisar `proposal.md`, `design.md`, `specs/**/spec.md` o `tasks.md`; ante solicitudes como *"auditar escenarios"*, *"casos borde"*, *"reglas ambiguas"* o *"validar specs"*; y antes de `/opsx:apply`.
- **Entradas**: Change en preparación (`proposal`, `design`, `specs`, `tasks`), KB aplicable, código existente y `AGENTS.md`.
- **Procedimiento**:
  1. *Inventario y clasificación*: clasificar cada escenario en funcionamiento esperado, error de negocio o caso de borde.
  2. *Mapeo contra KB*: verificar trazabilidad hacia reglas RN-*, historias US-* y flujos. Detectar reglas huérfanas o decisiones no fundamentadas.
  3. *Verificabilidad de THEN*: rechazar criterios vagos ("funciona bien", "es consistente"); exigir estados HTTP, códigos de error, transiciones o filas inmutables observables.
  4. *Auditoría de ejes críticos*: concurrencia, idempotencia, aislamiento multitenant (`clinic_id`), RBAC, auditoría append-only sin PII y husos horarios.
  5. *Alineación con Tasks*: comprobar que cada escenario posea una task TDD (RED/GREEN) verificable con Postgres real y datos sintéticos.
- **Resultado esperado**: Tabla formal de hallazgos por severidad (`BLOQUEANTE`, `MAYOR`, `MENOR`) con `archivo:línea`, regla infringida y parche propuesto; matriz de cobertura; preguntas abiertas. La skill **no edita** artefactos ni inventa reglas de negocio.
- **Criterios de revisión**: 100 % de requisitos con escenario de funcionamiento; al menos un error de negocio y un borde en requisitos críticos; cero `THEN` no observables; cero reglas huérfanas.

---

## 4. Comparación y selección de servidores MCP

| Criterio | Context7 MCP (Upstash) | PostgreSQL MCP (`crystaldba/postgres-mcp`) |
|---|---|---|
| **Propósito** | Consulta de documentación oficial y actualizada de librerías, APIs y motores. | Inspección, introspección de esquemas y ejecución de queries sobre PostgreSQL. |
| **Capacidades** | `resolve-library-id`, `query-docs` con recuperación de fragmentos contextuales. | `list_tables`, `describe_table`, `execute_query` (DDL/DML seguro en modo solo lectura). |
| **Compatibilidad** | Alta. Compatible con clientes OpenCode y Claude Desktop vía HTTP/SSE remoto. | Media/Alta. Servidor local vía `stdio` o contenedor Docker. |
| **Conexión / Infra** | Remota (`https://mcp.context7.com/mcp`). No requiere procesos locales ni Docker activo. | Local. Exige que el motor PostgreSQL de desarrollo esté levantado y accesible. |
| **Credenciales y Seguridad** | Gratuito sin credenciales obligatorias. API key opcional en env var. Sin acceso a datos del repo. | Requiere cadena `DATABASE_URL` con usuario y clave; riesgo de exposición de credenciales. |
| **Aporte a C-11** | **Crítico**: Documenta la idempotencia del webhook de Meta, estados, índices parciales y transacciones concurrentes en SQLAlchemy 2.0. | Medio: Permite verificar las tablas `reminder_job` y `delivery_event`, cuyo esquema ya está en Alembic y modelos. |

### 4.1 Elección justificada
Se seleccionó **Context7 MCP**. La preparación de un change bajo SDD demanda precisión en contratos de integración y en la API del proveedor antes de escribir código. Context7 indexa documentación pública oficial (PostgreSQL 15, SQLAlchemy 2.0 y Meta WhatsApp Cloud API), no requiere dependencias locales activas (garantizando reproducibilidad en cualquier máquina o CI) y asegura un entorno sin credenciales en el repositorio.

---

## 5. Pasos de instalación y configuración

### 5.1 Skill propia
1. Ubicar `SKILL.md` y sus referencias en `.agents/skills/auditoria-escenarios-turnos/`.
2. Registrar la entrada y compact rules en `.atl/skill-registry.md`.
3. Incorporar la directiva en `AGENTS.md` y sincronizarla en `CLAUDE.md`.

### 5.2 Context7 MCP
1. Declarar el servidor remoto en el archivo de configuración versionado `opencode.json` en la raíz del monorepo:
   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "mcp": {
       "context7": {
         "type": "remote",
         "url": "https://mcp.context7.com/mcp",
         "enabled": true
       }
     }
   }
   ```
2. Si se requiere cuota ampliada, definir `CONTEXT7_API_KEY` en el entorno (sin escribirla en archivos del repo).
3. Comprobar la disponibilidad invocando `resolve-library-id` y `query-docs`.
4. Documentar los pasos de reproducción en `README.md` y `docs/skills-mcp/mcp-context7.md`.

---

## 6. Archivos de la fundación a actualizar

| Archivo | Motivo de la actualización |
|---|---|
| `AGENTS.md` y `CLAUDE.md` | Alta de la skill en skills disponibles, contrato de uso del MCP Context7 y límites de seguridad (mantener ambos archivos idénticos). |
| `.atl/skill-registry.md` | Registro formal de `auditoria-escenarios-turnos`, ruta local, trigger y compact rules para subagentes. |
| `CHANGES.md` | Actualización de C-11 a estado `[ ] preparado (2026-11-07)`, referenciando los artefactos SDD y notas de preparación. |
| `README.md` | Inclusión de la sección de infraestructura de desarrollo y enlace a la guía de reproducción de Context7. |

---

## 7. Fuentes consultadas y contraste oficial

1. **Meta WhatsApp Business Platform — Cloud API Reference**  
   URL: `https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components` (Consulta: 2026-11-07). Verificación de estados de entrega (`sent`, `delivered`, `read`, `failed`), errores del webhook y ventana de mensajes.
2. **PostgreSQL 15 Documentation — Partial Indexes & Concurrency**  
   URL: `https://www.postgresql.org/docs/15/indexes-partial.html` (Consulta: 2026-11-07). Índices parciales para jobs fallidos y cláusulas `FOR UPDATE` bajo aislamiento Read Committed.
3. **SQLAlchemy 2.0 Unified Tutorial — Locking & Core Execution**  
   URL: `https://docs.sqlalchemy.org/en/20/core/selectable.html` (Consulta: 2026-11-07). Contrastado para `with_for_update()` y manejo de sesiones asíncronas.
4. **Agent Skills Specification — Standard SKILL.md Architecture**  
   URL: `https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo` (Consulta: 2026-11-07). Estructura de frontmatter, directivas y evaluación sintética de skills.
