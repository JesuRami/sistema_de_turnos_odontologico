# Spec Delta — web/reports-admin

## MODIFIED Requirements

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

## ADDED Requirements

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
