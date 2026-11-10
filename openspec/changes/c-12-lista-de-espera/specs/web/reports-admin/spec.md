# Spec Delta — web/reports-admin

## MODIFIED Requirements

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

## ADDED Requirements

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
