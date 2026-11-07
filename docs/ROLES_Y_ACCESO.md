# Guía de Roles, Credenciales y Acceso al Sistema

Este documento describe cómo ingresar al **Sistema de Turnos Odontológico**, cuáles son los roles disponibles, sus credenciales predeterminadas para desarrollo/demo y qué permisos tiene cada uno.

---

## 1. Arquitectura de Usuarios y Roles

El sistema implementa un modelo de seguridad estricto (RBAC) definido en **C-03**:
- **Personal de la clínica**: opera mediante inicio de sesión con correo y contraseña. Utiliza tokens JWT de acceso corto (15 minutos) almacenados en memoria y tokens de refresco rotativos en cookies `HttpOnly` seguras.
- **Pacientes**: **no tienen cuenta ni contraseña**. Operan de forma anónima mediante el catálogo público de reserva online (`/b/:slug`) o a través de enlaces con *capability token* de un solo turno (`/g/:token`) enviados por WhatsApp o email.

### Matriz de Roles del Personal

| Rol | Propósito principal | Alcance en la Agenda | Rutas exclusivas |
|---|---|---|---|
| **`admin`** | Dirección y administración de la clínica | Ve y gestiona la agenda completa de todos los profesionales y sillones | `/admin/profesionales`, `/admin/sillones`, `/admin/horarios`, `/admin/reportes`, exportación completa de datos |
| **`recepcion`** | Atención, admisión y gestión diaria | Ve y opera todos los turnos (altas, sobreturnos, cancelaciones, asistencia) | `/`, `/bloqueos`, `/politicas`, `/pacientes/fusionar` |
| **`odontologo`** | Profesional de la salud | **Solo ve sus propios turnos**. No ve datos de contacto de pacientes ni turnos ajenos | Vista restringida en `/`, marca de asistencia de sus pacientes |

---

## 2. Credenciales de Prueba (Entorno de Desarrollo)

Al levantar el proyecto en desarrollo (vía `.\dev.ps1` o ejecutando el seed), se siembran automáticamente los siguientes usuarios sintéticos (regla 13: sin datos reales):

| Rol | Correo Electrónico | Contraseña Predeterminada | Primer Ingreso |
|---|---|---|---|
| **Admin** | `admin@example.com` | `adminadminadmin` | Solicita cambio de contraseña obligatorio (`/cambiar-clave`) |
| **Recepción** | `recepcion@example.com` | `cambiar-esta-clave-provisoria` | Solicita cambio de contraseña obligatorio (`/cambiar-clave`) |
| **Odontólogo** | `odontologo@example.com` | `cambiar-esta-clave-provisoria` | Solicita cambio de contraseña obligatorio (`/cambiar-clave`) |

> [!NOTE]
> Las contraseñas provisorias salen de `SEED_ADMIN_PASSWORD`, `SEED_RECEPCION_PASSWORD` y `SEED_ODONTOLOGO_PASSWORD` del archivo `.env` (si las dos últimas faltan, se usa la del admin). El seed solo las aplica al **crear** cada usuario: cambiar el `.env` no modifica usuarios que ya existen en la base.

---

## 3. Cómo Ingresar al Proyecto

### Paso 1: Levantar el proyecto
Si estás usando Docker:
```powershell
.\dev.ps1
```
O bien:
```bash
docker compose up -d
```
*(Si corrés el backend de forma local fuera de Docker, podés sembrar los usuarios ejecutando `cd backend && python -m app.seed` con `SEED_DEMO_USERS=true` en `.env`).*

