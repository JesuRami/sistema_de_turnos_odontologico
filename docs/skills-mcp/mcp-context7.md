# MCP Context7 — integración del proyecto

Este documento explica cómo está conectado **Context7** al proyecto
`sistema_de_turnos_odontologico`, cómo comprobar la conexión y cómo reproducirlo en
otra máquina. Context7 es un **servidor MCP de documentación**: no es una skill y no
se registra en `.atl/skill-registry.md`.

## 1. Qué aporta y para qué se usa

Context7 expone documentación oficial y actualizada de librerías y APIs. En este
proyecto se usa para contrastar contratos externos antes de escribir specs o código:

- WhatsApp Cloud API de Meta: verificación del webhook, firma `X-Hub-Signature-256`,
  payload de estados (`sent`/`delivered`/`read`/`failed`) y ventana de 24 h.
- FastAPI / Starlette: dependencias, routers y manejo de requests.
- PostgreSQL / SQLAlchemy: constraints, índices y patrones de consulta.

**Cuándo usarlo**: al preparar o revisar un change que dependa de una API externa, al
dudar de una firma o de un estado del proveedor, y antes de fijar un contrato en una
spec. **Cuándo no**: para decisiones de negocio del dominio odontológico; esas salen de
`knowledge-base/`, no de la documentación de una librería.

### Herramientas que se usan

| Herramienta | Para qué |
|---|---|
| `resolve-library-id` | Encontrar el ID de la librería (por ejemplo WhatsApp Business Platform). |
| `query-docs` | Traer fragmentos de documentación sobre un tema concreto. |

En este entorno las herramientas se invocan desde Code Mode como
`tools.context7["resolve-library-id"]` y `tools.context7["query-docs"]`.

## 2. Requisitos

- OpenCode instalado y funcionando (este repo se verificó con OpenCode 1.18.x, formato
  de configuración V1).
- Acceso a Internet a `https://mcp.context7.com/mcp`.
- **Ninguna credencial obligatoria.** Context7 permite un uso gratuito sin API key. Si
  se necesita más cuota, se puede configurar `CONTEXT7_API_KEY` como variable de
  entorno y enviarla por header; nunca se escribe el valor en el repo.

## 3. Configuración

### 3.1 Configuración versionada del proyecto

El archivo [`opencode.json`](../../opencode.json) de la raíz declara el servidor:

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

Esta es la forma del cliente instalado (OpenCode 1.x). Si se migra a OpenCode V2, el
mismo servidor se declara dentro de `mcp.servers` y se usa `disabled` en lugar de
`enabled`; no cambian la URL ni las herramientas.

### 3.2 Configuración global (alternativa)

Si se prefiere que Context7 esté disponible en todos los proyectos, la configuración
global vive en:

```
%USERPROFILE%\.config\opencode\opencode.json
```

con la misma entrada. La configuración del proyecto tiene precedencia sobre la global.
No hace falta duplicar el servidor: si ya está global, el `opencode.json` del proyecto
lo reemplaza por nombre con los mismos campos.

### 3.3 API key opcional (sin secretos en el repo)

Solo si se necesita la cuota ampliada:

1. Crear la variable de entorno `CONTEXT7_API_KEY` en la máquina (no en el repo).
2. Agregar el header con sustitución de entorno:

```json
{
  "mcp": {
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "enabled": true,
      "headers": {
        "CONTEXT7_API_KEY": "{env:CONTEXT7_API_KEY}"
      }
    }
  }
}
```

El repositorio no contiene claves, tokens ni `.env`. `.env` está en `.gitignore`.

## 4. Comprobación de conexión

1. Abrir OpenCode en la raíz del repo y verificar que el servidor figure conectado
   (`/mcps` en la interfaz, o `opencode mcp list` si el CLI está en el PATH).
2. Confirmar que las herramientas `context7_resolve_library_id` y
   `context7_query_docs` aparecen disponibles.
3. Ejecutar una consulta real (ver §5). Una lista de herramientas instaladas no
   alcanza: hay que ejecutar al menos una y guardar la evidencia.

### Problema de instalación encontrado y solución

En este entorno el CLI `opencode` no estaba en el `PATH` de PowerShell, así que
`opencode mcp list` no se pudo ejecutar desde la terminal. La conexión se comprobó
igual por dos vías: el servidor ya estaba declarado en la configuración global
(`C:\Users\<usuario>\.config\opencode\opencode.json`) y las herramientas respondieron
correctamente a consultas reales desde la sesión. Para reproducirlo en otra máquina,
alcanza con el `opencode.json` del proyecto y abrir OpenCode en esa carpeta; si el CLI
está instalado, `opencode mcp list` es la comprobación más directa.

## 5. Evidencia de uso real

Consulta ejecutada el **2026-11-07**:

- `resolve-library-id` con `libraryName: "WhatsApp Business Platform"` devolvió el ID
  `/llmstxt/developers_facebook_business-messaging_whatsapp_llms_txt` (5.628
  fragmentos, reputación alta).
- `resolve-library-id` con `libraryName: "FastAPI"` devolvió
  `/websites/fastapi_tiangolo` (4.326 fragmentos).
- `query-docs` sobre el ID de WhatsApp se usó para contrastar el orden de los estados
  y el tratamiento de eventos fuera de orden en la timeline de C-11.

La transcripción y el resultado están en
[`evidencias/04-mcp-uso.md`](evidencias/04-mcp-uso.md). El aporte concreto al change
está resumido en [`aplicacion.md`](aplicacion.md).

## 6. Límites de acceso

- **Solo lectura de documentación pública.** No se envían datos del proyecto, del
  paciente ni del repositorio.
- No se consultan datos reales ni PII: las consultas se escriben con términos técnicos
  genéricos.
- No reemplaza la KB ni las reglas duras: si Context7 contradice `AGENTS.md` o la KB,
  prevalecen `AGENTS.md` y la KB.
- La cobertura depende del índice de Context7. Si un tema no aparece, se contrasta con
  la documentación oficial del proveedor y se registra el pendiente; no se inventa.
- El servidor es remoto: la disponibilidad y la latencia dependen de `mcp.context7.com`.

## 7. Referencias

- Context7: <https://github.com/upstash/context7> (consultado 2026-11-07).
- OpenCode MCP: <https://opencode.ai/docs/mcp-servers/> (consultado 2026-11-07).
- Context7 MCP endpoint: <https://mcp.context7.com/mcp>.
