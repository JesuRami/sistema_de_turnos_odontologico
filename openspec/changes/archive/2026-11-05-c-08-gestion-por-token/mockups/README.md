# Mockups — C-08 `gestion-por-token`

Pantallas y estados de la página pública de gestión del turno (`/g/:token`).

- **Design system:** `design-system/` — Revision 1, `Approval: approved (2026-11-05, by user)`
- **Approval:** approved (2026-11-05, by user)
- **Preview:** rendered (2026-11-05) — `previews/<pantalla>-390x844.png` y `previews/<pantalla>-1440x900.png`
- **Datos:** 100% sintéticos (regla dura 13). El teléfono, la dirección y los nombres son ficticios.

## Pantallas

| Archivo | Cuándo se ve | Estado representado |
|---|---|---|
| `01-pending.html` | Link válido, turno `pending` | Acciones: confirmar, reprogramar, cancelar + plazo de cancelación |
| `02-confirmed.html` | Después de confirmar (o al reabrir un turno ya confirmado) | `confirmed`, replay idempotente sin error |
| `03-cancel.html` | El paciente elige cancelar | Motivo opcional (lista cerrada + «Otro» con nota ≤200) y advertencia irreversible |
| `04-window-closed.html` | Cancelar/reprogramar fuera de la ventana de 24 h | Derivación a la clínica con teléfono (`409 cancellation_window_closed`) |
| `05-reschedule.html` | El paciente elige reprogramar | Días y horarios disponibles de la misma profesional |
| `06-expired.html` | Token vencido o inexistente | Pantalla de contacto (`410 manage_link_expired` / `404 manage_link_not_found`) |

## Estados no mockeados (decisión de alcance)

- **Cargando / error de red**: se resuelven con los componentes de `design-system/components.html` (`alert-info` + texto `Cargando…`), sin pantalla propia.
- **Turno ya iniciado o pasado** (`409 appointment_started` / `422 appointment_in_past`): reutiliza `04-window-closed.html` cambiando el copy a «Este turno ya pasó».
- **Colisión al reprogramar** (`409 slot_taken`): alerta `alert-error` sobre `05-reschedule.html` recargando los horarios.

## Cómo previsualizar

Abrir cualquier `.html` en un navegador. Dependen de `../../../../design-system/tokens.css` y
`../../../../design-system/brand.js`; no requieren build ni servidor.

## Cómo se relacionan con el design system

- Importan `tokens.css`; no hay hex ni tamaños hardcodeados en los mockups.
- `mockup.css` define solo clases de presentación reutilizando variables.
- El nombre visible usa `data-brand-name` (valor en `brand.js`), así que el `(TBD)` de marca se
  reemplaza en un solo lugar.
