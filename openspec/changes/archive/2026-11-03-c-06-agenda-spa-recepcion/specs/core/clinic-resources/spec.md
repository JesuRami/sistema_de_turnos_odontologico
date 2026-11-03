# Spec Delta — core/clinic-resources

## ADDED Requirements

### Requirement: Perfil de la clínica para el personal

Todo el personal autenticado SHALL consultar el nombre y la zona horaria de su
propia clínica. La respuesta SHALL NOT incluir políticas ni datos de otras
clínicas, y el tenant SHALL salir siempre de la sesión, nunca de la request.

#### Scenario: Odontólogo consulta la clínica

- **WHEN** un odontólogo pide el perfil de la clínica
- **THEN** recibe el nombre y la zona horaria `America/Argentina/Buenos_Aires`

#### Scenario: Sin sesión

- **WHEN** se pide el perfil sin access token
- **THEN** responde 401
