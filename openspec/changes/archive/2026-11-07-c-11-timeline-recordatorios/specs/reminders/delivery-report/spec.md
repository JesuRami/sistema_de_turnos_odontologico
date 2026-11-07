# Spec Delta — reminders/delivery-report

## MODIFIED Requirements

### Requirement: Cifras por paso y canal

El reporte SHALL devolver una fila por paso y canal con enviados, entregados,
leídos, fallidos y costo atribuido, más un total. **Enviados** SHALL contar cada
evento `sent` del rango, incluidos los reenvíos manuales. **Entregados** y
**leídos** SHALL contarse una vez por job, sin multiplicarse por los reenvíos.
Los pasos configurados SHALL aparecer con 0 si no hubo envíos.

#### Scenario: Mezcla de estados

- **WHEN** en el rango se enviaron tres recordatorios de 24 h por WhatsApp: uno
  leído, uno solo entregado y uno fallido después de enviado
- **THEN** la fila `t_24h / whatsapp` muestra enviados 3, entregados 2, leídos 1,
  fallidos 1

#### Scenario: Reenvío manual entregado

- **WHEN** un job de 24 h se envió una vez, falló y recepción lo reenvió
  registrándose la entrega en el proveedor dentro del mismo rango
- **THEN** la fila `t_24h / whatsapp` muestra enviados 2, entregados 1, leídos 0, fallidos 0

#### Scenario: Reenvío manual pendiente de confirmación de entrega

- **WHEN** un job de 24 h se envió una vez, falló y recepción lo reenvió quedando
  enviado (`sent`) sin confirmación de entrega del proveedor aún
- **THEN** la fila `t_24h / whatsapp` muestra enviados 2, entregados 0, leídos 0, fallidos 0

#### Scenario: Paso sin envíos

- **WHEN** no hubo recordatorios de 3 h en el rango
- **THEN** la fila `t_3h / whatsapp` aparece con todos los valores en 0

### Requirement: Costo atribuido

El costo SHALL ser la suma del costo registrado en cada evento `sent` del rango,
por paso y canal, expresado en USD con 6 decimales. Los reenvíos manuales SHALL
sumar su costo. Los mensajes que nunca se enviaron SHALL NOT sumar costo.

#### Scenario: Costo por paso

- **WHEN** se enviaron 2 mensajes de 24 h con costo 0,0125 USD cada uno
- **THEN** el costo de esa fila es 0,025000

#### Scenario: Costo de un reenvío

- **WHEN** un job de 24 h se envió y se reenvió manualmente, ambos con costo
  0,0125 USD
- **THEN** la fila suma 0,025000 y no 0,012500

#### Scenario: Reenvío no enviado

- **WHEN** recepción reencoló un reenvío pero el worker todavía no lo envió
- **THEN** ese reenvío no suma costo ni enviados

## ADDED Requirements

### Requirement: Fallidos del último intento

**Fallidos** SHALL contar el job cuyo último intento tiene un evento `failed`
posterior al último `sent` (comparado al segundo, porque Meta informa con
segundos enteros); una falla anterior ya reenviada SHALL NOT contarse.

#### Scenario: Falla anterior ya reenviada

- **WHEN** el primer envío de un job falló y el reenvío posterior se entregó
- **THEN** el job no suma un fallido, porque el último intento no falló

#### Scenario: Falla del mismo segundo que el envío

- **WHEN** Meta informa `failed` con un `timestamp` del mismo segundo en que se
  registró el `sent`
- **THEN** el job cuenta como fallido
