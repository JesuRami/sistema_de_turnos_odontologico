# Plan de ejecución — TP «Skill propia + MCP»

> Documento interno de planificación. **No es un entregable del TP**: los entregables
> exigidos son `docs/skills-mcp/investigacion.md`, `docs/skills-mcp/aplicacion.md`,
> las evidencias, el video y el `.zip` final.
>
> Fuente: `mcp-skills.pdf` (Metodología I, 5 páginas).
> Punto de partida: repo `sistema_de_turnos_odontologico`, con C-01…C-10 y C-13
> implementados y archivados. **C-10 se archivó el 2026-11-06**, por lo que el TP se
> replanifica sobre el siguiente change pendiente.

---

## 1. Objetivo y alcance

Incorporar al proyecto **una skill propia** y **un servidor MCP existente**, integrarlos
a la fundación (KB, roadmap, registro de skills, instrucciones del agente) y demostrar su
utilidad preparando **un único change pendiente** con SDD.

### Dentro del alcance

- Investigar y comparar **dos** servidores MCP; elegir y conectar uno.
- Investigar una **skill creadora**, instalarla/comprobarla y usarla para crear una skill propia.
- Guardar, registrar y documentar la skill propia; actualizar `AGENTS.md`/`CLAUDE.md`.
- Dejar **preparado** (no implementado, no verificado, no archivado) el change C-12.
- Producir ficha, informe, evidencias, video y `.zip`.

### Fuera del alcance

- Implementar o archivar C-12.
- Desarrollar un servidor MCP propio.
- Contratar servicios pagos o usar credenciales reales de Meta/WhatsApp.
- Modificar C-10 o los changes ya cerrados.
- Regenerar toda la fundación o marcar etapas no ejecutadas.

### Restricciones que condicionan el plan

| Restricción | Efecto en el plan |
|---|---|
| Datos ficticios, sin PII ni secretos | Fixtures sintéticas; ninguna llamada real a Meta; `.env` fuera del repo |
| Reproducibilidad | Config del MCP versionada y documentada; instrucciones de instalación de la skill creadora |
| SDD obligatorio | `proposal.md` + `design.md` + `specs/**` + `tasks.md`; no implementar |
| 3 escenarios mínimos | 1 funcionamiento + 1 error de negocio + 1 borde, verificables |
| Commits solo si se piden | El plan propone commits por fase, pero no se ejecutan sin pedido explícito |
| Sin co-autoría de IA | Mensajes `tipo(ámbito): descripción` |

---

## 2. Diagnóstico del punto de partida

### Changes disponibles al 2026-11-07

| Change | Dependencias | ¿Preparable hoy? | Comentario |
|---|---|---|---|
| C-10 `whatsapp-webhook` | C-08 ✅ + C-09 ✅ | **Ya archivado** | Implementado y archivado el 2026-11-06; no sirve como change pendiente del TP |
| **C-12 `lista-de-espera`** | C-05 ✅ + C-08 ✅ + C-10 ✅ | **Sí** | Todas sus dependencias están archivadas; es el change con más reglas y casos borde |
| C-11 `timeline-recordatorios` | C-09 ✅ + C-10 ✅ | **Sí** | También preparable; más orientado a UI y operación de recordatorios |
| C-14 `hardening-piloto` | C-06 ✅ + C-11 ❌ + C-12 ❌ + C-13 ✅ | No | Faltan C-11 y C-12 |
| C-15…C-19 | C-14 ❌ | No | Fase posterior al piloto |

**Decisión adoptada: C-11 `timeline-recordatorios`.**
Se seleccionó C-11 para dar continuidad inmediata al canal WhatsApp y al motor de recordatorios
archivados en C-09 y C-10 (2026-11-06). Concentra la operación diaria de recepción (US-032, Flujo 4),
el reenvío manual con cooldown y tope, el timeline de estados asíncronos y la alerta de fallos en agenda.
C-12 queda como siguiente hito del roadmap.

### Base técnica que C-12 ya tiene

- `clinic.waitlist_offer_ttl_hours` ya existe (default 4 h) y se expone en la API de
  políticas; C-04 dejó el contrato.
- `appointment`, `appointment_event`, `patient`, `professional` y `chair` ya existen con
  `clinic_id` obligatorio, FKs compuestas y auditoría append-only.
