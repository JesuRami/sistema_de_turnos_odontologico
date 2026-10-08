# Sistema de Turnos Odontológico — Base de Conocimiento

Base de conocimiento generada en modo interactivo (Q&A estratégico validado, sin preguntas pendientes al equipo salvo las registradas en `10`). Alcance: **MVP agenda-first v1.0** — multi-chair agenda + reserva online 24/7 + recordatorios WhatsApp. Clínica, cobros, ARCA y obras sociales son fases posteriores.

## Índice de Archivos

| Archivo | Contenido |
|---------|-----------|
| [01_vision_y_objetivos.md](01_vision_y_objetivos.md) | Propósito, objetivos por actor, alcance v1.0, fuera de alcance, métricas de éxito |
| [02_descripcion_general.md](02_descripcion_general.md) | Stack (Python/FastAPI + SQLAlchemy + Postgres + Redis + React+TS+Vite, Docker Compose), arquitectura, integraciones, API REST |
| [03_actores_y_roles.md](03_actores_y_roles.md) | 4 actores, matriz RBAC simple, rutas públicas |
| [04_modelo_de_datos.md](04_modelo_de_datos.md) | Dominios, ERD, 12 entidades (appointment con exclusion constraint), seed |
| [05_reglas_de_negocio.md](05_reglas_de_negocio.md) | Reglas RN-AG/SB/BL/LE/CX/ST/ON/WA/GL (solapamientos, sobreturnos, bloqueos, lista de espera, ventanas) |
| [06_funcionalidades.md](06_funcionalidades.md) | 6 épicas, 16 historias US-001…US-051 (solo MVP agenda) |
| [07_flujos_principales.md](07_flujos_principales.md) | Reserva online, gestión por token, motor de recordatorios, día de recepción, lista de espera |
| [08_arquitectura_propuesta.md](08_arquitectura_propuesta.md) | Patrones, directorios, seguridad, variables de entorno |
| [09_decisiones_y_supuestos.md](09_decisiones_y_supuestos.md) | 7 decisiones (DD-01…DD-07) + 7 supuestos (SU-01…SU-07) |
| [10_preguntas_abiertas.md](10_preguntas_abiertas.md) | 2 inconsistencias + 11 preguntas priorizadas + registro de fases posteriores |
| [11_whatsapp_y_recordatorios.md](11_whatsapp_y_recordatorios.md) | EXTRA: canal WhatsApp Cloud API, 6 plantillas, reminder engine, costos y riesgos |

## Quick Start para Desarrolladores

1. Entender el dominio → [01](01_vision_y_objetivos.md), [03](03_actores_y_roles.md)
2. Entender los datos → [04](04_modelo_de_datos.md)
3. Entender las reglas → [05](05_reglas_de_negocio.md)
4. Entender la arquitectura → [02](02_descripcion_general.md), [08](08_arquitectura_propuesta.md)
5. Implementar → [07](07_flujos_principales.md), [06](06_funcionalidades.md)
6. Antes de codificar → [10](10_preguntas_abiertas.md)

## Resumen Ejecutivo

Sistema web (Python/FastAPI + SQLAlchemy + PostgreSQL + Redis + React+TS+Vite, Docker Compose) para clínicas odontológicas argentinas que en v1.0 resuelve la agenda confiable: cero solapamientos garantizados en base de datos, reserva online sin cuenta, recordatorios WhatsApp que reducen ausentismo y lista de espera que llena cancelaciones. Historia clínica, cobros, ARCA y obras sociales quedan para fases posteriores sobre los mismos `patient_id`/`appointment_id` estables.