### Paso 2: Abrir la pantalla de Login
Navegá en tu navegador a:
- **Frontend (Vite dev)**: [http://localhost:5174/login](http://localhost:5174/login)
- **Frontend (Nginx prod)**: [http://localhost:5173/login](http://localhost:5173/login)

---

## 4. Experiencia por Cada Rol

### A. Ingresando como Administrador (`admin@example.com`)
1. Ingresá `admin@example.com` y la contraseña `cambiar-esta-clave-provisoria`.
2. Como tiene la bandera de seguridad `must_change_password`, el sistema te redirigirá automáticamente a `/cambiar-clave`.
3. Ingresá una nueva contraseña (por ejemplo `AdminDemo123!`) y confirmala.
4. **Lo que podés hacer**:
   - Visualizar y operar toda la agenda (día y semana).
   - Crear y gestionar **Profesionales** (`/admin/profesionales`).
   - Crear y gestionar **Sillones** (`/admin/sillones`).
   - Definir **Reglas de Horarios y Disponibilidad** (`/admin/horarios`).
   - Consultar **Reportes de Ocupación, Ausentismo y Cancelaciones** (`/admin/reportes`).
   - Ver el registro de **Auditoría Global** y descargar la **Exportación Completa de Datos (ZIP)**.
   - Ajustar las **Políticas de la Clínica** (tope de sobreturnos, ventana de cancelación, etc.).

### B. Ingresando como Recepción (`recepcion@example.com`)
1. Ingresá `recepcion@example.com` y la contraseña `cambiar-esta-clave-provisoria`.
2. En el primer ingreso el sistema te redirige a `/cambiar-clave`; después de elegir una contraseña nueva accedés a la **Agenda de Recepción** (`/`).
3. **Lo que podés hacer**:
   - Dar de alta turnos normales y sobreturnos justificados.
   - Registrar la asistencia del día: **Presente**, **Ausente** o **No asistió (No-show)**.
   - Reprogramar y cancelar turnos con motivo obligatorio.
   - Fusionar fichas de pacientes duplicados (`/pacientes/fusionar`).
   - Cargar bloqueos de agenda por vacaciones, feriados o mantenimiento (`/bloqueos`).
   - Si intentás entrar a `/admin/reportes` o a la configuración de profesionales, el sistema te mostrará una advertencia de permisos y te impedirá el acceso.

### C. Ingresando como Odontólogo (`odontologo@example.com`)
1. Ingresá `odontologo@example.com` y la contraseña `cambiar-esta-clave-provisoria`.
2. En el primer ingreso el sistema te redirige a `/cambiar-clave`; después de elegir una contraseña nueva accedés a la **Agenda Filtrada** (`/`).
3. **Lo que podés hacer**:
   - Este usuario está vinculado automáticamente en la base de datos al *Profesional Ficticio de Ejemplo*.
   - **Aislamiento en DB**: La base de datos solo le devuelve sus propios turnos. No puede ver la agenda de otros profesionales de la clínica.
   - **Privacidad de datos**: Por secreto profesional y privacidad (regla 13 y RBAC), no se le muestran teléfonos ni correos de los pacientes.
   - Puede marcar a sus pacientes como **Presente** o **No asistió** únicamente durante el día del turno.
   - No tiene permisos para crear turnos ni acceder a pantallas administrativas.

---

## 5. Acceso del Paciente (Sin Usuario ni Clave)

El paciente no inicia sesión en `/login`:

1. **Reserva online de turnos (24/7)**:
   - URL: [http://localhost:5174/b/clinica-demo](http://localhost:5174/b/clinica-demo)
   - Permite elegir profesional, fecha y hora libre en un flujo mobile-first de 4 pasos.
2. **Gestión de su turno confirmado**:
   - URL con token seguro: `http://localhost:5174/g/<token>`
   - Al reservar, el paciente recibe un enlace directo para **Confirmar**, **Cancelar** (sujeto a la ventana de 24 hs de la clínica) o **Reprogramar** su turno sin necesidad de recordar claves ni registrarse.

---

## 6. Matriz de Permisos por Ruta en la SPA

| Ruta | Nombre de Pantalla | `admin` | `recepcion` | `odontologo` | Paciente anónimo |
|---|---|:---:|:---:|:---:|:---:|
| `/b/:slug` | Reserva pública | ❌ | ❌ | ❌ | ✅ |
| `/g/:token` | Gestión por token | ❌ | ❌ | ❌ | ✅ |
| `/login` | Iniciar Sesión | ✅ | ✅ | ✅ | ❌ |
| `/` | Agenda principal | ✅ (completa) | ✅ (completa) | ✅ (solo propios) | ❌ |
| `/bloqueos` | Bloqueos de agenda | ✅ | ✅ | ❌ (solo lectura) | ❌ |
| `/politicas` | Políticas de clínica | ✅ | ✅ | ❌ | ❌ |
| `/pacientes/fusionar` | Fusión de pacientes | ✅ | ✅ | ❌ | ❌ |
| `/admin/profesionales` | ABM Profesionales | ✅ | ❌ | ❌ | ❌ |
| `/admin/sillones` | ABM Sillones | ✅ | ❌ | ❌ | ❌ |
| `/admin/horarios` | Plantilla semanal | ✅ | ❌ | ❌ | ❌ |
| `/admin/reportes` | Reportes y Auditoría | ✅ | ❌ | ❌ | ❌ |