- `AppointmentOrigin` **solo tiene `reception` y `online`**: C-12 debe agregar `waitlist`
  mediante una migración Alembic. Es un punto de diseño real: en PostgreSQL
  `ALTER TYPE … ADD VALUE` no puede usarse en la misma transacción que inserta el valor.
- No existen las tablas `waiting_list_entry` ni `waitlist_offer`; el modelo está descrito
  en `knowledge-base/04_modelo_de_datos.md` §waiting_list_entry + waitlist_offer.
- C-05/C-06/C-13 dejaron diferidos a C-12: evaluar la lista al cancelar, reasignar jobs
  del duplicado fusionado y el reporte de conversión lista de espera → turno.
- C-10 ya dejó el canal WhatsApp/email y el outbox de respuestas, que C-12 reutiliza para
  enviar la oferta con expiración visible.

**Consecuencia:** C-12 no arranca de cero, pero sí exige decisiones de concurrencia,
índices parciales y migración de enum que un MCP de documentación puede fundamentar.

---

## 3. Decisiones propuestas (a confirmar antes de ejecutar)

### 3.1 Change: C-12 `lista-de-espera`

- Governance: **MEDIO**.
- Alcance: lista de espera extremo a extremo (paciente + recepción + motor automático),
  migración `c12_waiting_list`, panel de cola, ofertas por WhatsApp/email, aceptación y
  reporte de conversión.
- Se deja **preparado** en `openspec/changes/c-12-lista-de-espera/`.
- En `CHANGES.md` se actualiza la referencia y el estado a “preparado”, **nunca `[x]`**.

### 3.2 MCP: Context7

**Comparación principal propuesta: Context7 vs. Postgres MCP.**

| Criterio | Context7 (Upstash) | Postgres MCP (`crystaldba/postgres-mcp`) |
|---|---|---|
| Propósito | Documentación oficial de librerías, motores y APIs | Inspección y consulta de una base Postgres |
| Capacidades | `resolve-library-id`, `query-docs` con fragmentos | Listar esquemas, describir tablas, ejecutar SQL (modo seguro) |
| Aporte a C-12 | `FOR UPDATE SKIP LOCKED`, índices parciales con NULL, `ALTER TYPE … ADD VALUE`, `with_for_update(skip_locked=True)` | Verificar tablas/índices reales y el estado de `appointment`/`clinic` |
| Conexión | Remota, `https://mcp.context7.com/mcp` | Local, proceso + DSN de Postgres |
| Credenciales | Ninguna obligatoria; API key opcional para más límites | `DATABASE_URL` con usuario/clave; riesgo de secreto |
| Permisos | Solo lectura de documentación pública | Puede leer/escribir según configuración; exige modo read-only |
| Costo | Gratuito; tier pago opcional | Gratuito (open source); costo de infraestructura |
| Disponibilidad actual | **Sí** (herramientas conectadas) | **No**: Docker Desktop no está corriendo |
| Fit con C-12 | **Alto**: las decisiones críticas son de concurrencia y migración | Medio: el esquema ya es legible en código y migraciones |

**Elección propuesta: Context7.**
C-12 se juega en decisiones que tienen documentación oficial muy concreta: cómo reclamar
ofertas sin duplicados (`FOR UPDATE SKIP LOCKED`), cómo imponer una sola entrada activa
cuando `professional_id` es NULL (índices parciales), y cómo agregar un valor de enum sin
romper la transacción. Context7 ya indexa PostgreSQL 15 (23.053 fragmentos) y SQLAlchemy
2.0 (14.858 fragmentos), no requiere credenciales ni Docker y es reproducible en cualquier
máquina. Postgres MCP queda documentado como alternativa descartada por ahora: aporta
verificación del esquema, pero suma DSN, permisos y una dependencia de infraestructura que
hoy no está disponible.

> Si se prefiere comparar dos MCP ya conectados: Context7 vs. Playwright MCP. Playwright
> sirve para inspeccionar la UI de recepción, pero C-12 se puede preparar y justificar sin
> levantar el stack completo; por eso se propone Postgres MCP como comparación más
> significativa para un change de datos y concurrencia.

### 3.3 Skill propia: `espec-scenarios-audit`

- Ubicación: `.agents/skills/espec-scenarios-audit/SKILL.md` (project-local, versionada).
- Creada con la skill creadora `skill-creator` (ya instalada globalmente).
- Propósito: auditar los escenarios de un change OpenSpec contra las reglas de negocio
  de la KB, clasificarlos y detectar huecos, ambigüedades y criterios no verificables.
