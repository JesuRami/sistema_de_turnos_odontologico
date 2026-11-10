# web/reports-admin Specification

## Purpose

Define la interfaz de usuario en la SPA para la visualización de reportes de ocupación, ausentismo, cancelaciones, consulta de auditoría y descarga de exportaciones para el administrador.

## Requirements

### Requirement: Página de reportes para administración

La SPA SHALL ofrecer `/admin/reportes`, accesible solo al rol admin, con
pestañas Ocupación, Ausentismo, Cancelaciones, WhatsApp, Lista de espera y
Auditoría y un selector de rango que por defecto abarca el mes en curso en la
zona de la clínica. Otros roles SHALL ser redirigidos y la entrada del menú
SHALL no mostrarse.

#### Scenario: Admin ve los reportes
- **WHEN** un admin abre `/admin/reportes`
- **THEN** ve las seis pestañas y el rango del mes actual

#### Scenario: Recepción no accede
- **WHEN** un usuario de recepción abre la ruta
- **THEN** es redirigido y el menú no la lista

### Requirement: Estados de carga, vacío y error

Cada pestaña SHALL mostrar carga, un mensaje de vacío cuando no hay datos y un
error que explique qué pasó y cómo reintentar. SHALL indicar que la capacidad
usa el horario vigente.

#### Scenario: Rango sin turnos
- **WHEN** el rango no tiene turnos
- **THEN** muestra el mensaje de vacío, no una tabla de ceros sin explicación

#### Scenario: Error de rango
- **WHEN** el backend responde `422 invalid_range`
- **THEN** muestra un mensaje en lenguaje claro y conserva los filtros

### Requirement: Descargas

Cada reporte SHALL tener "Descargar CSV" y la página "Exportar todos mis
datos" (ZIP completo, un clic), usando la sesión del usuario y sin credenciales
en la URL.

#### Scenario: Descarga de reporte
- **WHEN** el admin pulsa "Descargar CSV" en Ausentismo
- **THEN** se solicita el CSV con el rango activo y se inicia la descarga

#### Scenario: Exportación completa
- **WHEN** pulsa "Exportar todos mis datos"
- **THEN** se descarga el ZIP y se informa el resultado

### Requirement: Auditoría navegable

La pestaña Auditoría SHALL listar eventos con filtros por turno, tipo y rango,
paginación incremental ("Cargar más") y mostrar actor, estados antes/después y
hora local de la clínica.

#### Scenario: Cargar más
- **WHEN** hay `next_cursor`
- **THEN** "Cargar más" agrega la página siguiente sin repetir filas

### Requirement: Pestaña WhatsApp

La pestaña WhatsApp SHALL mostrar, para el rango activo, una fila por paso y
canal con enviados, entregados, leídos, fallidos y costo en USD, más el total,
con el paso en lenguaje claro ("Alta de turno", "72 h antes"…), su estado de
vacío y error y "Descargar CSV" con el rango activo.

#### Scenario: Mes con envíos

- **WHEN** el admin abre la pestaña WhatsApp en un mes con envíos
- **THEN** ve las filas por paso con sus cifras y el total

#### Scenario: Mes sin envíos

- **WHEN** el rango no tiene mensajes enviados
- **THEN** muestra el mensaje de vacío

#### Scenario: Descarga

- **WHEN** pulsa "Descargar CSV" en la pestaña WhatsApp
- **THEN** se solicita el CSV del reporte WhatsApp con el rango activo

### Requirement: Pestaña Lista de espera

La pestaña Lista de espera SHALL mostrar, para el rango activo, una fila por
profesional y el total con ofertas creadas (automáticas y manuales), aceptadas,
rechazadas, vencidas, cerradas y tasa de conversión, con su estado de vacío y
error y "Descargar CSV" con el rango activo. La pestaña WhatsApp SHALL nombrar el
paso `waitlist_offer` como "Oferta de lista de espera".

#### Scenario: Mes con ofertas

- **WHEN** el admin abre la pestaña en un mes con ofertas
- **THEN** ve cada profesional con sus cifras, la tasa y el total

#### Scenario: Tasa sin ofertas

- **WHEN** un profesional no tuvo ofertas
- **THEN** su tasa se muestra como "—"

#### Scenario: Descarga

- **WHEN** pulsa "Descargar CSV" en la pestaña
- **THEN** se solicita el CSV de `GET /api/reports/waitlist` con el rango activo
