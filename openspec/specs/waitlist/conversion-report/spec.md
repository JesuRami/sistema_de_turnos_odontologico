# waitlist/conversion-report Specification

## Purpose
Muestra al administrador cuántas ofertas de la lista de espera se hicieron y
cuántas terminaron en turno, por profesional y con exportación CSV, calculado
sobre la auditoría de la lista y no sobre estados mutables.

## Requirements

### Requirement: Reporte de conversión solo para administración

`GET /api/reports/waitlist` SHALL ser accesible solo para el rol admin, con los
mismos parámetros de rango y validaciones que los demás reportes (`from` y `to`
como fechas locales inclusive, hasta 366 días, parámetros desconocidos
rechazados). Recepción y odontólogo SHALL recibir `403 forbidden_role`.

#### Scenario: Recepción pide la conversión

- **WHEN** un usuario de recepción llama `GET /api/reports/waitlist`
- **THEN** responde `403 forbidden_role`

#### Scenario: Rango invertido

- **WHEN** `from` es posterior a `to`
- **THEN** responde `422 invalid_range`

### Requirement: Cifras de conversión por profesional

El reporte SHALL devolver, por profesional del hueco ofrecido y en total, para
las ofertas creadas en el rango (fecha local de la clínica): ofertas creadas
(separando automáticas y manuales), aceptadas, rechazadas, vencidas, cerradas y
la tasa de conversión `aceptadas / creadas`, redondeada a un decimal y `null`
sin ofertas.

#### Scenario: Una rotación que convierte

- **WHEN** en el rango una oferta automática venció y la siguiente se aceptó
- **THEN** el profesional muestra 2 creadas, 1 vencida, 1 aceptada y 50,0 %

#### Scenario: Sin ofertas

- **WHEN** el rango no tiene ofertas
- **THEN** cada fila muestra ceros y tasa `null`

#### Scenario: Oferta manual

- **WHEN** recepción hizo una oferta manual en el rango
- **THEN** cuenta en creadas y en manuales

### Requirement: Conversión calculada sobre eventos

Las cifras SHALL calcularse desde los eventos append-only de la lista, tomando el
último evento de cada oferta como su resultado, y SHALL NOT leer el estado
mutable de ofertas ni entradas. Una oferta todavía pendiente SHALL contarse solo
en creadas.

#### Scenario: Estado mutado sin evento

- **WHEN** se altera directamente el estado de una oferta en la base de pruebas
  sin escribir evento
- **THEN** el reporte no cambia

### Requirement: Exportación CSV de la conversión

El reporte SHALL admitir `format=csv` con el mismo contenido que el JSON,
encabezados fijos, UTF-8, `Content-Disposition` de descarga y neutralización de
valores que empiecen con `=`, `+`, `-` o `@`, como los demás reportes.

#### Scenario: CSV de la conversión

- **WHEN** el admin pide `format=csv`
- **THEN** recibe un CSV con una fila por profesional y la fila total

### Requirement: Aislamiento del reporte de conversión

El reporte SHALL incluir solo ofertas de la clínica del admin.

#### Scenario: Dos clínicas

- **WHEN** hay ofertas en dos clínicas y el admin de la A pide el reporte
- **THEN** las cifras incluyen solo las de la A