- Se usa dos veces sobre C-12: sobre el borrador de specs y antes de cerrar `tasks.md`.

---

## 4. Entregables y trazabilidad

| Exigencia del TP | Archivo / evidencia | Fase |
|---|---|---|
| Ficha de investigación (≤2 páginas) | `docs/skills-mcp/investigacion.md` | 1 |
| Skill propia | `.agents/skills/espec-scenarios-audit/SKILL.md` + `references/` | 2 |
| Registro de la skill | `.atl/skill-registry.md` | 2 |
| Instrucciones del agente | `AGENTS.md` + `CLAUDE.md` (idénticos) | 2 y 3 |
| Configuración reproducible del MCP | `opencode.json` + `README.md` + `docs/skills-mcp/mcp-context7.md` | 3 |
| Change preparado | `openspec/changes/c-12-lista-de-espera/` | 4 |
| Roadmap actualizado | `CHANGES.md` (C-12 como preparado) | 4 |
| Evidencia de uso de la skill | `docs/skills-mcp/evidencias/03-skill-uso.md` | 5 |
| Evidencia de uso del MCP | `docs/skills-mcp/evidencias/04-mcp-uso.md` | 5 |
| Revisión crítica (antes/después) | `docs/skills-mcp/evidencias/05-revision-critica.md` | 5 |
| Informe de aplicación (≤2 páginas) | `docs/skills-mcp/aplicacion.md` | 6 |
| Video (≤5 min) | enlace en `ENTREGA.md` | 6 |
| Entrega única | `TP-Skills-MCP-Apellido1-Apellido2-Apellido3.zip` + `ENTREGA.md` | 6 |

---

## 5. Fases de ejecución

### Fase 0 — Confirmaciones y línea base (0,5 sesión)

- [ ] Confirmar C-12, Context7 y el nombre de la skill.
- [ ] Verificar que C-05, C-08 y C-10 están archivados y que C-12 sigue `[ ]` en `CHANGES.md`.
- [ ] Crear `docs/skills-mcp/evidencias/`.
- [ ] Registrar la fecha de inicio y el commit base (`git rev-parse HEAD`).
- [ ] Guardar la decisión en engram (`mem_save`).

**Criterio de salida:** las tres decisiones están aprobadas y la línea base queda registrada.

---

### Fase 1 — Investigación y ficha (1–2 sesiones)

#### 1.1 Skill creadora

- [ ] Confirmar el origen de `skill-creator` instalado globalmente:
  - Repositorio y licencia (hoy: Apache 2.0, `~/.config/opencode/skills/skill-creator/`).
  - Compatibilidad con OpenCode/Agent Skills (`SKILL.md` + frontmatter).
  - Comando reproducible de instalación (verificar `npx skills add …`).
- [ ] Comprobar disponibilidad: listar la skill, leer su `SKILL.md`, invocarla en seco.
- [ ] Comparar con una alternativa (p. ej. `writing-skills` de `obra/superpowers`)
  y justificar la elección.
- [ ] Registrar fuente, URL y fecha de consulta (2026-11-07 o la fecha real de ejecución).

#### 1.2 Diseño de la skill propia

Definir por escrito, antes de generarla:

| Campo | Contenido propuesto |
|---|---|
| Nombre | `espec-scenarios-audit` |
| Propósito | Auditar escenarios de un change OpenSpec contra la KB y el formato verificable |
| Cuándo se activa | Al preparar/revisar `specs/**/spec.md`; antes de `/opsx:apply`; pedidos de “casos borde” o “reglas ambiguas” |
| Entradas | Change (`proposal.md`, `design.md`, `specs/**`, `tasks.md`) + KB 04/05/06/07/10 |
| Procedimiento | Inventariar → clasificar → mapear a RN/US → verificar observabilidad → detectar huecos → revisar tasks → emitir hallazgos |
| Salida | Tabla de hallazgos por severidad + parches propuestos (no aplica cambios) |
| Criterios de revisión | 100 % de requisitos con escenario de funcionamiento; ≥1 error de negocio y ≥1 borde en requisitos críticos; 0 THEN no verificables; 0 RN huérfanas; 0 decisiones nuevas sin justificar |
| Límites | No inventa reglas; si falta KB marca `(TBD)` y pregunta; no edita specs |

#### 1.3 Comparación de MCP

