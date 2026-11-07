---
name: auditoria-escenarios-turnos
description: Audita los escenarios de un change OpenSpec del sistema de turnos odontológico contra la base de conocimiento y las reglas duras del proyecto. Clasifica cada escenario en funcionamiento, error de negocio o borde; detecta THEN no verificables, requisitos sin escenario, reglas RN-* huérfanas, decisiones de dominio sin justificar y tasks que no prueban lo que prometen. Usala siempre que se prepare o revise un proposal, design, spec o tasks de OpenSpec; cuando se pida "auditar escenarios", "buscar casos borde", "revisar reglas ambiguas", "validar specs", "faltan escenarios" o "revisar antes de aplicar"; y antes de /opsx:apply, aunque el pedido no nombre la skill.
---

# Auditoría de escenarios de turnos

## Para qué sirve

Un change de OpenSpec puede tener specs que parecen completas y, sin embargo, dejar
sin cubrir la carrera de dos recepcionistas, el turno que cruza un cambio de horario
o la respuesta de Meta que llega fuera de orden. Esta skill revisa los artefactos
**antes de implementar** y devuelve hallazgos accionables, no una opinión general.

La salida es una tabla de hallazgos con severidad y un parche propuesto. La skill
**no edita** specs, design ni tasks: audita para que el autor decida.

## Cuándo se activa

- Se está preparando o revisando un change (`proposal.md`, `design.md`, `specs/**`, `tasks.md`).
- Alguien pide auditar escenarios, buscar casos borde, revisar reglas ambiguas o validar specs.
- Antes de `/opsx:apply` o de archivar un change.
- Después de un cambio de alcance, una decisión nueva o un hallazgo de implementación.

## Entradas necesarias

1. El change completo, en `openspec/changes/<nombre>/`.
2. La KB relevante, como mínimo:
   - `knowledge-base/05_reglas_de_negocio.md` (RN-AG/SB/ST/BL/LE/CX/ON/WA/GL).
   - `knowledge-base/06_funcionalidades.md` (US y CA afectados).
   - `knowledge-base/07_flujos_principales.md` (flujo E2E que el change toca).
   - `knowledge-base/10_preguntas_abiertas.md` (decisiones que no se pueden inventar).
   - `knowledge-base/11_whatsapp_y_recordatorios.md` si el change toca recordatorios o WhatsApp.
3. Las reglas duras de `AGENTS.md`/`CLAUDE.md`.
4. Las specs principales de `openspec/specs/**` para las capabilities afectadas.
5. El código existente que el change reutiliza (modelos, servicios, endpoints), para no
   inventar contratos que ya existen.

Si falta una entrada, decilo y pedila. No completes reglas de dominio por suposición:
marcá `(TBD)` y formulá la pregunta.

## Procedimiento

### 1. Inventariar

Listá cada requisito de las delta specs y cada escenario con su tipo:

- **Funcionamiento**: el camino feliz observable.
- **Error de negocio**: una regla del dominio impide la operación (consentimiento, estado,
  ventana, rol, colisión).
- **Borde**: concurrencia, idempotencia, límites, datos faltantes, orden inesperado,
  zona horaria, reenvío, cross-tenant.

Registrá para cada requisito: `archivo:línea`, capability y RN/US/CA que lo respalda.

### 2. Mapear contra la KB

Para cada requisito, buscá la regla o el criterio de aceptación que lo justifica. Marcá:

- **RN huérfana**: la spec toca un tema regulado y no cita ni aplica la regla.
- **Decisión sin justificar**: agrega una regla nueva que no está en la KB ni fue aprobada.
- **Contradicción**: la spec dice algo distinto de la KB, de `AGENTS.md` o de una spec principal.

Cuando la KB no alcance, no inventes: `(TBD)` + pregunta concreta.

### 3. Verificar que cada THEN sea observable

Un `THEN` sirve si se puede comprobar sin interpretar. Aceptá:

- Código HTTP y código de error (`409 slot_taken`, `422 invalid_range`).
- Estado de una fila o de una máquina de estados.
- Existencia/ausencia de una fila, un evento o una llamada.
- Idempotencia demostrable (misma entrada dos veces → un solo efecto).
- Tiempo o zona horaria con un instante concreto.

