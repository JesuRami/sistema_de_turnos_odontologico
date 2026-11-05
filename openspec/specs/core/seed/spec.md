# core/seed Specification

## Purpose
Permite dar de alta un tenant nuevo con el mínimo operable (clínica, admin
provisorio, sillón y profesional de ejemplo) de forma idempotente y solo con
datos sintéticos.

## Requirements

### Requirement: Seed mínimo por clínica

El seed SHALL crear 1 clínica con la configuración por defecto, 1 usuario
`admin` con cambio de contraseña obligatorio, 1 sillón activo "Sillón 1" y
1 profesional de ejemplo inactivo, sin pacientes.

#### Scenario: Seed sobre DB migrada vacía

- **WHEN** se ejecuta el seed contra una DB recién migrada
- **THEN** existen exactamente 1 clínica, 1 admin con
  `must_change_password=true`, 1 sillón "Sillón 1" activo, 1 profesional
  inactivo y 0 pacientes

### Requirement: Seed idempotente

Ejecutar el seed más de una vez para el mismo slug SHALL dejar el mismo estado
que una sola ejecución, sin duplicar filas ni sobrescribir la contraseña de un
admin existente.

#### Scenario: Doble ejecución

- **WHEN** se ejecuta el seed dos veces con el mismo slug
- **THEN** las cantidades de filas son las mismas que tras la primera
  ejecución y el hash del admin no cambió

### Requirement: Credenciales provisorias solo desde entorno

La credencial provisoria del admin SHALL leerse del entorno; si falta, el seed
SHALL abortar nombrando la variable sin crear nada, y NUNCA SHALL imprimir la
contraseña ni el hash.

#### Scenario: Falta la contraseña provisoria

- **WHEN** se ejecuta el seed sin la variable de contraseña del admin
- **THEN** aborta con un mensaje que nombra la variable y no persiste filas

#### Scenario: Salida sin secretos

- **WHEN** el seed termina con éxito
- **THEN** su salida no contiene la contraseña provisoria ni el hash

### Requirement: Datos del seed obviamente sintéticos

Todo dato de ejemplo del seed, tests y fixtures SHALL ser sintético y
obviamente falso, con emails del dominio `example.com`.

#### Scenario: Valores de ejemplo sintéticos

- **WHEN** se ejecuta el seed con los valores de `.env.example`
- **THEN** el email del admin termina en `@example.com` y el profesional de
  ejemplo tiene un nombre evidentemente ficticio

### Requirement: Plantillas de notificación por defecto en cada clínica

El seed SHALL crear, al dar de alta una clínica, las plantillas de alta de turno,
72 h, 24 h y 3 h para WhatsApp y su par de email, en `es_AR`, con nombres de
plantilla Meta placeholder y marcadas activas, sin pisar las que el admin haya
editado al re-ejecutarlo.

#### Scenario: Clínica nueva

- **WHEN** se ejecuta el seed sobre una base migrada vacía
- **THEN** la clínica tiene ocho plantillas activas, cuatro por canal, una por paso

#### Scenario: Re-ejecución respeta ediciones

- **WHEN** el admin cambió el texto de una plantilla y se re-ejecuta el seed
- **THEN** la plantilla conserva el texto editado y no se duplica ninguna

#### Scenario: Sin datos reales en las plantillas

- **WHEN** se inspeccionan las plantillas sembradas
- **THEN** solo contienen placeholders de variables y ningún dato personal ni
  teléfono o dirección reales