- [ ] Completar la tabla de §3.2 con datos verificables de la documentación oficial.
- [ ] Verificar que Context7 indexa PostgreSQL 15 y SQLAlchemy 2.0 (hecho: consulta
  `resolve-library-id` del 2026-11-07: `/websites/postgresql` y `/sqlalchemy/sqlalchemy`).
- [ ] Documentar instalación/conexión, permisos, credenciales, costos y límites.
- [ ] Registrar lo no verificable como pendiente (no inventar).

#### 1.4 Ficha

- [ ] Escribir `docs/skills-mcp/investigacion.md` con las 8 secciones pedidas:
  necesidad, change elegido, skill creadora y diseño, comparación de MCP, elección
  justificada, pasos de instalación/configuración, archivos de fundación a actualizar,
  fuentes con URL y fecha.
- [ ] Extensión objetivo: **900–1.100 palabras** (≤2 páginas).
- [ ] Adjuntar como evidencia la salida de `resolve-library-id` y la comprobación de la
  skill creadora.

**Criterio de salida:** ficha revisada, sin afirmaciones sin fuente, con pendientes explícitos.

---

### Fase 2 — Crear e integrar la skill (2 sesiones)

#### 2.1 Crear

- [ ] Cargar `skill-creator` y usarla para generar el borrador de
  `espec-scenarios-audit`.
- [ ] Adaptar el borrador al dominio:
  - Catálogo RN-AG/SB/ST/CX/ON/WA/LE/GL de `knowledge-base/05_reglas_de_negocio.md`.
  - Formato OpenSpec `#### Scenario:` + `WHEN`/`THEN`.
  - Regla de los tres tipos: funcionamiento, error de negocio, borde.
  - Prohibición de decisiones de dominio sin justificación.
  - Salida con severidad y referencia `archivo:línea` + `RN-*`.
- [ ] Agregar `references/scenario-checklist.md` con el checklist y ejemplos del dominio
  (incluyendo FIFO, expiración, doble aceptación y unicidad con NULL).
- [ ] Probar la skill contra un change ya archivado (C-09 o C-10) para calibrar falsos
  positivos.
- [ ] Ajustar la descripción (trigger) para que se active con frases reales del equipo.

#### 2.2 Integrar

- [ ] Registrar en `.atl/skill-registry.md`: trigger, nombre, ruta y compact rules.
- [ ] Actualizar `AGENTS.md` y `CLAUDE.md`:
  - Fila en “Skills Disponibles” (rol: calidad de specs / orquestación).
  - Cuándo usarla, qué necesita y cómo revisar el resultado.
  - Mantener ambos archivos idénticos (`diff AGENTS.md CLAUDE.md`).
- [ ] Actualizar los documentos de fundación afectados. Si la KB no cambia, dejarlo
  escrito y justificado en `aplicacion.md`.
- [ ] Si la skill creadora queda global, incluir en `docs/skills-mcp/` una referencia
  versionada con fuente, licencia y comando de instalación reproducible.

#### 2.3 Descubrimiento en sesión nueva

- [ ] Abrir una sesión nueva (o un subagente sin contexto) y pedir: “auditá los
  escenarios del change C-12”.
- [ ] Confirmar que encuentra la skill por el registro/instrucciones y la usa.
- [ ] Guardar transcripción o captura en `evidencias/03-skill-descubrimiento.md`.

**Criterio de salida:** la skill existe, está registrada, las instrucciones la referencian
y una sesión nueva la encuentra sin ayuda manual.

---

### Fase 3 — Configurar e integrar el MCP (1–2 sesiones)

#### 3.1 Configuración

- [ ] Crear configuración project-scoped (`opencode.json` en la raíz) con Context7:
  - `type: remote`
  - `url: https://mcp.context7.com/mcp`
  - `enabled: true`
  - API key **opcional** por variable de entorno, nunca hardcodeada.
- [ ] Verificar la sintaxis exacta de variables/headers en la documentación de OpenCode.
- [ ] Confirmar que no se commitea ningún secreto ni `.env`.

#### 3.2 Comprobación de conexión

- [ ] Reiniciar el cliente y listar las herramientas del MCP.
- [ ] Ejecutar una herramienta real: `resolve-library-id` para PostgreSQL 15 y
  `query-docs` sobre `FOR UPDATE SKIP LOCKED` o índices parciales.
- [ ] Guardar la solicitud, el resultado y una captura en `evidencias/04-mcp-conexion.md`.

#### 3.3 Documentación