Rechazá: "funciona bien", "responde correctamente", "no se duplica" sin decir qué se
cuenta, "queda consistente", "se muestra al usuario" sin estado observable.

### 4. Probar los ejes del dominio

Recorré el checklist de `references/checklist-escenarios.md`. Como mínimo:

- **Concurrencia**: dos requests simultáneos, doble tick, doble webhook, doble clic.
- **Idempotencia**: claves únicas y reenvíos.
- **Aislamiento**: `clinic_id` obligatorio y respuesta ante otro tenant.
- **RBAC**: admin, recepción, odontólogo (solo lo propio), paciente por token.
- **Auditoría**: evento en la misma transacción, append-only, sin PII.
- **Tiempo**: zona de la clínica, bordes de ventana, turno ya iniciado.
- **Estados**: transiciones permitidas y prohibidas; no retroceder.
- **Datos**: lectura desde eventos inmutables cuando la regla lo exige.

### 5. Revisar las tasks

Cada escenario debe tener al menos una task que explique **cómo se verificará**:
test que falla primero (RED), implementación mínima (GREEN), capa de test y datos
sintéticos. Si una task dice "implementar X" sin verificación, es un hallazgo.

Comprobá también que las tasks no implementen cambios de dominio que la KB no autoriza
y que respeten las reglas duras (migración, Postgres real, sin mocks de DB para
invariantes, sin secretos ni PII).

### 6. Emitir hallazgos

Usá exactamente esta tabla, ordenada por severidad:

```markdown
## Hallazgos

| # | Severidad | Requisito / escenario | Archivo:línea | Regla / fuente | Qué falta | Parche propuesto |
|---|-----------|-----------------------|---------------|----------------|-----------|------------------|
| 1 | BLOQUEANTE | ... | specs/x/spec.md:42 | RN-WA-04 | ... | ... |
```

Severidades:

- **BLOQUEANTE**: el change no se puede implementar sin decidir o corregir esto; hay
  contradicción con la KB o un `THEN` no verificable en un invariante.
- **MAYOR**: falta un escenario de error de negocio o borde en un requisito crítico;
  la task no verifica; decisión nueva sin justificar.
- **MENOR**: redacción, referencia faltante, duplicación, ejemplo poco claro.

Cerrá con:

```markdown
## Cobertura

| Requisito | Funcionamiento | Error de negocio | Borde | Verificable |
|-----------|----------------|------------------|-------|-------------|
| ... | sí/no | sí/no | sí/no | sí/no |

## Preguntas abiertas
- ...
```

### 7. Reauditar

Después de que el autor aplique los parches, repetí la auditoría sobre los archivos
modificados. No des por cerrado un hallazgo sin ver el cambio en el archivo.

## Criterios de revisión del resultado

La auditoría está bien hecha si:

- El 100 % de los requisitos tiene al menos un escenario de funcionamiento.
- Todo requisito crítico (invariantes, dinero, salud, seguridad) tiene al menos un
  error de negocio y un borde.
- Ningún `THEN` es no verificable.
- Ninguna RN aplicable queda huérfana y ninguna decisión nueva queda sin justificar.
- Cada escenario tiene una task que dice cómo probarlo.
- Los hallazgos citan `archivo:línea` y una fuente del proyecto, no una preferencia.

## Límites

- No inventes reglas de negocio ni completes la KB por inferencia.
- No edites los artefactos: proponé el parche y dejá la decisión al autor.
- No confundas "no está en la spec" con "está mal": primero buscá en la KB, en las
  specs principales y en el código existente.
- Si el change no tiene specs (solo proposal/design), auditá igual los requisitos
  declarados y marcá la falta de delta specs como BLOQUEANTE.
- No uses esta skill para implementar ni para archivar: solo audita.

## Referencias

- `references/checklist-escenarios.md`: checklist por eje del dominio, con ejemplos
  de este repo.
- `references/plantilla-informe.md`: formato completo del informe y ejemplo de hallazgo.
