# Spec delta — platform/hardening (C-14)

## ADDED Requirements

### Requirement: Envolvente de errores sin trazas ni PII
Toda respuesta de error SHALL ser `{"detail": <código>}`; los 5xx SHALL incluir `request_id`.
#### Scenario: excepción no prevista
- WHEN un endpoint lanza una excepción sin handler
- THEN responde `500 {"detail":"internal_error","request_id":…}` con `X-Request-ID` y sin traza
#### Scenario: carrera de locks
- WHEN Postgres devuelve `55P03`, `40001` o `40P01`
- THEN responde `409 concurrent_update` con `Retry-After: 1`

### Requirement: Rol de base `app_writer`
La app SHALL conectarse con un usuario miembro de `app_writer`, sin `DELETE` en ninguna tabla y sin `UPDATE` en las append-only.
#### Scenario: borrado físico
- WHEN la app intenta `DELETE FROM appointment`
- THEN Postgres responde `permission denied`

### Requirement: Métricas del piloto
`GET /api/reports/pilot` SHALL devolver solapamientos (meta 0), ausentismo vs. línea base, confirmación antes de T−24 h, huecos recuperados y proporción online, calculados sobre eventos.

### Requirement: Resiliencia de recepción ante cortes (SU-06)
Sin red, confirmación y asistencia SHALL quedar en una cola en memoria y reenviarse al volver; la agenda del día SHALL poder imprimirse.
