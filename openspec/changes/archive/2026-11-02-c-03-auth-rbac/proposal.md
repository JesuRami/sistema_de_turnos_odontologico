# Proposal — c-03-auth-rbac (C-03 `auth-rbac` · CHANGES.md)

> Nota de nombre: el CLI exige kebab-case; `c-03-auth-rbac` corresponde a
> `C-03 auth-rbac` (Fase 0, governance **CRITICO**, depende de C-02 — tercer
> eslabón del camino crítico C-01→C-02→C-03→C-04→C-05→C-07→C-08→C-10→C-14).

## Why

El personal de la clínica todavía no puede entrar al sistema: C-02 dejó
`User` con hash argon2id y rol, pero sin autenticación ni autorización, y los
stubs de C-01 (`require_roles`, `get_db`) responden 501. Todo lo que viene
después (agenda de recepción C-06, CRUD de configuración C-04, turnos C-05,
reportes C-13) asume un `clinic_id` y un rol confiables en cada request: sin
C-03 cada endpoint tendría que inventar su propio control de acceso y el
aislamiento entre profesionales —la única frontera sensible real del dominio
(DD-03)— quedaría en manos del frontend, que es justo lo que la regla dura 10
prohíbe.

Es **CRITICO** porque define el contrato de credenciales y sesiones del
producto: rotación de refresh con detección de reuso, cookies HttpOnly,
revocación de personal desactivado y el punto único donde se decide qué ve un
odontólogo. Cambiar esto después del piloto obliga a reautenticar a todo el
personal y a revisar cada query.

## What Changes

- `POST /api/auth/login` — email + password, argon2id, rate-limit 5/60 s por
  IP+email y tope por IP; respuesta con access token en body y refresh en
  cookie HttpOnly `SameSite=Lax` (`Secure` según entorno).
- `POST /api/auth/refresh` — rotación de refresh con **detección de reuso**
  (familia de sesión en Redis): un token ya rotado que reaparece revoca la
  familia completa y se audita.
- `POST /api/auth/logout` — revoca la sesión vigente (refresh + access con el
  mismo `sid`) y limpia la cookie.
- `GET /api/auth/me` — identidad efectiva del portador (usuario, rol,
  `clinic_id`, `professional_id`, `must_change_password`).
- `POST /api/auth/change-password` — cambio autenticado; rehashea, revoca las
  demás sesiones y limpia `must_change_password` (necesario porque el seed de
  C-02 crea el admin con cambio obligatorio).
- JWT de acceso de 15 min con claims `sub`, `clinic_id`, `roles`, `email`,
  `jti`, `sid`, `type`, `iat`, `exp`, `iss`, `aud`; algoritmo pineado,
  `iss`/`aud`/`exp` validados y `JWT_SECRET` ≥32 bytes verificado al arranque.
- Dependency `require_roles('admin','recepcion')` sobre un `Principal`
  (usuario recargado de la DB, nunca claims de rol confiados) + helper de
  alcance por query que aplica "odontólogo solo lo suyo" en SQLAlchemy.
- CRUD de usuarios del personal (`GET/POST /api/users`, `PATCH
  /api/users/{id}`, `POST /api/users/{id}/password-reset`): alta/baja lógica
  (`active=false`, sin borrado físico), odontólogo atado a su
  `professional_id` (US-051 CA-1), revocación de sesiones al desactivar o
  cambiar rol.
- **Migración 002** (`c03_auth_rbac`, revises `c02_core_models`): columnas
  `user.password_changed_at` y tabla append-only `auth_event` (enum nativo
  `auth_event_type`) para la traza de seguridad sin PII.
- Infra transversal: rate-limit Redis reutilizable, validación de secreto JWT,
  cliente Redis inyectable en tests (Redis real de compose, sin mocks de DB).

Fuera de alcance: recuperación de contraseña por email, MFA, login social,
tokens de paciente (DD-04, C-07/C-08), endpoints de agenda/turnos (C-04/C-05),
vista de odontólogo en la SPA (C-06) y cualquier UI.

## Capabilities

### New Capabilities

- `identity/staff-auth`: ciclo de vida de la sesión del personal — login,
  rotación de refresh con detección de reuso, logout, `me`, política y cambio
  de contraseña, rate-limit y flags de cookie por entorno.
- `identity/rbac`: contrato de autorización — `Principal`, dependency de roles,
  matriz rol→permiso aplicada en servidor y alcance "odontólogo solo lo suyo"
  resuelto en la query.
- `identity/auth-audit`: traza de seguridad append-only de eventos de
  autenticación y de gestión de usuarios, sin datos personales.

### Modified Capabilities

- `core/staff-users`: los usuarios del personal dejan de ser solo un modelo y
  pasan a gestionarse por API — alta/baja lógica con rol, vínculo
  odontólogo↔profesional validado en el borde, reseteo de credencial
  provisoria y revocación de sesiones al desactivar o cambiar de rol.

## Impact

- Código nuevo: `backend/app/core/{jwt,rate_limit,redis}.py`,
  `backend/app/modules/auth/{service,router,schemas}.py` (reemplazan los stubs
  `ping`/`echo`), `backend/app/modules/users/{service,router,schemas}.py`
  (CRUD), `backend/app/modules/auth/audit.py`,
  `backend/app/common/{principal,scoping}.py`,
  `backend/alembic/versions/c03_auth_rbac.py`.
- Código modificado: `backend/app/core/{security,settings,deps}.py`,
  `backend/app/common/dependencies.py` (stub `require_roles` → real),
  `backend/app/main.py` (rate-limit global sigue; auth usa el suyo),
  `backend/tests/conftest.py` (`JWT_SECRET` de test ≥32 bytes, fixture Redis),
  `.env.example` (`JWT_*`, cookie, rate-limit de auth), `backend/app/seed.py`
  (admin del seed conserva `must_change_password=true`).
- Dependencias: C-04/C-05/C-06 consumen `Principal` + `require_roles` +
  helper de alcance; C-05 define el filtro concreto sobre `appointment`; C-14
  ajusta parámetros de argon2id y rotación de secreto.
- Reglas duras aplicadas: 2, 3, 4, 6, 7, 8, 9, 10, 11 (ver design), 13.
  Decisiones abiertas para revisión humana en `design.md`.
