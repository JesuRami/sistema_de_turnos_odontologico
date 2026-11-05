# Spec Delta — web/manage-token

## Purpose

Define la página pública `/g/:token` con la que el paciente ve su turno y lo
confirma, cancela o reprograma desde el celular, sin cuenta y sin guardar el
token en el navegador.

## ADDED Requirements

### Requirement: Página pública sin sesión ni almacenamiento del token

`/g/:token` SHALL funcionar sin sesión de personal y SHALL leer el token solo de
la URL, sin escribirlo en `localStorage`, `sessionStorage`, cookies ni en la
memoria de otra ruta. La página SHALL enviar `Referrer-Policy: no-referrer` y no
SHALL incluir el token en pedidos a otros orígenes.

#### Scenario: Visita anónima

- **WHEN** se abre `/g/<token>` sin sesión iniciada
- **THEN** la página muestra el turno y no redirige al login

#### Scenario: Sin almacenamiento del token

- **WHEN** se inspeccionan `localStorage` y `sessionStorage` después de cargar y usar la página
- **THEN** no contienen el token ni datos del turno

### Requirement: Resumen del turno con acciones según estado y ventana

La página SHALL mostrar fecha y hora en la zona de la clínica, el profesional, el
estado y el nombre de pila del paciente, y SHALL habilitar solo las acciones que
el servidor informa como posibles: confirmar si está pendiente, cancelar o
reprogramar si está vigente y dentro de la ventana.

#### Scenario: Turno pendiente con acciones

- **WHEN** el turno está `pending` y faltan 5 días
- **THEN** se ven los botones "Confirmar turno", "Cancelar" y "Cambiar horario"

#### Scenario: Turno fuera de la ventana

- **WHEN** el turno empieza en 3 h y la ventana es 24 h
- **THEN** "Cancelar" y "Cambiar horario" están deshabilitados y se muestra el teléfono de la clínica

#### Scenario: Turno ya cancelado

- **WHEN** el turno está `cancelled`
- **THEN** no se ofrece ninguna acción y se ofrece volver a reservar

### Requirement: Confirmación en un toque con feedback claro

El botón de confirmación SHALL enviar la acción sin pedir datos adicionales y
SHALL mostrar el estado confirmado, sin permitir un segundo envío mientras el
primero está en curso.

#### Scenario: Confirmar

- **WHEN** el paciente toca "Confirmar turno"
- **THEN** la página muestra el turno como confirmado y el botón deja de ofrecerse

#### Scenario: Doble toque

- **WHEN** el paciente toca dos veces seguidas "Confirmar turno"
- **THEN** se envía una sola acción y la página queda en estado confirmado

### Requirement: Cancelación con motivo opcional y derivación

La cancelación SHALL pedir el motivo de forma opcional con la lista cerrada del
servidor y un campo libre solo para "otro", SHALL confirmar la acción destructiva
antes de enviarla y SHALL derivar a la clínica cuando el servidor responde
`cancellation_window_closed`.

#### Scenario: Cancelar con motivo

- **WHEN** el paciente elige el motivo "viaje" y confirma la cancelación
- **THEN** la página muestra el turno cancelado y no ofrece más acciones

#### Scenario: Cancelar sin motivo

- **WHEN** el paciente cancela sin elegir motivo
- **THEN** la acción se envía igual y la página muestra el turno cancelado

#### Scenario: Fuera de la ventana

- **WHEN** el servidor responde `409 cancellation_window_closed`
- **THEN** la página muestra un mensaje con el teléfono de la clínica y el turno sigue vigente

### Requirement: Reprogramación con huecos válidos

La reprogramación SHALL mostrar solo los huecos que devuelve el servidor para el
mismo profesional, agrupados por día, en la zona de la clínica, y SHALL marcar el
horario actual del turno.

#### Scenario: Elegir un hueco nuevo

- **WHEN** el paciente abre "Cambiar horario" y elige un hueco libre
- **THEN** la página muestra el turno en el horario nuevo

#### Scenario: Hueco tomado en el intervalo

- **WHEN** el servidor responde `409 slot_taken` con alternativos
- **THEN** la página explica que el horario se ocupó y ofrece los alternativos

#### Scenario: Sin huecos disponibles

- **WHEN** el servidor devuelve una lista vacía
- **THEN** la página muestra el teléfono de la clínica en lugar de una grilla vacía

### Requirement: Pantalla de contacto para link inválido o vencido

Ante `404 manage_link_not_found` o `410 manage_link_expired`, la página SHALL
mostrar una pantalla de contacto con el nombre de la clínica y su teléfono
cuando exista, sin revelar datos del turno ni permitir acciones.

#### Scenario: Link vencido

- **WHEN** el servidor responde `410 manage_link_expired`
- **THEN** se muestra la pantalla de contacto y ninguna acción

#### Scenario: Link inválido

- **WHEN** el servidor responde `404 manage_link_not_found`
- **THEN** se muestra un mensaje genérico con la opción de volver a reservar si hay slug de clínica

### Requirement: Diseño mobile-first y accesible

La página SHALL ser usable a 360 px de ancho sin scroll horizontal, con controles
de al menos 44 px, foco visible, etiquetas asociadas y respeto de
`prefers-reduced-motion`; los estados de carga y error SHALL anunciarse a
lectores de pantalla.

#### Scenario: Celular angosto

- **WHEN** se abre la página en un viewport de 360×740
- **THEN** no hay scroll horizontal y los botones miden al menos 44 px

#### Scenario: Estado de carga anunciado

- **WHEN** la vista está cargando
- **THEN** se anuncia "Cargando tu turno" con `aria-live`