- [ ] Crear `docs/skills-mcp/mcp-context7.md` con:
  - Requisitos y pasos de configuración.
  - Variables de entorno (sin valores).
  - Comprobación de conexión y ejecución de una herramienta.
  - Un problema de instalación real y su solución (p. ej. herramientas que no aparecen
    hasta reiniciar el cliente, o límite de peticiones sin API key).
  - Configuración de ejemplo sin secretos.
  - Límites de acceso: solo documentación pública, solo lectura, sin PII ni datos del repo.
- [ ] Crear `README.md` en la raíz (hoy no existe) con descripción breve del proyecto y
  enlace a `docs/skills-mcp/mcp-context7.md`.
- [ ] Actualizar `AGENTS.md`/`CLAUDE.md` con el propósito del MCP, capacidades, momento
  de uso y límites. **No registrarlo como skill.**
- [ ] Verificar que `AGENTS.md` y `CLAUDE.md` siguen idénticos.

**Criterio de salida:** otra persona puede reproducir la conexión siguiendo el README y
ejecutar una herramienta real; el MCP queda documentado como integración, no como skill.

---

### Fase 4 — Preparar C-12 (2–3 sesiones)

#### 4.1 Exploración y artefactos

- [ ] Ejecutar `/opsx:explore` si hace falta para mapear C-12 contra C-05/C-08/C-10.
- [ ] Ejecutar `/opsx:propose c-12-lista-de-espera` (o generar los artefactos con el
  mismo formato del repo).
- [ ] Completar:
  - `proposal.md`: why, what changes, capabilities, impact, fuera de alcance, open decisions.
  - `design.md`: modelo de datos, migración `c12_waiting_list`, agregado de `waitlist` al
    enum, índices parciales para la unicidad con `professional_id` NULL, reclamo de
    ofertas con `FOR UPDATE SKIP LOCKED`, evaluación al cancelar, expiración y rotación,
    aceptación y creación del turno, reporte de conversión, RBAC, configuración.
  - `specs/**/spec.md`: requisitos y escenarios.
  - `tasks.md`: tareas ordenadas con verificación por escenario.
- [ ] Aplicar la skill `espec-scenarios-audit` sobre el borrador y corregir los hallazgos
  bloqueantes/mayores.
- [ ] Usar Context7 para contrastar:
  - `FOR UPDATE SKIP LOCKED` y su uso para reclamar ofertas sin duplicados.
  - Índices parciales y el problema de unicidad cuando `professional_id` es NULL.
  - `ALTER TYPE … ADD VALUE` y su restricción transaccional.
  - `with_for_update(skip_locked=True)` y `Index(..., postgresql_where=...)` en SQLAlchemy 2.0.
- [ ] Revisar cada regla contra `knowledge-base/04`, `05`, `06`, `07` y `10`; justificar
  toda decisión nueva.

#### 4.2 Escenarios mínimos

La spec debe contener al menos:

| Tipo | Ejemplo propuesto |
|---|---|
| Funcionamiento | Se cancela un turno → la primera entrada compatible por FIFO (con tolerancia de preferencia) recibe una oferta con `expires_at`; aceptar crea el turno con origen `waitlist`, cancela las demás ofertas pendientes y audita todo |
| Error de negocio | Un paciente intenta anotarse dos veces para el mismo profesional mientras su entrada está `waiting` → `409` con referencia a la entrada existente; o aceptar una oferta vencida → `409/422`, la oferta queda `expired` y la entrada vuelve a `waiting` |
| Borde | Dos ofertas de la misma entrada se aceptan a la vez → una sola crea el turno, la otra vuelve a la cola con prioridad; o tres vencimientos consecutivos → la entrada queda `expired`; o el hueco liberado cae fuera del rango preferido → se salta al siguiente compatible; o `professional_id = NULL` (“cualquiera”) no duplica la entrada |

- [ ] Verificar que cada `THEN` sea observable (código HTTP, estado en DB, evento, fila).
- [ ] Verificar que `tasks.md` indique cómo se probará cada escenario.
- [ ] No implementar nada.

#### 4.3 Roadmap

- [ ] Actualizar `CHANGES.md`:
  - Estado de C-12: “preparado (fecha) → `openspec/changes/c-12-lista-de-espera/`”.
  - Nota de dependencias satisfechas y de que **no** está implementado.
  - Mantener `[ ]` (no marcar `[x]`).
- [ ] No tocar los changes ya archivados.

