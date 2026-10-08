# Preguntas Abiertas

## Inconsistencias detectadas

### IN-01 — Discovery pide circuito completo; MVP entrega solo agenda
**Documento A dice**: Discovery §D3 considera imprescindibles odontograma, caja, Mercado Pago, ARCA y obras sociales para "competir en AR".
**Documento B dice**: Q&A validado (P2) deja clínica/cobros/OS/ARCA como fases posteriores explícitas.
**Impacto**: relato comercial y roadmap deben ser coherentes: no vender "gestión integral" con un MVP de agenda.
**Resolución propuesta**: mantener agenda-first; el discurso v1 es "menos ausentismo, cero solapamientos, huecos llenos" y el circuito completo es roadmap fechado, no promesa del MVP. Resolver antes del piloto comercial.

### IN-02 — Single-tenant por clínica vs. cadena multi-sucursal del Discovery
**Documento A dice**: Discovery incluye clínica mediana/cadena multi-sucursal y comisiones como usuarios y competidores que la soportan.
**Documento B dice**: Q&A fija un tenant por clínica en fase 1.
**Impacto**: una cadena que pida consolidado multi-sede en v1 no puede atenderse.
**Resolución propuesta**: multi-sede es fase 2 con multi-tenant lógico (el `clinic_id` ya lo prepara); no aceptar cadenas como piloto v1. Registrar como criterio de selección de piloto.

## Preguntas abiertas (priorizadas)

| Prioridad | Pregunta | Bloquea | Decisor |
|-----------|----------|---------|---------|
| Alta | ¿Rotamos el `manage_token` en cada reprogramación o lo conservamos hasta TTL? (seguridad vs. links viejos en WhatsApp que siguen vivos) | Diseño detallado auth | Tech Lead + PO |
| Alta | ¿Qué CAPTCHA/anti-bot lleva la reserva pública (Turnstile, reCAPTCHA, ninguno + rate-limit)? Sin esto, el endpoint de disponibilidad es enumerable y spameable | Sprint 1 (booking público) | Tech Lead |
| Alta | ¿Quién paga el alta de plantillas Meta y el número de WhatsApp: la clínica (su Business Manager) o nosotros (número compartido)? Define facturación, riesgo de ban y portabilidad | Piloto (antes de enviar 1 mensaje) | PO / Dueño |
| Alta | **Cumplimiento Ley 27.706 (historia clínica electrónica interoperable) y Ley 26.529**: el MVP no guarda datos clínicos, pero el `patient_id` y los contactos son datos de salud en contexto. ¿Qué resguardos (consentimiento, retención, portabilidad HL7 FHIR futura) se exigen desde v1 para no re-arquitecturar en fase clínica? | Diseño (modelo de consentimiento y retención) | Asesor legal + PO |
| Media | ¿Recepción puede forzar prioridad en lista de espera saltando FIFO (con motivo auditado) o FIFO es estricto? | Sprint lista de espera | PO |
| Media | ¿El odontólogo ve motivos de cancelación y teléfonos, o vista reducida (solo nombre+hora)? Privacidad entre profesionales | Diseño de vista odontólogo | PO |
| Media | ¿On-premise o despliegue dedicado se ofrece alguna vez, o SaaS puro para siempre? (Q&A dice no on-premise en fase 1; dejar la puerta cerrada o entreabierta condiciona contratos) | Roadmap / contratos | Dueño |
| Media | ¿Feriados nacionales AR se precargan automáticamente o carga manual por clínica? (RN-BL-04 fijó manual; confirmar que no se espera calendario oficial) | Backlog | PO |
| Baja | ¿Tope de sobreturnos default 2/día/profesional se valida en piloto o se deja libre con solo auditoría? | Piloto | PO + clínicas piloto |
| Baja | ¿Página de reserva con dominio propio por clínica (`clinica.tudominio.com`) o slug compartido (`app.com/b/slug`)? (SEO vs. costo TLS/multi-dominio) | Lanzamiento | PO |
| Baja | Fases posteriores: ¿el orden es (1) clínica/odontograma → (2) cobros/MP → (3) ARCA → (4) obras sociales, u otro? El orden condiciona qué ganchos dejar en v1 | Roadmap post-MVP | Dueño + PO |

## Registro para fases posteriores (no MVP, no olvidar)

- Clínica: odontograma FDI por cara, periodontograma, imágenes, evoluciones, consentimientos con firma Ley 25.506, ReNaPDiS/HL7 FHIR donde aplique.
- Cobros: caja, señas, Mercado Pago QR/link, cuenta corriente, conciliación automática.
- Fiscal/OS: factura ARCA en el cobro, nomenclador por convenio, validación online (DentalTec como referencia), autorizaciones, liquidación mensual, flujo Círculo → Federación.
- Crecimiento: multi-sucursal, comisiones, laboratorio, stock/esterilización, CRM/recall avanzado, IA (CDSS/dictado/rx), videoconsulta, portal paciente con login, API pública, Google Calendar.
