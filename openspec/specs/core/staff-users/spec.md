# core/staff-users Specification

## Purpose
Modela a los usuarios del personal de la clínica (admin, recepción,
odontólogo) y el resguardo de sus contraseñas, como base sobre la que C-03
construye autenticación y RBAC.

## Requirements

### Requirement: Rol de usuario cerrado

Cada usuario SHALL tener exactamente un rol del conjunto cerrado `admin`,
`recepcion`, `odontologo`; la base SHALL rechazar cualquier otro valor.

#### Scenario: Rol desconocido rechazado

- **WHEN** se inserta un usuario con rol `superadmin`
- **THEN** la base rechaza la fila

#### Scenario: Roles válidos aceptados

- **WHEN** se insertan usuarios con rol `admin` y `recepcion` sin profesional
- **THEN** ambos persisten

### Requirement: Odontólogo vinculado a su profesional

Un usuario con rol `odontologo` SHALL tener `professional_id` de su misma
clínica; los roles `admin` y `recepcion` SHALL poder no tenerlo.

#### Scenario: Odontólogo sin profesional rechazado

- **WHEN** se inserta un usuario `odontologo` con `professional_id` nulo
- **THEN** la base rechaza la fila con violación de CHECK

#### Scenario: Odontólogo con profesional propio aceptado

- **WHEN** se inserta un usuario `odontologo` con un profesional de su clínica
- **THEN** el usuario persiste vinculado a ese profesional

### Requirement: Email de usuario único por clínica

El email de usuario SHALL guardarse en minúsculas y SHALL ser único dentro de
la clínica; el mismo email SHALL poder existir en otra clínica.

#### Scenario: Email duplicado en la misma clínica

- **WHEN** existe `admin@example.com` en la clínica A y se inserta otro usuario
  con ese email en A
- **THEN** la base rechaza la inserción con violación de unicidad

#### Scenario: Mismo email en otra clínica

- **WHEN** se inserta `admin@example.com` en la clínica B
- **THEN** persiste sin conflicto

#### Scenario: Email con mayúsculas rechazado por la base

- **WHEN** se inserta directamente un email `Admin@Example.com`
- **THEN** la base rechaza la fila con violación de CHECK

### Requirement: Contraseñas solo como hash argon2id

Las contraseñas SHALL almacenarse únicamente como hash argon2id con sal
aleatoria; el valor en claro NUNCA SHALL persistirse ni registrarse en logs.

#### Scenario: Hash verificable y no reversible

- **WHEN** se hashea una contraseña de prueba
- **THEN** el hash comienza con `$argon2id$`, no contiene la contraseña y la
  verificación con esa contraseña es exitosa

#### Scenario: Contraseña incorrecta no verifica

- **WHEN** se verifica el hash con otra contraseña o con un hash malformado
- **THEN** la verificación devuelve falso sin lanzar excepción

#### Scenario: Misma contraseña, hashes distintos

- **WHEN** se hashea dos veces la misma contraseña
- **THEN** los hashes son distintos y ambos verifican

### Requirement: Usuarios desactivables sin borrado

Un usuario SHALL desactivarse con `active=false` conservando la fila, y SHALL
poder marcarse con cambio de contraseña obligatorio.

#### Scenario: Usuario provisorio marcado

- **WHEN** se crea un usuario con credencial provisoria
- **THEN** persiste con `must_change_password=true` y `active=true`