**Criterio de salida:** el change está completo y revisado, con ≥3 escenarios verificables,
y el roadmap lo refleja como preparado.

---

### Fase 5 — Evidencias y revisión crítica (1 sesión)

#### 5.1 Evidencia de la skill

- [ ] `evidencias/03-skill-uso.md`: prompt exacto, salida, hallazgos y qué aportó a C-12.
- [ ] Mostrar al menos un hallazgo real (no una lista de herramientas instaladas).

#### 5.2 Evidencia del MCP

- [ ] `evidencias/04-mcp-uso.md`: consulta, resultado y decisión del change que cambió
  gracias a esa consulta.
- [ ] Guardar el fragmento relevante, no todo el volcado.

#### 5.3 Revisión crítica (obligatoria)

Elegir **un defecto real** de la ejecución inicial. Candidatos:

1. La spec inicial implementa FIFO puro y omite la tolerancia de preferencia de RN-LE-02 →
   se corrige el escenario y la consulta de compatibilidad.
2. La unicidad de entrada activa se resuelve con un `UNIQUE (patient_id, professional_id)`
   que no bloquea duplicados cuando `professional_id` es NULL → se corrige con dos índices
   parciales (o `COALESCE`), fundamentado en PostgreSQL.
3. La aceptación de una oferta vencida crea el turno igual → se corrige con validación de
   `expires_at` y rotación al siguiente.
4. La carrera de doble aceptación no está cubierta → se agrega escenario y bloqueo.
5. Agregar `waitlist` al enum dentro de la misma transacción que inserta el turno → falla
   en PostgreSQL; se corrige la estrategia de migración.
6. Un `THEN` vago (“el sistema responde bien”) → se reescribe con código/estado observable.

- [ ] Documentar en `evidencias/05-revision-critica.md`: cómo se detectó, qué fuente o
  regla permitió corregirlo, y el **antes/después**.
- [ ] Si no aparece un defecto, probar un caso de borde y documentar el límite sin inventar.

**Criterio de salida:** hay evidencia verificable de uso y una corrección real con antes/después.

---

### Fase 6 — Informe, video y entrega (1–2 sesiones)

#### 6.1 Informe

- [ ] `docs/skills-mcp/aplicacion.md` (900–1.100 palabras, ≤2 páginas):
  - Resultados de la skill y del MCP.
  - Enlaces a evidencias.
  - Lista de archivos modificados y motivo de cada uno.
  - Revisión crítica (resumen del antes/después).
  - Limitaciones (cobertura de Context7, sin DB levantada, change solo preparado, etc.).

#### 6.2 Video (≤5 min)

Guion propuesto:

| Minuto | Contenido |
|---|---|
| 0:00–0:40 | Necesidad y change elegido (C-12), por qué skill + MCP |
| 0:40–1:40 | Skill creadora y skill propia: creación, ubicación, registro |
| 1:40–2:40 | Uso real de la skill sobre C-12 y hallazgo corregido |
| 2:40–3:40 | Configuración del MCP, conexión y consulta real |
| 3:40–4:30 | Artefactos de C-12 y aporte concreto de ambas incorporaciones |
| 4:30–5:00 | Revisión crítica, límites y próximo paso |

- [ ] Grabar sin secretos, sin PII y sin datos reales.
- [ ] Si hay varios integrantes, cada uno explica su contribución.

#### 6.3 Entrega

- [ ] Crear `ENTREGA.md` con: integrantes, URL del repo, commit de entrega y enlace al video.
- [ ] Incluir la ficha y el informe dentro del `.zip`.
- [ ] Nombre: `TP-Skills-MCP-Apellido1-Apellido2-Apellido3.zip`.
- [ ] Verificar que el repo contiene todos los artefactos y las instrucciones de reproducción.
- [ ] Verificar que no hay `.env`, tokens, claves ni datos reales en el repo ni en el `.zip`.

**Criterio de salida:** entrega única completa y reproducible por otro integrante.

---

## 6. Orden de commits propuesto

> Solo se ejecutan si el usuario lo pide. Sin `Co-Authored-By` ni firmas de asistente.

