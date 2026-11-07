# Evidencia — Conexión y Uso del Servidor MCP Context7

> **Change**: C-11 `timeline-recordatorios`  
> **Servidor MCP**: Context7 (`https://mcp.context7.com/mcp`)  
> **Tipo de integración**: Remota (HTTP/SSE)  
> **Fecha de ejecución**: 2026-11-07  

---

## 1. Comprobación de disponibilidad y herramientas expuestas

La configuración del servidor reside en el archivo versionado `opencode.json` de la raíz del monorepo:
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

Al iniciar la sesión, el cliente OpenCode detecta y registra las herramientas provistas por Context7:
- `tools.context7["resolve-library-id"]`: Localiza identificadores canónicos de librerías y documentación oficial.
- `tools.context7["query-docs"]`: Recupera fragmentos específicos y vigentes de la documentación indexada.

---

## 2. Invocación 1: Consulta sobre Meta WhatsApp Cloud API (Webhooks y Estados)

### Solicitud (Prompt / Tool Call)
```json
{
  "tool": "resolve-library-id",
  "arguments": {
    "query": "whatsapp business platform cloud api webhooks"
  }
}
```
**Resultado obtenido**:
- Library ID resuelta: `/websites/whatsapp-business-platform`

### Consulta documental de contratos
```json
{
  "tool": "query-docs",
  "arguments": {
    "libraryId": "/websites/whatsapp-business-platform",
    "query": "webhook message status delivered read failed ordering retry delivery receipt"
  }
}
```
**Fragmento clave recuperado**:
> *"Webhooks for message status updates (`sent`, `delivered`, `read`, `failed`) may arrive out of chronological sequence due to distributed delivery tiers. For instance, a `read` receipt can be received prior to a delayed `delivered` receipt. Furthermore, Meta will retry failed deliveries with exponential backoff for up to 30 days. When processing status receipts, applications must ensure idempotency using `wamid` / message ID and derive message progression from state precedence rather than arrival order."*

### Aporte concreto a C-11
- **Decisión de diseño D2 (`design.md`)**: Se fundamentó la regla de que el backend no debe depender de un orden secuencial rígido en la llegada de eventos. Si Meta envía `read` sin un `delivered` previo, o envía `delivered` y `failed` en el mismo mensaje, el modelo de lectura de C-11 calcula el estado efectivo por precedencia (`read > delivered > failed > scheduled`), garantizando coherencia en la UI de recepción.

---

## 3. Invocación 2: Consulta sobre PostgreSQL 15 y SQLAlchemy 2.0 (Concurrencia e Índices Parciales)

### Solicitud (Prompt / Tool Call)
```json
{
  "tool": "resolve-library-id",
  "arguments": {
    "query": "postgresql"
  }
}
```
**Resultado obtenido**:
- Library ID resuelta: `/websites/postgresql` (PostgreSQL 15, 23.053 fragmentos indexados)

### Consulta documental sobre concurrencia y bloqueos
```json
{
  "tool": "query-docs",
  "arguments": {
    "libraryId": "/websites/postgresql",
    "query": "SELECT FOR UPDATE row-level locks read committed concurrent update transaction"
  }
}
```
**Fragmento clave recuperado**:
> *"In Read Committed isolation level, a `SELECT ... FOR UPDATE` command acquires exclusive row-level locks on matching rows. If a concurrent transaction is concurrently updating the same row, the second transaction blocks until the first commits or rolls back, and then re-evaluates the query condition against the newly committed version of the row."*

### Consulta documental sobre índices parciales en PostgreSQL
```json
{
  "tool": "query-docs",
  "arguments": {
    "libraryId": "/websites/postgresql",
    "query": "CREATE INDEX partial index predicate WHERE status = failed performance"
  }
}
```
**Fragmento clave recuperado**:
> *"A partial index is built over a subset of a table defined by a conditional expression (the `WHERE` clause). This reduces index size and maintenance overhead when the indexed condition matches a small percentage of rows, such as filtering for erroneous or pending states."*

### Aporte concreto a C-11
1. **Prevención de carreras en reenvío manual (D4 y D6 en `design.md`)**:
   Se estructuró el endpoint `POST /api/appointments/{id}/reminders/{step}/{channel}/resend` con un bloqueo `SELECT ... FOR UPDATE` sobre la fila del `reminder_job`. Cuando dos recepcionistas hacen clic simultáneamente en "Reenviar", la primera transacción serializa la fila, inserta la auditoría en `reminder_manual_resend` y resetea el job. La segunda transacción se desbloquea tras el commit, re-evalúa la condición y detecta inmediatamente que el cooldown de 60 segundos está activo, respondiendo `409 resend_cooldown` en lugar de duplicar el mensaje.
2. **Índice parcial para la alerta de fallos (migración `c11_reminder_timeline`)**:
   Para alimentar el panel de seguimiento diario (`follow-up`) sin degradar la tabla operativa, se diseñó un índice parcial:
   ```sql
   CREATE INDEX CONCURRENTLY ix_reminder_job_clinic_failed
   ON reminder_job (clinic_id, appointment_id)
   WHERE status = 'failed';
   ```
   permitiendo búsquedas casi instantáneas de los turnos que requieren atención telefónica.

---

## 4. Conclusión de la integración del MCP

Context7 MCP permitió validar contratos técnicos de proveedores externos y patrones de concurrencia avanzados directamente desde documentación oficial, eliminando supuestos erróneos antes de plasmar las especificaciones y tareas de C-11.
