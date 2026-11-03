# Spec Delta — web/staff-session

## Purpose

Define cómo el personal de la clínica inicia, mantiene y cierra su sesión en la
SPA, cómo se renueva el acceso sin romper la rotación estricta del refresh y qué
rutas ve cada rol.

## ADDED Requirements

### Requirement: Login del personal desde la SPA

La SPA SHALL ofrecer un formulario de login por email y contraseña. Ante
credenciales inválidas SHALL mostrar un único mensaje genérico, sin indicar si
falló el email o la contraseña. Ante `429` SHALL indicar cuándo reintentar.

#### Scenario: Login exitoso

- **WHEN** un recepcionista ficticio ingresa credenciales válidas
- **THEN** la SPA lo lleva a la agenda del día de su clínica

#### Scenario: Credenciales inválidas

- **WHEN** la API responde `401 invalid_credentials`
- **THEN** la SPA muestra "Email o contraseña incorrectos" y no revela cuál falló

#### Scenario: Demasiados intentos

- **WHEN** la API responde `429` con `Retry-After: 30`
- **THEN** la SPA muestra que se puede reintentar en 30 segundos y deshabilita el envío

### Requirement: El access token vive solo en memoria

La SPA SHALL guardar el access token únicamente en memoria. SHALL NOT escribirlo
en `localStorage`, `sessionStorage`, cookies accesibles por JS ni en la URL. Al
recargar la página, la sesión SHALL recuperarse con el refresh de la cookie
HttpOnly.

#### Scenario: Recarga de la página

- **WHEN** el usuario recarga con una cookie de refresh vigente
- **THEN** la SPA obtiene un access nuevo vía refresh y muestra la misma ruta

#### Scenario: Nada persistido en el navegador

- **WHEN** el usuario inició sesión
- **THEN** ni `localStorage` ni `sessionStorage` contienen el access token

### Requirement: Renovación single-flight entre pestañas

Cuando un request recibe `401` por access vencido, la SPA SHALL renovar el
access con un único refresh en vuelo compartido por todos los requests y por
todas las pestañas del mismo origen, y SHALL reintentar cada request una sola
vez. Si el refresh falla con `401`, SHALL cerrar la sesión local en todas las
pestañas y volver al login.

#### Scenario: Varios requests vencidos a la vez

- **WHEN** tres requests reciben `401 token_expired` al mismo tiempo
- **THEN** se envía un solo `POST /api/auth/refresh` y los tres se reintentan con el access nuevo

#### Scenario: Dos pestañas abiertas

- **WHEN** dos pestañas necesitan renovar el access al mismo tiempo
- **THEN** solo una envía el refresh y la otra recibe el access resultante

#### Scenario: Refresh rechazado

- **WHEN** el refresh responde `401 refresh_reuse`
- **THEN** todas las pestañas cierran la sesión local y muestran el login

### Requirement: Cambio de contraseña obligatorio

Si el usuario tiene `must_change_password=true`, la SPA SHALL llevarlo a la
pantalla de cambio de contraseña y SHALL NOT mostrar otra ruta protegida hasta
completarlo. La pantalla SHALL mostrar los errores de política que devuelva la
API.

#### Scenario: Primer ingreso con clave provisoria

- **WHEN** un admin ficticio entra con una contraseña provisoria
- **THEN** ve la pantalla de cambio de contraseña y no la agenda

#### Scenario: Contraseña nueva inválida

- **WHEN** la API responde `422` por contraseña de menos de 12 caracteres
- **THEN** la SPA muestra el motivo y conserva al usuario en la pantalla

### Requirement: Rutas protegidas por rol

Toda ruta del personal SHALL exigir sesión. Las pantallas de administración
SHALL mostrarse solo al admin; recepción y odontólogo que naveguen a ellas
SHALL ver un aviso de acceso denegado. La UI SHALL ocultar las acciones que la
API rechazaría para el rol, sin reemplazar la autorización de la API.

#### Scenario: Sin sesión

- **WHEN** alguien sin sesión abre la agenda
- **THEN** la SPA lo lleva al login y, tras ingresar, vuelve a la agenda

#### Scenario: Recepción en una pantalla de admin

- **WHEN** recepción navega a la configuración de profesionales
- **THEN** ve "No tenés permiso para esta sección"

### Requirement: Logout

El logout SHALL invocar a la API, descartar el access en memoria y las cachés de
datos de la sesión en todas las pestañas, y volver al login, aunque la API no
responda.

#### Scenario: Cerrar sesión

- **WHEN** el usuario cierra sesión
- **THEN** la SPA llama `POST /api/auth/logout`, borra los datos en memoria y muestra el login

#### Scenario: API caída al cerrar sesión

- **WHEN** el logout falla por red
- **THEN** la SPA igual descarta la sesión local y muestra el login
