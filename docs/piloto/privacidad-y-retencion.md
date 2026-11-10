# Privacidad, consentimiento, retención y portabilidad — v1 (C-14)

**Estado: default propuesto, pendiente de asesor legal + PO** (pregunta Alta de `10`, Ley 27.706/26.529/25.326).

- **Datos que guarda v1**: nombre, teléfono E.164, email, DNI opcional, turnos y su auditoría. Sin datos clínicos.
- **Consentimiento**: por canal (WhatsApp/email), append-only en `consent` (C-09) + aceptación de política en la reserva.
- **Portabilidad/acceso**: exportación completa de la clínica (C-13) y por paciente
  `GET /api/exports/patients/{id}` (C-14), ambas auditadas en `auth_event`.
- **Retención propuesta**: 10 años para datos asociados a atención (Ley 26.529 art. 18). **Sin purga
  automática en v1**; la app no puede borrar (rol `app_writer` sin DELETE).
- **Logs**: JSON redactados (sin teléfonos, emails, DNI ni tokens).
