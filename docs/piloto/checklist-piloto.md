# Checklist del piloto (C-14)

Criterio de selección (IN-02): 1-2 clínicas amigas, un solo consultorio/sede. Nada de cadenas.

## Antes de enviar el primer mensaje
- [ ] Decisión comercial de titularidad del número WhatsApp (pregunta Alta abierta en `10`).
- [ ] 6 plantillas Meta aprobadas (alta, 72 h, 24 h, 3 h, oferta de lista de espera y respuesta).
      Hoy el catálogo (`backend/app/modules/reminders/templates.py`) tiene `turno_creado_v1` y
      `hueco_lista_espera_v1` con nombre fijo; los pasos por hora salen de `notification_template`
      de cada clínica: confirmar que los 4 restantes estén cargados y aprobados.
- [ ] 2 variantes de respaldo cargadas; si Meta rechaza alguna, el canal email cubre ese paso.
- [ ] `REMINDER_COST_WHATSAPP_MICROS` con el precio vigente y umbral mensual en Políticas.

## Infraestructura
- [ ] `ENV=prod`, `ALLOWED_HOSTS`, `CORS_ORIGINS` y `FRONTEND_PUBLIC_URL` en https (el arranque lo exige).
- [ ] Secretos generados con `openssl rand -hex 32`: `JWT_SECRET`, `MANAGE_LINK_SECRET`, `APP_DB_PASSWORD`, `DB_PASSWORD`.
- [ ] App y worker con el usuario de `app_writer` (`compose.prod.yaml`).
- [ ] Backups cifrados con PITR configurados y **restauración probada** (`backups-pitr.md`).
- [ ] Recepción imprime la agenda del día al abrir (`/agenda/imprimir`).

## Métricas de éxito (Reportes → Piloto)
| Métrica | Meta |
|---|---|
| Solapamientos | 0 |
| Ausentismo | −20 % vs. línea base (cargarla en la pestaña) |
| Confirmación antes de T−24 h | ≥ 60 % |
| Huecos recuperados por lista de espera | ≥ 10 % |
| Reservas online | ≥ 30 % a 90 días |
