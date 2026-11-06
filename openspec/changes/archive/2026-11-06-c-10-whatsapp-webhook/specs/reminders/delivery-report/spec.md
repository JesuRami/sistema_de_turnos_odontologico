# Spec Delta — reminders/delivery-report

## Purpose

Da al administrador de cada clínica la cuenta de mensajes de recordatorio
enviados, entregados, leídos y fallidos por paso y su costo atribuido, como base
de la transparencia y el pricing del canal (RN-WA-05).

## ADDED Requirements

### Requirement: Reporte de mensajes solo para administración

`GET /api/reports/whatsapp` SHALL ser accesible únicamente para el rol admin y
limitarse a la clínica del usuario. Recepción y odontólogo SHALL recibir
`403 forbidden_role`; sin sesión, `401`.

#### Scenario: Recepción pide el reporte

- **WHEN** un usuario de recepción llama `GET /api/reports/whatsapp`
- **THEN** responde `403 forbidden_role`

#### Scenario: Aislamiento entre clínicas

- **WHEN** dos clínicas enviaron mensajes en el mismo rango
- **THEN** el admin de la clínica A ve solo los de la clínica A

### Requirement: Rango por fecha de envío

El reporte SHALL requerir `from` y `to` (fechas locales de la clínica, inclusive)
y filtrar por la fecha local de envío. `from > to` SHALL responder `422
invalid_range`; más de 366 días, `422 range_too_large`; parámetros desconocidos,
`422 unknown_parameter`.

#### Scenario: Mensaje en el borde del día

- **WHEN** un mensaje se envió a las 23:30 locales del 31/10 (02:30 UTC del 1/11)
- **THEN** cuenta en un rango que termina el 31/10 y no en uno que empieza el 1/11

#### Scenario: Rango invertido

- **WHEN** `from` es posterior a `to`
- **THEN** responde `422 invalid_range`

### Requirement: Cifras por paso y canal

El reporte SHALL devolver una fila por paso y canal con enviados, entregados,
leídos, fallidos y costo atribuido, más un total. Cada mensaje SHALL contarse una
vez por estado alcanzado (un leído también cuenta como entregado). Los pasos
configurados SHALL aparecer con 0 si no hubo envíos.

#### Scenario: Mezcla de estados

- **WHEN** en el rango se enviaron tres recordatorios de 24 h por WhatsApp: uno
  leído, uno solo entregado y uno fallido después de enviado
- **THEN** la fila `t_24h / whatsapp` muestra enviados 3, entregados 2, leídos 1,
  fallidos 1

#### Scenario: Paso sin envíos

- **WHEN** no hubo recordatorios de 3 h en el rango
- **THEN** la fila `t_3h / whatsapp` aparece con todos los valores en 0

### Requirement: Costo atribuido

El costo SHALL ser la suma del costo registrado al enviar cada mensaje del rango,
por paso y canal, expresado en USD con 6 decimales. Los mensajes que nunca se
enviaron SHALL NOT sumar costo.

#### Scenario: Costo por paso

- **WHEN** se enviaron 2 mensajes de 24 h con costo 0,0125 USD cada uno
- **THEN** el costo de esa fila es 0,025000

### Requirement: Cálculo sobre eventos inmutables

Los conteos SHALL calcularse desde los eventos de entrega registrados y SHALL NOT
depender del estado actual mutable del job.

#### Scenario: Estado alterado

- **WHEN** se altera directamente el estado de un job en la base de pruebas sin
  escribir evento
- **THEN** el reporte no cambia

### Requirement: Exportación CSV del reporte

El reporte SHALL admitir `format=csv` con las mismas cifras que el JSON,
encabezados fijos, UTF-8, `Content-Disposition` de descarga y neutralización de
valores que empiecen con `=`, `+`, `-` o `@`. Otro formato SHALL responder
`422 invalid_format`.

#### Scenario: Descarga CSV

- **WHEN** el admin pide `format=csv`
- **THEN** recibe `text/csv` con una fila por paso y canal más el total, con las
  mismas cifras que el JSON

#### Scenario: Sin datos personales

- **WHEN** se descarga el CSV
- **THEN** no contiene nombres, teléfonos, emails ni ids de mensaje del proveedor
