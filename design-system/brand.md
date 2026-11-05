# Brand — Turnos Odontológicos

Estado: **provisional**. Todo lo marcado `(TBD)` requiere decisión del usuario.

## Nombre

- **Nombre del producto:** `(TBD)`.
- **Nombre mostrado en previews:** `Clínica Demo (TBD)` (valor en `brand.js`).
- **Nombre real en la app:** cada clínica muestra su propio `clinic.name`; el producto no
  impone marca a los pacientes.
- **Fuente:** no hay nombre de producto en `knowledge-base/` ni en el código.

## Logo

- **Archivo estable:** `assets/logo.svg`.
- **Estado:** placeholder rotulado (`LOGO PROVISIONAL / TBD`). No debe presentarse como logo
  aprobado.
- **Uso:** esquina superior izquierda en vistas de personal; en la vista pública solo si hay
  marca blanca acordada.
- **Área de resguardo:** media altura del isotipo a cada lado.

## Tono

- **Registro:** profesional, claro, sin jerga clínica innecesaria.
- **Voz al paciente:** segunda persona, frases cortas, sin culpa ("No pudimos reservar ese
  horario", no "Usted se equivocó").
- **Voz al personal:** operativa y directa ("Marcar presente", "Reprogramar").
- **Fuente:** `knowledge-base/06_funcionalidades.md` (historias de usuario) y el copy ya
  presente en `frontend/src/features/booking/`.

## Color

- **Base:** verde dental (`#0e7c7b`) sobre fondo hueso (`#f7f5ef`).
- **Uso semántico:** verde = acción primaria y confirmación; rosa/rojo = destructivo o error;
  ámbar = advertencia; azul = información.
- **Restricción:** el verde no se usa para comunicar estado "exitoso" y "primario" en el mismo
  componente sin jerarquía (el estado usa el badge, no el color del botón).
- **Fuente:** `frontend/tailwind.config.js`.

## Tipografía

- **Familia:** Inter con fallback `system-ui`. No se sirve desde el proyecto.
- **Uso:** una sola familia; jerarquía por peso y tamaño, no por familia.
- **Números:** tabulares en agenda y horarios (`font-variant-numeric: tabular-nums`).

## Imágenes

- **Fotografía:** `(TBD)`; v1 no usa imágenes de stock ni fotos de personas.
- **Ilustración:** `(TBD)`.
- **Regla dura 13:** nunca usar imágenes de pacientes reales, ni siquiera en mockups.

## Movimiento

- **Principio:** el movimiento confirma una acción, no decora.
- **Duración:** 150 ms para cambios de estado; 200 ms para entrada de diálogos.
- **Reducción:** `prefers-reduced-motion: reduce` desactiva transiciones.
