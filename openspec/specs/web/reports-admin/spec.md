# web/reports-admin Specification

## Purpose

Define la interfaz de usuario en la SPA para la visualización de reportes de ocupación, ausentismo, cancelaciones, consulta de auditoría y descarga de exportaciones para el administrador.

## Requirements

### Requirement: Página de reportes para administración

La SPA SHALL ofrecer `/admin/reportes`, accesible solo al rol admin, con
pestañas Ocupación, Ausentismo, Cancelaciones, WhatsApp y Auditoría y un
selector de rango que por defecto abarca el mes en curso en la zona de la
clínica. Otros roles SHALL ser redirigidos y la entrada del menú SHALL no
mostrarse.

#### Scenario: Admin ve los reportes
- **WHEN** un admin abre `/admin/reportes`
- **THEN** ve las cinco pestañas y el rango del mes actual

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
