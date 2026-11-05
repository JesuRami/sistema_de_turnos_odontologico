# Design System — Turnos Odontológicos

Sistema visual portable del proyecto. Es la fuente de verdad para mockups, componentes y
tokens de UI. Se derivó de la interfaz ya implementada en C-06 (agenda del personal) y C-07
(reserva pública), no de una marca nueva.

- **Mode:** system-and-mockups
- **Revision:** 1
- **Approval:** approved (2026-11-05, by user)
- **Decided:** 2026-11-05, by user
- **Decided in:** `.active-orchestrator-state.json` → `visual_design.mode`

## Por qué existe

El proyecto ya tiene UI funcionando con una identidad de facto (verde dental + `enamel`,
tipografía del sistema, radios chicos). Este documento la fija para que los próximos changes
visuales —empezando por C-08 `gestion-por-token`— no inventen otra estética.

## Fuentes de la identidad

| Fuente | Qué aporta |
|---|---|
| `frontend/tailwind.config.js` | Paleta `dental` (50/100/200/600/700/900), `enamel`, familia `Inter` |
| `frontend/src/shared/ui/index.tsx` | Botones (primary/secondary/danger/ghost), campos, `Alert`, `Modal`, `PageTitle` |
| `frontend/src/features/booking/BookingFlow.tsx` | Layout público mobile-first (`max-w-md`, `bg-enamel`) |
| `frontend/src/features/agenda/AgendaGrid.tsx` | Densidad de agenda y estados de turno |
| `frontend/src/index.css` | Tailwind base (sin CSS propio) |

## Archivos

| Archivo | Rol |
|---|---|
| `design-system/tokens.css` | Variables CSS: color, tipografía, espaciado, radios, sombras, foco, movimiento |
| `design-system/brand.md` | Nombre, tono, logo e imágenes (con `(TBD)` donde no hay dato) |
| `design-system/brand.js` | Único punto de cambio del nombre mostrado en previews HTML |
| `design-system/assets/logo.svg` | Logo **provisional** (dice que lo es) |
| `design-system/components.html` | Catálogo de componentes y estados, importa tokens y assets locales |
| `design-system/previews/` | Capturas 390×844 y 1440×900 |

## Decisiones abiertas `(TBD)`

1. **Nombre del producto**: no está definido en la KB ni en el código. Hoy se muestra
   `Clínica Demo (TBD)`.
2. **Logo definitivo**: `assets/logo.svg` es un placeholder rotulado.
3. **Imágenes/fotografía**: sin brief; no se usan fotos en v1.
4. **Inter**: se declara en Tailwind pero no se sirve desde el proyecto. El stack cae a
   `system-ui`; si se quiere Inter real, hay que self-hostearla (no CDN, para no depender
   de terceros en runtime).

## Cómo reemplazar cada `(TBD)`

- **Nombre**: editar `BRAND.name` en `design-system/brand.js`. Todos los previews que usan
  `[data-brand-name]` se actualizan solos. En la app real, el nombre visible depende de la
  clínica (`clinic.name`), no de este archivo.
- **Logo**: reemplazar el contenido de `design-system/assets/logo.svg` conservando el
  `viewBox` y el nombre del archivo. Después: subir `Revision:` a 2, poner
  `Approval: pending`, re-renderizar previews y pedir revisión.
- **Tokens**: editar `design-system/tokens.css`. Cualquier cambio de valor compartido también
  exige bump de `Revision` y nueva aprobación.

## Cómo previsualizar

Abrir `design-system/components.html` en un navegador (o servirlo en localhost si el
navegador bloquea `file://`). El archivo es autocontenido: solo depende de `tokens.css`,
`brand.js` y `assets/logo.svg` del mismo directorio.

## Reglas de uso

- Los mockups de cada change importan `tokens.css` y `brand.js`; no copian valores hex.
- Prohibido introducir una paleta paralela o una tipografía nueva sin revisar este sistema.
- El foco visible es obligatorio: `--focus-ring` con contraste sobre `enamel` y blanco.
- Respetar `prefers-reduced-motion` (los tokens de movimiento se anulan).
- Los estados vacíos, de error y de carga se diseñan, no se improvisan.
