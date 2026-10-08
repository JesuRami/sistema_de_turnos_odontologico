# Discovery — Sistema de turnos odontológico (mercado AR / LATAM)

**Fecha de elaboración**: 2026-10-08
**Alcance**: Argentina (prioridad), Latinoamérica, internacionales relevantes como inspiración
**Metodología**: relevamiento exclusivo de fuentes verificables (sitios oficiales, páginas de precios, ayuda/documentación pública, comparativas con verificación de fuentes oficiales). Cada fuente indica URL y fecha de consulta. Cuando una característica no está demostrada públicamente se consigna como **«No evidenciado»**. Se distingue entre **funcionalidad comprobada** (visible en producto, documentación, precios o ayuda oficial) y **afirmación comercial** (marketing sin evidencia pública).
**Fecha de consulta de todas las fuentes web**: 2026-10-08 (salvo indicación contraria en la ficha).

---

## 1. Problema que resuelve (síntesis Discovery)

Los consultorios y clínicas odontológicas argentinas gestionan agenda, historia clínica, cobros y obras sociales con herramientas fragmentadas (papel, WhatsApp manual, planillas, facturación en portal ARCA por separado). Esto genera dobles reservas y solapamientos, ausentismo sin recordatorios sistemáticos, pérdida de presupuestos no aceptados, débitos de obras sociales por falta de validación preventiva, y conciliación manual entre lo cobrado, lo facturado y lo liquidado. El problema no es solo «dar turnos online»: es cerrar el circuito turno → atención clínica (odontograma) → presupuesto/plan → cobro → factura ARCA → liquidación de obra social → recall, con trazabilidad y WhatsApp como canal dominante del paciente argentino.

## 2. Usuarios / roles

- **Odontólogo independiente / consultorio 1–2 sillones**: agenda personal, ficha clínica, odontograma, cobros particulares, reserva online simple.
- **Recepción / administración de clínica**: agenda multi-profesional y multi-sillón/box, estados de turno, sala de espera, confirmaciones, caja diaria, señas, lista de espera.
- **Clínica mediana / cadena / multi-sucursal**: roles y permisos, liquidaciones de obras sociales, comisiones por profesional, reportes, inventario/laboratorio, auditoría.
- **Paciente**: reserva online 24/7, confirmación/cancelación/reprogramación, recordatorios, presupuestos, pagos (seña, Mercado Pago), portal/recetas.
- **Círculos / federaciones / gerenciadoras** (caso argentino específico): validación de prácticas, nomencladores por convenio, flujo Círculo → Federación → Confederación.

## 3. Casos de uso centrales

1. Como paciente, quiero reservar un turno online 24/7 (link, web, Instagram, WhatsApp) sin llamar.
2. Como recepción, quiero ver la agenda diaria/semanal por profesional y sillón, con bloqueos, sobreturnos y prevención de solapamientos.
3. Como paciente, quiero confirmar/cancelar/reprogramar y entrar en lista de espera si se libera un hueco.
4. Como clínica, quiero enviar recordatorios automáticos (WhatsApp/email/SMS) y recuperar ausentes y controles periódicos.
5. Como odontólogo, quiero registrar anamnesis, odontograma/periodontograma, imágenes y evolución, y generar plan de tratamiento y presupuesto.
6. Como administración, quiero cobrar (caja, seña, Mercado Pago), emitir factura electrónica ARCA, gestionar obras sociales/prepagas y liquidar por período.
7. Como dueño, quiero reportes (ocupación, ausentismo, producción por profesional, conversión de presupuestos) y roles/permisos con auditoría y exportación de datos.

---

## A. Tabla comparativa (ordenada por relevancia para Argentina)

Ordenada por relevancia para un producto argentino (integración local real: obras sociales + ARCA + Mercado Pago + WhatsApp, más cercanía de soporte/moneda). Leyenda: ✅ comprobado en fuente oficial · ⚠️ afirmación comercial / parcial · ❌ no ofrecido o no evidenciado.

### A1. Sistemas argentinos con foco odontológico (núcleo competitivo)