| # | Momento | Mensaje propuesto |
|---|---|---|
| 1 | Ficha terminada | `docs(skills-mcp): agrega ficha de investigación de skill y MCP` |
| 2 | Skill creada | `feat(skills): agrega espec-scenarios-audit` |
| 3 | Registro e instrucciones | `docs(foundation): registra la skill y actualiza instrucciones del agente` |
| 4 | MCP configurado y documentado | `docs(mcp): integra Context7 y documenta su reproducción` |
| 5 | Change preparado | `docs(openspec): prepara c-12-lista-de-espera` |
| 6 | Evidencias e informe | `docs(skills-mcp): agrega evidencias, revisión crítica e informe` |
| 7 | Entrega | `chore(release): agrega ENTREGA.md para el TP` |

---

## 7. Cronograma estimado

| Sesión | Foco | Salida |
|---|---|---|
| S0 | Confirmaciones y línea base | Decisiones aprobadas |
| S1 | Investigación de skill creadora y MCP | Notas y fuentes |
| S2 | Ficha + diseño de la skill | `investigacion.md` |
| S3 | Creación de la skill | Borrador probado |
| S4 | Integración y prueba en sesión nueva | Registro + instrucciones + evidencia |
| S5 | Configuración del MCP y documentación | `opencode.json` + README + evidencia |
| S6 | Exploración y proposal de C-12 | `proposal.md` |
| S7 | Design + specs | `design.md` + `specs/**` |
| S8 | Auditoría con la skill + correcciones + tasks | `tasks.md` + hallazgos |
| S9 | Evidencias + revisión crítica + informe | `aplicacion.md` |
| S10 | Video + `.zip` + verificación final | Entrega |

Total estimado: **10 sesiones de 60–90 minutos** (≈ 12–15 horas), sin contar la
implementación de C-12, que queda para una instancia posterior.

---

## 8. Riesgos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Context7 no cubre algún detalle de PostgreSQL/SQLAlchemy | Media | Medio | Contrastar con la doc oficial; registrar el pendiente |
| Docker/DB no disponible | Alta | Bajo | Context7 es remoto; C-12 se prepara sin DB |
| La unicidad con `professional_id` NULL se resuelve mal | Media | Alto | Dos índices parciales; verificarlo en el design y en la spec |
| `ALTER TYPE … ADD VALUE` en la misma transacción | Media | Alto | Migración separada / bloque autocommit; documentarlo |
| La skill generada es demasiado genérica | Media | Medio | Probarla contra C-09/C-10 y C-12; agregar checklist y ejemplos |
| Falsos positivos de la skill | Media | Bajo | Calibrar con un change archivado; registrar el ajuste |
| Se confunde “preparado” con “implementado” | Baja | Alto | No marcar `[x]`; no ejecutar `/opsx:apply`; nota explícita |
| Filtración de secretos/PII | Baja | Alto | Solo fixtures sintéticas; revisar el `.zip` antes de entregar |
| Límite de 2 páginas excedido | Media | Bajo | Objetivo 900–1.100 palabras; revisar antes de cerrar |
| Video excede 5 minutos | Media | Bajo | Guion con tiempos y ensayo |

---

## 9. Checklist final contra los criterios de evaluación

- [ ] **Investigación fundamentada:** fuentes verificables, comparación de 2 MCP y elección
  ajustada al proyecto.
- [ ] **Skill propia:** procedimiento claro, adaptación al dominio y evidencia de uso.
- [ ] **MCP operativo:** conexión reproducible y ejecución útil de una herramienta.
- [ ] **Integración a la fundación:** ubicación, registro, referencias e instrucciones
  actualizados y coherentes (`AGENTS.md` = `CLAUDE.md`).
- [ ] **Aplicación y revisión:** aporte concreto a C-12, ≥3 escenarios verificables,
  control del resultado y revisión crítica con antes/después.
- [ ] **Datos y credenciales:** solo datos ficticios; sin claves, tokens ni `.env`.
- [ ] **Reproducibilidad:** otra persona puede instalar la skill y conectar el MCP.
- [ ] **Entrega:** ficha, informe, evidencias, video y `.zip` con `ENTREGA.md`.

---

## 10. Preguntas abiertas para el usuario

1. ¿Se confirma **C-12 `lista-de-espera`** como change pendiente, o se prefiere C-11
   `timeline-recordatorios`?
2. ¿Se confirma **Context7** como MCP (comparado con Postgres MCP)?
3. ¿Se acepta el nombre **`espec-scenarios-audit`** para la skill propia?
4. ¿El TP es individual o de hasta tres integrantes? (define el video y la distribución
   de commits)
5. ¿Se dispone de un repositorio remoto y de un lugar para alojar el video?
