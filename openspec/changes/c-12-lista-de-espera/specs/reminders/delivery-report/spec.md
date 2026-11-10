# Spec Delta — reminders/delivery-report

## ADDED Requirements

### Requirement: Ofertas de lista de espera en el reporte

El reporte SHALL incluir una fila por canal para el paso `waitlist_offer`, con
las mismas reglas de conteo y costo que los pasos de recordatorio, y SHALL
mostrarla con 0 aunque no haya habido ofertas en el rango. El total SHALL sumar
esas filas.

#### Scenario: Oferta enviada y leída

- **WHEN** en el rango se envió una oferta por WhatsApp que el paciente leyó
- **THEN** la fila `waitlist_offer / whatsapp` muestra enviados 1, entregados 1,
  leídos 1 y el costo de un mensaje, y el total lo incluye

#### Scenario: Oferta escalada a email

- **WHEN** una oferta falló por WhatsApp y salió por email
- **THEN** la fila `waitlist_offer / whatsapp` cuenta el fallo y la fila
  `waitlist_offer / email` cuenta el envío

#### Scenario: Sin ofertas

- **WHEN** no hubo ofertas en el rango
- **THEN** las filas `waitlist_offer` aparecen con todos los valores en 0