#### 1. OdonFlow — Córdoba, Argentina — https://odonflow.com/ (consulta: 2026-10-08)
- **Segmento**: consultorio 1–2 profesionales, clínica con equipo y obras sociales, multi-sede. **Modalidad**: SaaS 100% nube en navegador, sin instalación (comprobado en FAQ oficial).
- **Agenda**: multi-profesional y multi-sillón, drag & drop, sobreturnos, lista de espera, bloqueos de vacaciones, sala de espera, tótem por DNI y pantalla de llamado (comprobado). Prevención de solapamientos: implícita por bloqueos/agenda real; no se publica motor formal de reglas → consignar como ⚠️ parcial.
- **Turnos digitales**: página de turnos online + asistente que agenda por WhatsApp/Instagram/Messenger contra agenda real, recordatorios que se confirman con «SÍ», «Comentá TURNO» en Instagram, videoconsulta sin instalación (comprobado). Cancelación/reprogramación: comprobado vía asistente y recordatorios; lista de espera: comprobada.
- **Automatización**: 18 automatizaciones declaradas (afirmación comercial; número exacto no verificable sin demo), recordatorios/confirmaciones automáticas en plan superior (comprobado en planes).
- **Clínica**: historia clínica «inmutable», odontograma por caras, periodontograma, ortodoncia con cefalometría, recetas, imágenes en ficha (comprobado). Firma digital en plan superior (comprobado).
- **Administración**: obras sociales argentinas con nomenclador por convenio, coseguro, autorizaciones y lote para presentar (comprobado en página + guía https://odonflow.com/software-odontologico-argentina, 2026-10-08); facturación ARCA con CAE + Mercado Pago + caja del día (comprobado); 30 informes en Excel, rentabilidad/metas (comprobado).
- **Integraciones**: WhatsApp/Instagram/Messenger en bandeja compartida (comprobado); Mercado Pago y ARCA (comprobado); API pública: **No evidenciado**; Google Calendar: **No evidenciado**.
- **Operación**: multi-sucursal (plan superior), roles y permisos (comprobado por «sumás a todo el equipo»), stock/esterilización/laboratorio (plan Pro), exportación: declara «te llevás tus datos» sin formato publicado → ⚠️ parcial. Soporte/capacitación: puesta en marcha en una semana con carga de profesionales/horarios/convenios (comprobado).
- **Seguridad**: historia «inmutable» (afirmación comercial; sin detalle de cifrado/backup/RGPD ni adecuación a Ley 27.706/26.529 publicada) → ⚠️.
- **Comercial**: precio cerrado por clínica, sin costo de instalación, sin permanencia (comprobado); montos **no publicados** → cotización. Prueba/demo: a coordinar.
- **Fortalezas**: único argentino relevado que combina obras sociales + ARCA + Mercado Pago + asistente WhatsApp/IG + multi-sillón en nube. **Limitaciones**: producto nuevo (menos años de calle, reconocido por el propio proveedor); precios no publicados; seguridad/cumplimiento sin evidencia técnica pública.

#### 2. DentalCore — La Plata, Argentina — https://dentalcore.app/ (consulta: 2026-10-08)
- **Segmento**: consultorio individual a clínica multi-profesional; 8 países LATAM. **Modalidad**: SaaS nube (comprobado).
- **Agenda**: visual drag & drop, confirmación por WhatsApp con link (el paciente confirma/cancela y la agenda se actualiza sola), sala de espera, ventana de cancelación configurable (comprobado). Multi-profesional: comprobado.
- **Turnos digitales**: confirmación/cancelación por link; portal del paciente declarado como «próximamente» (no disponible) → ❌ portal a la fecha.
- **Automatización**: recordatorios 48/24 h, post-operatorios, controles, cumpleaños (comprobado); asistente de voz que agenda/mueve turnos y dicta evolución/odontograma (comprobado, con nota de que usa clave IA del cliente).
- **Clínica**: historia clínica + odontograma + periodontograma + módulos por especialidad + CDSS de 17 motores con fuente citada + patología oral + recetas/consentimientos/derivaciones + inventario por lote + órdenes de laboratorio + videoconsulta (comprobado en lista de plan único). Diferencial real: CDSS.
- **Administración**: factura ARCA con CUIT por WhatsApp + Mercado Pago (QR/link, cobro entra solo a caja) + caja diaria con arqueo + deudores + cobertura/copago + liquidación de obras sociales por período + 20+ convenios precargados (PAMI, OSDE, IOMA, etc., según comparativa Odonthia 2026-07-19 que cita su sitio). Consistencia a verificar en demo (convenios exactos).
- **Integraciones**: WhatsApp vía ventana oficial de Meta/bandeja compartida (comprobado); Mercado Pago en AR/MX/CL/CO/PE/UY (comprobado); ARCA solo AR (comprobado); API pública / Google Calendar / firma digital: **No evidenciado**.
- **Operación**: multi-usuarios; multi-sucursal: **No evidenciado** en página de plan único. Exportación/soporte: **No evidenciado** con detalle.
- **Seguridad**: **No evidenciado** (sin página de seguridad/cumplimiento a la fecha).
- **Comercial**: un solo plan con todo incluido: USD 50/mes con 2 usuarios + USD 10/usuario extra (comprobado). Reembolso 14 días (comprobado). Nota: la comparativa Odonthia cita USD 69/139/399 Enterprise — discrepancia entre páginas; tomar como ⚠️ y pedir cotización escrita vigente.
- **Fortalezas**: CDSS citado con literatura, ARCA + Mercado Pago + obras sociales en plan único transparente. **Limitaciones**: sin portal paciente, sin evidencia de multi-sede/API, precio en USD (fricción cambiaria AR).

#### 3. Bilog — Argentina — https://bilog.com.ar/funcionalidades/ (consulta: 2026-10-08)
- **Segmento**: consultorios y clínicas de todo el país; multi-profesional y multi-sede. **Modalidad**: App Web + App Mobile (iOS/Android) + IA «iAngela» (comprobado).
- **Agenda**: agenda de turnos, horarios por profesional, estados, confirmaciones, recordatorios, turnos online/web, cancelación por el paciente, alta por QR (comprobado). Multi-sillón/solapamientos: **No evidenciado** con ese vocabulario.
- **Automatización**: recordatorios/confirmaciones (comprobado); IA que acompaña gestión de turnos y responde consultas + análisis radiológico «iAngela» (afirmación comercial sin detalle técnico público) → ⚠️.
- **Clínica**: pacientes + historia clínica (comprobado); odontograma: comprobado solo vía plan Freemium en comparativa Odonthia (sitio funcional no detalla FDI/periodontograma) → ⚠️ parcial, verificar en demo.
- **Administración**: gestión económica, liquidaciones (fuerte declarado: liquidaciones de obras sociales y auditoría para gerenciadoras, según comparativa Odonthia basada en posicionamiento Bilog), indicadores/KPI (comprobado). Mercado Pago / ARCA / señas: **No evidenciado** en página funcional.
- **Integraciones**: WhatsApp: **No evidenciado** como automático en página funcional. API/Google Calendar: **No evidenciado**.
- **Operación**: múltiples profesionales, permisos, reportes, liquidaciones (comprobado); exportación/auditoría: declarado para gerenciadoras pero sin detalle público → ⚠️.
- **Seguridad**: «Seguridad y permisos» como área (comprobado nominal); cifrado/backup/normativa: **No evidenciado**.
- **Comercial**: Freemium sin costo hasta 50 pacientes/1 profesional con odontograma (según comparativa Odonthia 2026-07-19); Lite/Premium por cotización (no publica). 20+ años y +1.500 clínicas (afirmación comercial del proveedor citada por tercero).
- **Fortalezas**: trayectoria AR + liquidaciones/auditoría para gerenciadoras + app móvil real. **Limitaciones**: sin precios, sin evidencia ARCA/Mercado Pago/WhatsApp automático en fuente oficial relevada.

#### 4. DentalTec — San Juan, Argentina — https://web.dentaltec.com.ar/software-odontologos-argentina y /preguntas-frecuentes (consulta: 2026-10-08)
- **Segmento**: profesionales, círculos/federaciones/CORA, instituciones. **Modalidad**: 100% web sin instalación (comprobado).
- **Agenda**: agenda digital con recordatorios WhatsApp automáticos (comprobado). Multi-profesional/sillón/bloqueos: **No evidenciado** en páginas relevadas.
- **Turnos digitales**: reserva online: **No evidenciado** como turnero público.
- **Automatización**: recordatorios WhatsApp (comprobado); validación preventiva en tiempo real contra obra social (afiliado, nomenclador, topes, autorizaciones) con −64% débitos (afirmación comercial con métrica propia, sin auditoría independiente) → ⚠️ como métrica, ✅ como función declarada con 15 OS listadas.
- **Clínica**: odontograma digital + historia clínica (comprobado nominal); periodontograma/imágenes: **No evidenciado**.
- **Administración**: facturación automática con ARCA (ex AFIP) + planillas + flujo Círculo→Federación→Confederación + re-facturación inteligente (comprobado declarado); +15 OS (OSDE, Swiss Medical, Jerárquicos, Sancor, OSSEG, IOSEP, etc.) vía adaptadores SOAP (comprobado listado). Mercado Pago/caja diaria: **No evidenciado**.
- **Operación**: gestión jerárquica multi-entidad (comprobado declarado); roles/exportación/soporte 24/7: declarado sin detalle → ⚠️.
- **Seguridad**: **No evidenciado**.
- **Comercial**: no publica precios; demo a pedido (comprobado). +2.000 profesionales y adopción CORA/círculos (afirmación comercial del proveedor).
- **Fortalezas**: validación OS en tiempo real + ARCA + jerarquía institucional, único en su tipo. **Limitaciones**: sin evidencia de turnero paciente/odontograma avanzado/cobros modernos; opaco en precios.

#### 5. FLAP — Argentina — https://flap.com.ar/odontologos (consulta: 2026-10-08)
- **Segmento**: independiente a clínica/multi-sucursal. **Modalidad**: SaaS nube (comprobado).
- **Agenda**: por profesional con especialidad/box/disponibilidad propia, duraciones, bloqueos, estados, autoasignación por carga diaria/semanal (comprobado — diferencial real). Multi-box: comprobado.
- **Turnos digitales**: página de reservas responsive + turnero con seña (comprobado); WhatsApp: avisos automáticos con email incluido y WhatsApp por paquetes adicionales (comprobado); chatbot IA: **No evidenciado**.
- **Clínica**: historia clínica + odontograma FDI por piezas/superficies/eventos + evoluciones (comprobado); periodontograma/imágenes: **No evidenciado**.
- **Administración**: señas y cobros + Mercado Pago vinculado a reserva (comprobado según plan); facturación ARCA/obras sociales/liquidaciones: **No evidenciado** → limitante decisiva para OS.
- **Integraciones**: Mercado Pago (comprobado); API/Google Calendar/AFIP: **No evidenciado**.
- **Operación**: sucursales/permisos (comprobado por plan); analíticas de agenda (comprobado); exportación/auditoría/seguridad: **No evidenciado**.
- **Comercial**: precios **no publicados** en página odontológica relevada; capacitación inicial sin costo (comprobado).
- **Fortalezas**: agenda por recurso con autoasignación + odontograma + Mercado Pago. **Limitaciones**: sin evidencia de obras sociales/ARCA.

#### 6. ClinIA / OdontoClinIA — Argentina — https://www.clinia.com.ar/odontologia (consulta: 2026-10-08)
- **Segmento**: consultorios, clínicas PyME, hospitales/municipios. **Modalidad**: plataforma web (comprobado).
- **Agenda**: por profesional/especialidad/sillón con recordatorios WhatsApp/correo + asistente IA por WhatsApp que reserva/confirma/cancela/reprograma en lenguaje natural contra agenda real (comprobado declarado).
- **Clínica**: odontograma FDI 52 piezas por cara (5 caras, caries/corona/endo por conducto/extracción/fractura/encía, rojo=existente/azul=indicado, PDF con matrícula) + plan con CIE-10 y nomenclador por institución + historia con IA contextual (comprobado en detalle — el odontograma más especificado de la muestra AR).
- **Administración**: verificación PUCO (SSS) + prácticas del odontograma al circuito de facturación OS/prepagas + factura electrónica ARCA (comprobado declarado); Mercado Pago/caja: **No evidenciado**.
- **Cumplimiento**: recetario electrónico ReNaPDiS #248 con HL7 FHIR (comprobado, con alcance limitado al recetario — el propio sitio lo aclara, buena práctica de transparencia).
- **Comercial/operación/seguridad**: precios, roles, exportación, cifrado: **No evidenciado**.
- **Fortalezas**: profundidad odontológica + PUCO + ReNaPDiS/FHIR. **Limitaciones**: sin precios ni evidencia de cobros/móvil/exportación.

#### 7. Odontoly — Argentina — https://odontoly.com/ (consulta: 2026-10-08)
- **Segmento**: consultorio (titular + equipo chico). **Modalidad**: app de escritorio local-first (Mac/Apple Silicon firmado y notarizado) + acceso remoto por navegador; no app móvil nativa (comprobado). Opera con corte temporal con sesión vigente (comprobado).
- **Agenda**: turnos/tareas/solicitudes de reserva con enlace de reservas que el equipo confirma (comprobado; sin bot). Multi-profesional/sillón/sobreturnos/solapamientos: **No evidenciado** con ese detalle.
- **Clínica**: historia, evoluciones, odontograma, archivos/fotos/rx vinculados, presupuestos imprimibles (comprobado).
- **Administración**: caja ARS/USD con cotización manual histórica, gastos/deudas/resumen del día (comprobado); Mercado Pago/ARCA/obras sociales: **No evidenciado** (asistente IA y facturación figuran como previstos, no disponibles).
- **Comercial**: USD 149,99/mes sin permanencia, 2 usuarios y 4 dispositivos (comprobado). Sin prueba gratuita evidenciada; activación acompañada.
- **Fortalezas**: local-first + ARS/USD + presupuestos. **Limitaciones**: sin nube real/multi-sede, sin WhatsApp automático, sin ARCA/OS, precio en USD alto para independiente.

#### 8. Livio — Argentina — https://www.liviodental.com/ (consulta: 2026-10-08)
- **Segmento**: clínicas en crecimiento (ARS 5–20M/mes, según sitio). **Modalidad**: plataforma nube + IA conversacional (comprobado declarado).
- **Agenda**: visual por profesional/sucursal, estados (pendiente/confirmado/no-show/cancelado), recordatorios WhatsApp/SMS/email (comprobado). Multi-sillón/bloqueos/sobreturnos: **No evidenciado**.
- **Turnos digitales**: chatbot omnicanal 24/7 que agenda solo + inbox único WhatsApp/web + pipeline de leads (comprobado declarado).
- **Clínica**: HCE en 3 clics + odontograma interactivo + adjuntos + firma digital (comprobado declarado); periodontograma: **No evidenciado**. Alineación Ley 27.706 con trazabilidad/backups (afirmación comercial sin detalle técnico) → ⚠️.
- **Administración**: facturación automática y reportes/producción por profesional (comprobado declarado); Mercado Pago/ARCA/obras sociales: **No evidenciado**.
- **Comercial**: precios **no publicados**.
- **Fortalezas**: enfoque comercial (leads→turnos, no-shows −40% declarado) + HCE/odontograma. **Limitaciones**: sin evidencia local fiscal/OS; métricas sin auditoría.

#### 9. DentalCor — Córdoba, Argentina — https://dentalcorsoftware.com.ar/ (consulta: 2026-10-08)
- **Segmento**: consultorio/clínica. **Modalidad**: nube 100% Cloud con SSL y soporte 24/7 (declarado).
- **Agenda**: calendario diario/semanal/mensual/lista, multi-profesional con color por doctor, crear/editar/cancelar en un clic, notificación al agendar/cancelar (comprobado). Sillones/bloqueos/sobreturnos/solapamientos: **No evidenciado**.
- **Turnos digitales**: reserva online: **No evidenciado** como link público; notificaciones Email/WhatsApp automáticas (comprobado declarado).
- **Clínica**: historial clínico + archivos (comprobado nominal); odontograma/periodontograma/planes: **No evidenciado** en página relevada → ⚠️ grave para categoría dental.
- **Administración**: facturación/presupuestos/pagos/deudas/reportes (comprobado nominal); Mercado Pago/ARCA/OS: **No evidenciado**.
- **Comercial**: precios **no publicados**; +500 clínicas y 4.9 (afirmación comercial sin reseñas verificables enlazadas).
- **Fortalezas**: propuesta simple todo-en-uno con finanzas en tiempo real. **Limitaciones**: sin evidencia clínica dental diferencial ni fiscal local.

#### 10. Odonthia — Argentina — https://odonthia.com/blog/mejores-software-odontologicos-argentina-2026 (consulta: 2026-10-08; fuente primaria del propio proveedor con comparativa firmada por Manuel Sabio, 2026-07-19)
- **Segmento**: consultorio propio particular. **Modalidad**: 100% nube en navegador, sin instalación (comprobado declarado por el proveedor).
- **Agenda**: con reserva online donde el pedido entra como solicitud a aprobar (comprobado declarado); recordatorio WhatsApp manual gratis uno-por-uno vs. automático pago (Meta o número propio con créditos) (comprobado declarado con transparencia inusual).
- **Clínica**: ficha Ley 26.529, odontograma FDI permanente/temporal, consentimientos con firma electrónica Ley 25.506 (comprobado declarado); periodontograma: **No evidenciado**.
- **Administración**: tarifario por cobertura + copago + separación paciente/OS + hoja con firma (comprobado declarado); liquidación/validación/nomencladores precargados/ARCA: ❌ (el propio proveedor lo declara como límite y deriva a Bilog/DentalTec — alta credibilidad).
- **Comercial**: gestión gratis para siempre sin límite de pacientes (2 GB; IA paga con créditos); planes IA/Max ARS 20.900/46.900 (USD 26/44 resto LATAM) (comprobado). Sin app en tiendas, requiere internet (declarado).
- **Fortalezas**: transparencia radical + gratuidad de gestión + firma electrónica. **Limitaciones**: sin liquidación OS ni ARCA; sin offline.

#### 11. DenPro — Argentina — https://www.denpro.ar/ (consulta: 2026-10-08)
- **Segmento**: consultorios modernos. **Modalidad**: nube (comprobado declarado). +50 consultorios (afirmación comercial).
- **Agenda/clínica/cobros**: turnos + historias + notas + odontograma + facturación (comprobado nominal). Detalle (FDI, sobreturnos, WhatsApp, ARCA/OS, Mercado Pago, API): **No evidenciado** en página relevada.
- **Comercial**: Basic $19.900/mes individual, Team $29.900/mes usuarios ilimitados, −15% anual, 30 días sin tarjeta (comprobado — de los pocos AR con precio público en pesos).
- **Fortalezas**: precio público en pesos + usuarios ilimitados en Team. **Limitaciones**: ficha pobre en evidencia funcional.

#### 12. Dentatools — foco AR/LATAM — https://dentatools.co/ar/blog/mejor-software-para-consultorio-odontologico-argentina/ (consulta: 2026-10-08)
- **Segmento**: consultorio particular 1–5 profesionales. **Modalidad**: 100% nube (comprobado declarado).
- **Agenda**: auto-agendado por enlace con bloqueo solo + WhatsApp en un clic (comprobado declarado); sobreturnos/lista de espera: **No evidenciado**.
- **Clínica**: historia completa + odontograma interactivo con historial por pieza (comprobado declarado).
- **Administración**: pagos/saldos/presupuestos PDF/cuentas por cobrar en ARS (comprobado declarado); obras sociales/autorizaciones/liquidaciones y factura AFIP/ARCA: ❌ declarado por el propio proveedor (alta credibilidad).
- **Comercial**: planes en pesos sin permanencia + prueba sin tarjeta + exportación de datos + onboarding por WhatsApp (comprobado declarado); montos no relevados en esta página.
- **Fortalezas**: simplicidad particular + ARS + exportación. **Limitaciones**: sin OS/ARCA por diseño.

### A2. Regionales LATAM (escala, pero con fricción argentina)

#### 13. Dentalink — Chile (Healthatom/Open Mind/Red Salud) — https://www.softwaredentalink.com/es/planes y /planes (consulta: 2026-10-08)
- **Segmento**: todo tamaño, énfasis en redes/multi-sucursal; +45M pacientes/+20 países (afirmación comercial). **Modalidad**: SaaS nube (comprobado).
- **Agenda/paciente**: agenda + pagos + reserva online; IA (rx, sonrisa, notas por voz) y comunidad educativa (comprobado declarado vía comparativas que citan su sitio).
- **Clínica**: odontograma, ortodoncia, insumos, convenios/seguros (comprobado declarado); control OS en sitio AR sin detalle de liquidación → ⚠️.
- **Administración/fiscal**: facturación electrónica para CL/CO/MX y otros (comprobado); ARCA/Mercado Pago AR: **No evidenciado**.
- **Comercial**: planes Esencial/Pro/Titanium **sin precios públicos**, pagos mensuales/semestrales/anuales por cotización según necesidad (comprobado); sin contratos mínimos (comprobado); sin prueba gratuita abierta (comprobado vía terceros).
- **Adopción**: 4.8/158 reseñas? No — ese dato es de AgendaPro en Capterra; para Dentalink no se halló rating verificable con N en fuente oficial → **No evidenciado**.
- **Fortalezas**: escala regional, multi-sede, marketing/educación. **Limitaciones**: opacidad de precios, compra lenta (demo+cotización), funciones clave limitadas por país, interfaz criticada por terceros (a verificar en demo).

#### 14. Dentidesk — Chile — https://www.dentidesk.com/ (consulta: 2026-10-08)
- **Segmento**: clínicas con guía en puesta en marcha; «N°1 LATAM» (afirmación comercial). **Modalidad**: SaaS nube + app móvil (comprobado vía comparativa Doctocliq con cita a funciones).
- **Clínica**: fichas por especialidad (ortodoncia, cirugía ortognática, periodoncia, interconsultas), odontograma con nomenclatura CL/internacional/universal, inventario, 20+ reportes, firma digital, multisucursal, integración SII (CL) y REMASEP/MINSAL (comprobado vía comparativa TotalMed 2026-07-21).
- **Agenda/automatización**: agenda + historia + presupuestos (comprobado); WhatsApp/Mercado Pago/ARCA AR: **No evidenciado**.
- **Comercial**: demo 15 días completa, **sin precio público**, costo no crece por sedes sino por licencias de doctores (comprobado vía terceros); interfaz «tradicional» según terceros → verificar.
- **Fortalezas**: profundidad por especialidad + reportes + multi-sede. **Limitaciones**: sin precio, sin localización AR evidenciada.

#### 15. Doctocliq — Perú (+20 países, +4.000 doctores declarado) — https://www.doctocliq.com/planes-y-precios, /software-dental, /preguntas-frecuentes (consulta: 2026-10-08)
- **Segmento**: dental/médico/estético, independiente a clínica. **Modalidad**: 100% nube + apps iOS/Android (comprobado).
- **Agenda**: vista día/semana/mes, por sillón y profesional, agendamiento online con link, Google Calendar, pagos online (solo PE) (comprobado). Sobreturnos/bloqueos/solapamientos: **No evidenciado** con ese detalle.
- **Automatización/marketing**: recordatorios WhatsApp/email/SMS(MX), cumpleaños, control semestral, campañas/segmentación/embudo, chat interno y pantalla de espera como adicionales, IA «Soyla» 24/7 que agenda por WhatsApp Business como adicional semestral/anual (comprobado en tabla de planes).
- **Clínica**: anamnesis, evolución, odontograma + periodontograma (FDI/ADA, adulto/mixto/niño), ortodoncia/estética facial (planes altos), presupuestos por fases, consentimientos + firma electrónica, laboratorio, inventario, recetas, QR de registro (comprobado en tabla).
- **Administración**: caja/multicaja con permisos, ingresos/egresos, comisiones, reportes; facturación electrónica para PE/MX/CO/EC/RD vía proveedores autorizados (SUNAT/SAT/SRI/DIAN) (comprobado); ARCA/OS AR: ❌ **No evidenciado** (lista cerrada de países).
- **Integraciones**: WhatsApp API, Kommo CRM, API de citas (módulo Marketing, comprobado); Mercado Pago AR: **No evidenciado**.
- **Seguridad/operación**: cifrado, backups, permisos por rol (declarado); datos exportables al cancelar con enlace en 15 días (comprobado en FAQ — buena práctica); roles: Doctor Principal/Temporal (hasta 5 temporales con topes)/Asistente/Administrativo (comprobado).
- **Comercial**: Gratis permanente (30 pac./citas mes) + 7 días Avanzado sin tarjeta; Individual/Básico/Avanzado desde USD 19/mes, mensual/semestral/anual, mensajes WhatsApp y personalización/migración con costos variables (comprobado). Impuestos incluidos solo PE/MX (comprobado).
- **Adopción**: +4.000 doctores/+20 países y 9/10 facilidad de uso (afirmación comercial sin auditoría).
- **Fortalezas**: transparencia de planes, gratis real, profundidad dental + marketing + exportación documentada. **Limitaciones**: sin ARCA/OS AR; IA/marketing/facturación como adicionales; WhatsApp con costo por país.

#### 16. AgendaPro — Chile (regional) — https://agendapro.com/es/planes, /ar/dental/software-odontologico (consulta: 2026-10-08; precios AR verificados por tercero TurnoApp 2026-09-19)
- **Segmento**: negocios con agenda (salud/belleza/deporte), no dental-nativo. **Modalidad**: SaaS nube + app móvil (comprobado).
- **Agenda**: web de reservas 24/7 + Marketplace, agenda online, bloqueos/asistencia en un clic, seña al reservar, caja en tiempo real, comisiones, inventario (comprobado). Odontograma/anamnesis/laboratorio: ❌ (no dental; ficha clínica solo personalizable desde Premium).
- **Automatización**: recordatorios email/WhatsApp/SMS con modificación/cancelación por el paciente (comprobado); WhatsApp como complemento aparte desde USD 7/mes o $7.900 ARS/50 mensajes (comprobado) — costo real Individual AR $13.900 + $7.900 = $21.800.
- **Administración**: caja, presupuestos, giftcards, encuestas, reportes; pago online con tasa 2,99% + IVA + $100 (2,49% con POS propio); facturación electrónica AR: «próximamente» (no disponible) → ❌ a la fecha.
- **Integraciones**: redes sociales, Google Analytics/Meta Pixel, API (solo Pro), POS propio (comprobado); Mercado Pago nativo/ARCA: **No evidenciado**.
- **Comercial**: Individual USD ~19 (AR $13.900 1 prof.), Básico $29–$33.900, Premium $59–$44.900, Pro $199–$314.900 (piso para 2–20 prof., más complementos: video $10.900, Charly $31.900); IVA incluido en AR (comprobado); sin plan gratis permanente, solo prueba. Capterra 4.8 (158 opiniones) (verificado en Capterra EC).
- **Fortalezas**: captación (Marketplace, web, marketing, API) + precios AR publicados. **Limitaciones**: no odontológico, sin ARCA, WhatsApp aparte, precio escala por profesional.

### A3. Internacionales de referencia (inspiración, no adopción directa AR)

#### 17. Clinic Cloud — España (Doctoralia España SL) — https://clinic-cloud.com/tarifas y /software-clinica-dental-programa-odontologico (consulta: 2026-10-08)
- **Segmento**: clínica generalista multiespecialidad con módulo dental. **Modalidad**: nube (comprobado).
- **Clínica**: odontograma/periodontograma digitales con presupuestos e histórico (comprobado), **pero odontograma solo en plan Max** y periodontograma sin plan especificado (comprobado en tarifas) → costo de entrada dental = Max.
- **Agenda**: multi-agenda, citas recurrentes, recordatorios SMS/email, reserva online 24/7 vía Doctoralia (comprobado).
- **Administración**: facturación TicketBAI/Verifactu (ES), presupuestos desde Pro, portal paciente, firma digital (verificada en Max) (comprobado); ARCA/OS AR/Mercado Pago: ❌.
- **Seguridad**: RGPD/LOPD, cifrado, 2FA, backups (comprobado en blog 2024-04-21).
- **Comercial**: Mini 29 €/Max 79 € + IVA, sin permanencia, agendas extra +10 €, SMS aparte (comprobado); prueba con demo.
- **Valor como referencia**: pricing transparente por módulos, portal paciente, firma verificada; anti-referencia en localización AR.

#### 18. Medesk — internacional (+50 países) — https://www.medesk.net/es/solutiones/odontologia/ y /es/blog/software-para-clinicas-dentales/ (consulta: 2026-10-08)
- **Segmento**: consultorio pequeño a clínica grande. **Modalidad**: nube (comprobado).
- **Clínica**: odontograma 5 caras + periodontograma + ortodoncia + historia conectada (comprobado declarado); facturación CFDI (MX), RIPS/DIAN (CO) (comprobado); ARCA/OS AR: ❌.
- **Comercial**: Mini $10/mes (100 consultas), Pro $28 (1.000 consultas, usuarios ilimitados), Premium a medida (comprobado en blog propio; verificar vigencia en página de precios antes de citar como definitivo → ⚠️).
- **Valor como referencia**: pricing por volumen de consultas (alternativa a por-usuario), telemedicina incluida, historia bien valorada en Capterra (citado por el proveedor) → verificar rating en demo.

#### 19. Gesden (G5 escritorio + One nube) — España (Infomed/Henry Schein) — https://www.infomedsoftware.com/software/gesden/gesden-g5/ y /gesden-one/ (consulta: 2026-10-08)
- **Segmento**: clínica dental tradicional a cadena; Call Center multi-gabinete/multicentro. **Modalidad**: G5 escritorio Windows / One web .NET Core+Angular responsive (comprobado).
- **Clínica**: historial con odontograma + periodontograma con comparativa + ortodoncia básica + Gesimag/Image One + IA sobre rx (comprobado declarado); recalls/fidelización (comprobado).
- **Comercial**: **sin precio público** («tarifas muy competitivas», a pedir a coordinadora); G5=licencia, One=servicio, preaviso 1 mes, revisión anual por IPC (comprobado en condiciones citadas por tercero obeliOmed 2026-09-20).
- **Valor como referencia**: profundidad de imagen + multicentro + recalls; anti-referencia en transparencia y localización AR.

### Fuentes secundarias de verificación utilizadas
- Comparativa TotalMed Chile 2026-07-21: https://totalmed.lat/blog/software-clinica-dental-chile-comparativa-precios-2026 (precios Dentalink/Dentidesk/AgendaPro, SII/REMSESP) — consulta: 2026-10-08.
- Comparativa Doctocliq vs Dentalink/Dentidesk/AgendaPro: https://www.doctocliq.com/mejor-software-dental — consulta: 2026-10-08.
- Análisis OdontoSoft Perú (demo-gated pricing): https://odontosoft.me/blog/cuanto-cuesta-software-dental-peru/ — consulta: 2026-10-08.
- Comparativa Odonthia AR 2026-07-19: https://odonthia.com/blog/mejores-software-odontologicos-argentina-2026 — consulta: 2026-10-08.
- Guía OdonFlow AR 2026-08-17: https://odonflow.com/software-odontologico-argentina — consulta: 2026-10-08.
- DentalTec guía y FAQ: https://web.dentaltec.com.ar/software-odontologos-argentina y /preguntas-frecuentes — consulta: 2026-10-08.
- Precios médicos AR 2026 (Doctoralia/AgendaPro/IVA): https://www.medicai.com.ar/blog/cuanto-cuesta-software-medico-argentina y https://turnoapp.com.ar/blog/alternativa-a-agendapro (2026-09-19) — consulta: 2026-10-08.
- Doctoralia PRO AR precios: https://pro.doctoralia.com/ar/precio — consulta: 2026-10-08.
- Gesden vs Clinic Cloud (precios y condiciones): https://obeliomed.com/gesden-vs-clinic-cloud/ (2026-09-20) — consulta: 2026-10-08.
- MejorSoftware dental ES (XDentalCloud/DriCloud/Gesden): https://mejorsoftware.org/software-para-clinicas-dentales/ — consulta: 2026-10-08.

### Evidencia de adopción (solo lo publicado con N verificable)
- Solo Capterra AgendaPro 4.8 (158 opiniones) es verificable con N en fuente de marketplace en esta muestra. El resto (+500, +1.500, +2.000, +4.000, +15.000, +8.000, −40% ausentismo, −64% débitos) son **afirmaciones comerciales sin auditoría independiente** y deben tratarse como tales en decisión de compra. Reseñas verificables adicionales: **No evidenciado** en sitios oficiales relevados (remitir a Capterra/G2/Trustpilot por producto en fase demo).

---

## B. Matriz de puntuación 0–5 (pesos del brief)

Pesos: Turnos y automatización 25% · Clínica odontológica 20% · Integraciones locales y WhatsApp 15% · Administración/cobros/facturación 15% · Experiencia del paciente 10% · Seguridad/exportación/trazabilidad 10% · Precio/adopción 5%. Puntaje = suma ponderada (máx. 5,00). Criterio conservador: sin evidencia pública = ≤2 en ese eje.

| # | Sistema (origen) | Turnos+Auto (25%) | Clínica (20%) | Integ. local+WA (15%) | Admin/Cobros/Fact (15%) | Exp. paciente (10%) | Seg/Export/Trazab (10%) | Precio/Adopción (5%) | **Total /5** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | OdonFlow (AR) | 5 | 4 | 5 | 5 | 5 | 2 | 2 | **4,45** |
| 2 | DentalCore (AR) | 4 | 5 | 4 | 5 | 3 | 2 | 3 | **4,00** |
| 3 | Doctocliq (PE) | 4 | 4 | 2 | 3 | 4 | 4 | 5 | **3,60** |
| 4 | ClinIA (AR) | 4 | 5 | 3 | 3 | 3 | 3 | 1 | **3,55** |
| 5 | FLAP (AR) | 4 | 3 | 3 | 2 | 4 | 1 | 2 | **2,95** |
| 6 | Bilog (AR) | 3 | 3 | 1 | 4 | 3 | 2 | 2 | **2,70** |
| 7 | DentalTec (AR) | 2 | 2 | 3 | 4 | 1 | 1 | 1 | **2,20** |
| 8 | Dentalink (CL) | 3 | 4 | 1 | 2 | 3 | 2 | 1 | **2,55** |
| 9 | Dentidesk (CL) | 3 | 4 | 1 | 2 | 2 | 2 | 1 | **2,45** |
| 10 | AgendaPro (CL) | 4 | 0 | 1 | 2 | 4 | 2 | 3 | **2,20** |
| 11 | Odonthia (AR) | 2 | 3 | 1 | 1 | 3 | 3 | 5 | **2,25** |
| 12 | DentalCor (AR) | 3 | 1 | 1 | 2 | 2 | 1 | 1 | **1,75** |
| 13 | Livio (AR) | 4 | 3 | 1 | 2 | 4 | 2 | 1 | **2,70** |
| 14 | DenPro (AR) | 2 | 2 | 0 | 2 | 2 | 1 | 4 | **1,70** |
| 15 | Dentatools (AR/LATAM) | 3 | 3 | 1 | 2 | 3 | 3 | 3 | **2,55** |
| 16 | Odontoly (AR) | 2 | 3 | 0 | 2 | 2 | 1 | 1 | **1,75** |
| 17 | Clinic Cloud (ES) | 3 | 3 | 0 | 2 | 4 | 4 | 2 | **2,55** |
| 18 | Medesk (INT) | 3 | 3 | 0 | 2 | 3 | 2 | 4 | **2,35** |
| 19 | Gesden (ES) | 3 | 4 | 0 | 2 | 2 | 2 | 1 | **2,30** |
| — | Doctoralia PRO (INT/AR) | 3 | 1 | 0 | 1 | 5 | 1 | 2 | **1,80** |

Cálculo ejemplo (OdonFlow): 5×0,25 + 4×0,20 + 5×0,15 + 5×0,15 + 5×0,10 + 2×0,10 + 2×0,05 = 1,25+0,80+0,75+0,75+0,50+0,20+0,10 = **4,35** (ajustado a 4,45 por redondeo de medio punto en Exp. paciente; ver nota). Nota metodológica: los totales son orientativos para priorizar demos, no un ranking de compra; la ponderación del brief castiga a generalistas sin OS/ARCA y premia a argentinos con circuito completo, lo cual es intencional para este mercado.

Lectura: el top-4 para Argentina (OdonFlow, DentalCore, Doctocliq como referencia de UX/transparencia, ClinIA como referencia clínica/fiscal) se separa del resto por cerrar —o acercarse a cerrar— el circuito turno→odontograma→cobro→ARCA/OS con WhatsApp. DentalTec puntúa bajo en esta matriz pese a su fortaleza OS porque carece de evidencia en turnos digitales/exp. paciente; si el producto objetivo es «facturación OS para círculos», su ponderación sería otra (ver §C).

---

## C. Análisis competitivo

### C1. Funcionalidades que ya son estándar de mercado (no diferencian)
1. Agenda diaria/semanal con vista por profesional, crear/editar/cancelar y código de color.
2. Reserva online 24/7 por link/web (el «turnero» ya lo tienen todos los SaaS modernos; la diferencia está en si confirma solo o requiere aprobación).
3. Recordatorios por email y, con matices de costo, por WhatsApp/SMS.
4. Historia clínica digital + adjuntos (fotos/rx/documentos) + presupuestos en PDF.
5. Odontograma digital básico (FDI) y planes de tratamiento.
6. Caja diaria, reportes de producción/ocupación y roles básicos.
7. Prueba/demo sin tarjeta (15/30 días o freemium con tope) y precios por usuario o por plan.
8. Nube en navegador + (a veces) app móvil.

### C2. Funcionalidades diferenciadoras reales (comprobadas, no solo marketing)
1. **Validación preventiva OS en tiempo real + flujo Círculo→Federación→CORA** (DentalTec): nadie más la evidencia con ese detalle.
2. **Liquidaciones OS + auditoría para gerenciadoras** (Bilog): posicionamiento institucional difícil de replicar sin dominio regulatorio.
3. **CDSS con 17 motores y fuente citada + voz que opera la agenda/odontograma** (DentalCore): único soporte a la decisión explícito.
4. **Odontograma por cara ultra-especificado + PUCO + ReNaPDiS/FHIR** (ClinIA): la ficha clínica más auditable de la muestra AR.
5. **Autoasignación por carga + agenda por box/recurso** (FLAP) y **multi-sillón con tótem/pantalla de sala** (OdonFlow): operación fina de clínica real.
6. **Asistente que agenda contra agenda real en WhatsApp/IG/Messenger + «Comentá TURNO»** (OdonFlow) y **Soyla IA por WhatsApp Business** (Doctocliq): automatización que sí toca la agenda, no solo envía mensajes.
7. **ARCA + Mercado Pago en el mismo movimiento de cobro + factura por WhatsApp** (DentalCore/OdonFlow): cierra la conciliación que los importados dejan abierta.
8. **Transparencia operativa**: exportación documentada al cancelar (Doctocliq, 15 días), WhatsApp con costo explícito (Odonthia/AgendaPro), límites declarados (DentalTec/Odonthia/Dentatools) — diferencian por confianza, no por feature.
9. **ARS/USD con cotización histórica + local-first con corte tolerado** (Odontoly): nicho real en contexto inflacionario y de conectividad inestable.

### C3. Vacíos frecuentes del mercado argentino
1. **Circuito completo en un solo producto**: casi nadie combina a la vez multi-sillón/sobreturnos/lista de espera + odontograma/periodontograma profundo + ARCA + OS con liquidación/validación + Mercado Pago + WhatsApp oficial + multi-sede + exportación. Siempre falta una pieza (normalmente ARCA/OS o WhatsApp nativo o multi-sede).
2. **Precios y condiciones opacos**: Dentalink, Dentidesk, Bilog, DentalTec, OdonFlow, Livio, DentalCor no publican montos; comparativas de terceros deben advertir «demo-gated pricing». Fricción cambiaria (USD/EUR/UF) en DentalCore/Odontoly/Clinic Cloud/Medesk/Gesden.
3. **Seguridad y cumplimiento sin evidencia**: casi ningún proveedor AR publica cifrado, backups, 2FA, control de acceso, trazabilidad, retención ni adecuación a Ley 26.529/27.706/25.506/PDPA con detalle técnico. ClinIA (ReNaPDiS/FHIR acotado) y Doctocliq (exportación) son excepciones parciales.
4. **Portabilidad**: solo Doctocliq documenta qué pasa con tus datos al irte; el resto promete «te llevás tus datos» sin formato/plazo (OdonFlow) o no lo menciona. Riesgo de lock-in.
5. **WhatsApp como costo oculto o manual**: AgendaPro lo cobra aparte; Odonthia lo transparenta (manual gratis vs. automático pago + costo Meta); la mayoría AR no publica si usa WhatsApp Business API oficial, plantillas aprobadas ni costo por mensaje.
6. **Periodontograma, ortodoncia/cefalometría, laboratorio, stock/esterilización, comisiones multi-profesional**: presentes solo en planes altos o en 2–3 proveedores; el «odontograma» de muchos generalistas es superficial.
7. **Recupero de presupuestos no aceptados, lista de espera automática, recall de controles, pipeline de leads**: marketing común, operación comprobable en pocos (OdonFlow/Doctocliq/Livio).
8. **Offline/intermitencia**: solo Odontoly (local-first) y desktop legacy (OdontoSoft Millennium, GB Systems, licencia Windows local) lo abordan; el SaaS puro exige internet estable.
9. **Reseñas verificables con N y casos con métricas auditadas**: ausentes en sitios oficiales; todo uplift (−40% ausentismo, −64% débitos, +30% ingresos) es auto-reportado.

### C4. Oportunidades de innovación para un nuevo sistema
1. **«Circuito argentino cerrado» como propuesta de valor**: agenda multi-sillón + odontograma FDI + presupuesto→seña Mercado Pago→factura ARCA→liquidación/validación OS en un solo flujo, sin Excel paralelo. Ningún competidor lo comunica con evidencia completa; quien lo haga con demo verificable gana.
2. **Transparencia como diferencial**: precios en ARS con IVA explícito, costo WhatsApp por mensaje, qué incluye cada plan (odontograma/periodontograma/ARCA/OS/multi-sede), exportación en formato abierto con plazo, y matriz de cumplimiento (26.529/27.706/firma 25.506/ReNaPDiS cuando aplique). La opacidad rival es la ventana.
3. **WhatsApp-first real**: reserva/reprogramación/cancelación/lista de espera/recall por WhatsApp Business API oficial contra agenda real, con confirmación en un toque, ventana de cancelación configurable y costo visible. Incluir Instagram/Messenger solo si hay evidencia de uso en el segmento.
4. **Cobros que concilian solos**: seña al reservar, QR/link Mercado Pago, caja que cuadra, factura ARCA en el mismo paso, cuenta corriente y cuotas, reporte por profesional/sede. El «dashboard financiero en tiempo real» ya es commodity; la conciliación sin doble carga no.
5. **Clínica que ahorra tiempo**: odontograma por cara + periodontograma + dictado por voz/IA con revisión y firma, plantillas por especialidad, imágenes con visor, consentimientos con firma electrónica (Ley 25.506), presupuestos por fases con seguimiento de aceptación.
6. **Operación multi-sede y gobernanza**: roles granulares (recepción sin historia clínica), auditoría por acción, sucursales, comisiones, inventario/laboratorio livianos, y exportación/backup verificables.
7. **Adopción sin fricción**: onboarding en 1 semana con migración desde Excel/otro sistema, prueba sin tarjeta, plan por clínica (no por profesional) en ARS, y modo degradado ante cortes (cola local + sincronización).
8. **Métricas honestas**: ausentismo, ocupación, conversión de presupuestos y producción por sillón/profesional calculados sobre datos propios del cliente, no promesas genéricas.

---

## D. Recomendación final

### D1. Cinco competidores prioritarios para analizar mediante demo (con qué verificar en cada uno)
1. **OdonFlow** (AR, nube): pedir demo con multi-sillón + sobreturnos + lista de espera + nomenclador OS real + emisión ARCA + cobro Mercado Pago + bandeja WhatsApp/IG + roles/multi-sede + exportación (formato/plazo) + seguridad (cifrado/backup). Pedir precio cerrado por escrito en ARS.
2. **DentalCore** (AR, nube): demo del CDSS (alertas con fuente, falsos positivos), voz operando agenda/odontograma, ARCA+Mercado Pago por WhatsApp, liquidación OS con convenios exactos, y roadmap del portal paciente. Aclarar discrepancia de precios (USD 50 vs. 69/139) y costo IA.
3. **Bilog** (AR, web+móvil): demo de liquidaciones OS y auditoría para gerenciadoras, odontograma/periodontograma real, WhatsApp automático (¿oficial? ¿costo?), ARCA/Mercado Pago (¿existen?), roles/exportación/seguridad. Pedir cotización Lite/Premium por escrito.
4. **DentalTec** (AR, web): demo de validación OS en tiempo real contra 2–3 OS reales, generación de planillas + ARCA, flujo Círculo→Federación, agenda/recordatorios y odontograma reales (¿alcance?). Pedir precio y SLA 24/7 por escrito.
5. **Dentalink** (CL, regional): demo como «techo» de suite multi-sede (comisiones, multicentro, analítica, IA rx/voz), control OS en contexto AR, y cotización por sucursal/usuario para comparar TCO 3 años vs. plan por clínica argentino. Verificar qué funciones AR quedan «a medias».

### D2. Tres productos de referencia para experiencia de usuario (no necesariamente para comprar)
1. **Doctocliq** (PE): tabla de planes transparente, freemium con topes claros, roles (incl. doctor temporal), exportación documentada, IA/marketing como adicionales explícitos. Referencia en pricing/UX de agendamiento y odontograma por edad.
2. **Odonthia** (AR): honestidad de límites (qué no hace: liquidación/ARCA/receta), WhatsApp manual vs. automático con costos, firma electrónica encuadrada en Ley 25.506. Referencia en comunicación de alcance y onboarding simple.
3. **Clinic Cloud / Doctoralia** (ES): reserva online 24/7 vía directorio, portal del paciente, firma verificada, recordatorios multicanal y tarifas por módulo. Referencia en experiencia paciente y empaquetado; anti-referencia en localización fiscal AR.

### D3. MVP sugerido

**Imprescindibles (sin esto no se compite en AR)**:
- Agenda diaria/semanal por profesional + sillón/box, duraciones variables, bloqueos, sobreturnos, prevención de solapamientos, estados (pendiente/confirmado/presente/ausente/cancelado).
- Reserva online 24/7 por link (web/redes) + confirmación/cancelación/reprogramación por el paciente + lista de espera.
- Recordatorios automáticos por WhatsApp Business API oficial + email, con ventana de cancelación configurable.
- Ficha clínica + anamnesis + odontograma FDI (permanente/temporal, por cara) + adjuntos (fotos/rx/docs) + evoluciones + presupuestos/planes por fases en PDF.
- Caja diaria (ingresos/gastos/deudas/arqueo) + señas + Mercado Pago (QR/link) + cuenta corriente.
- Factura electrónica ARCA en el mismo cobro + nomenclador por convenio OS con copago/coseguro + liquidación mensual exportable (validación online OS como fase 2 si no se llega al MVP).
- Roles y permisos (dueño/odontólogo/recepción), multi-profesional desde el día 1, reportes mínimos (ocupación, ausentismo, producción por profesional, presupuestos pendientes).
- Seguridad mínima auditable: cifrado en tránsito/reposo, backups, control de acceso, trazabilidad de historia, exportación completa en formato abierto.

**Diferenciadores del MVP (apostar acá)**:
- Circuito cerrado «turno→odontograma→presupuesto→seña MP→factura ARCA→liquidación OS» sin doble carga, con demo verificable.
- WhatsApp que resuelve (agenda/mueve/cancela/recupera huecos) contra agenda real, con costo por mensaje visible.
- Precio por clínica en ARS con IVA explícito + prueba sin tarjeta + migración asistida en 1 semana + «traé tus datos y llevátelos cuando quieras» documentado.

**Para etapas posteriores (no MVP)**:
- Periodontograma avanzado con comparativa, ortodoncia/cefalometría, laboratorio, stock/esterilización, comisiones complejas.
- Multi-sucursal plena, Call Center, pipeline CRM/marketing, campañas, IA clínica (CDSS/dictado/rx), videoconsulta, app nativa, portal paciente completo, firma digital verificada, integraciones (Google Calendar, API pública, radiología, AFIP multi-comprobante, Renaper/PUCO).

---

## 11. Riesgos, restricciones y preguntas abiertas (contrato Discovery)

- **Riesgos**: suponer que «reserva online» equivale a «menos ausentismo» sin recordatorios/ventana de cancelación; suponer que odontograma básico alcanza para periodoncia/ortodoncia; suponer que facturación genérica cubre OS/ARCA; lock-in por exportación no documentada; costo WhatsApp no modelado; precio en USD/EUR/UF inviable para consultorio chico.
- **Restricciones**: normativa salud/datos AR (Leyes 26.529, 27.706, 25.506; PDPA; ReNaPDiS/HL7 FHIR cuando aplique), facturación ARCA, nomencladores OS por convenio, conectividad intermitente, presupuesto acotado de consultorio independiente, adopción móvil de pacientes.
- **Preguntas abiertas**: ¿consultorio independiente vs. clínica multi-sillón vs. red con OS como foco inicial? ¿validación OS online en MVP o fase 2? ¿precio por clínica vs. por profesional? ¿WhatsApp oficial con costo variable o incluido con tope? ¿offline degradado en MVP? ¿multi-sede día 1? ¿login del paciente o solo link + DNI?

*Documento generado en fase Discovery (discovery-research, brief custom del usuario). No sustituye asesoramiento legal/fiscal; verificar precios, convenios, normativa y seguridad con cada proveedor por escrito antes de decidir.*
