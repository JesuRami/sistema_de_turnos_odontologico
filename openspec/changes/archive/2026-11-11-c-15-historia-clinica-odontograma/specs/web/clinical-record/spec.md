# Spec Delta — web/clinical-record (C-15)

## Purpose
Define la SPA de la historia clínica: acceso por rol, odontograma interactivo accesible y pestañas de anamnesis, evoluciones, adjuntos y presupuestos, sin dejar datos clínicos en el navegador.

## ADDED Requirements

### Requirement: Acceso por rol en la SPA
La ruta `/pacientes/:patientId/historia-clinica` SHALL estar disponible solo para `admin` y `odontologo`. Un usuario `recepcion` SHALL no ver el acceso en ningún menú ni en el detalle del turno y, si entra por URL, SHALL ver una pantalla "sin acceso" sin que se emita ninguna petición clínica.

#### Scenario: Odontólogo abre la historia desde el turno
- **WHEN** un odontólogo pulsa "Historia clínica" en el detalle de un turno suyo
- **THEN** navega a la ruta del paciente y se cargan las pestañas

#### Scenario: Recepción no ve el enlace
- **WHEN** recepción abre el detalle de un turno
- **THEN** no existe el botón "Historia clínica"

#### Scenario: Recepción por URL
- **WHEN** recepción navega a `/pacientes/<id>/historia-clinica`
- **THEN** ve "sin acceso" y no se emite ninguna petición a `/api/patients/*/clinical-record` (verificable en la red)

#### Scenario: Ficha no abierta
- **WHEN** la API responde `404 clinical_record_not_opened`
- **THEN** la pantalla ofrece "Abrir historia clínica" y, al pulsarlo, llama `POST` y muestra la ficha

#### Scenario: Paciente fuera de alcance
- **WHEN** la API responde `404 patient_not_found`
- **THEN** la pantalla muestra "Paciente no encontrado" sin datos

### Requirement: Odontograma accesible
El componente SHALL dibujar las 32 piezas permanentes o las 20 temporales, cada una con 5 caras seleccionables más un control de pieza completa; SHALL operarse con teclado (flechas para moverse, Enter/Espacio para elegir estado) y SHALL exponer a lectores de pantalla el nombre de cada cara (por ejemplo, "Pieza 36, cara oclusal: caries"). El color SHALL no ser el único indicador del estado (se suma código corto o patrón).

#### Scenario: Alternar dentición
- **WHEN** el usuario cambia a "Temporal"
- **THEN** se muestran 20 piezas numeradas 51–85 y el pedido usa `dentition=deciduous`

#### Scenario: Registrar un hallazgo con teclado
- **WHEN** el usuario enfoca 36/O con las flechas y confirma "Caries" con Enter
- **THEN** queda marcada la cara, el cambio se acumula como borrador y "Guardar" envía un lote con esa entrada

#### Scenario: Lote en curso
- **WHEN** el borrador tiene 33 cambios
- **THEN** el botón "Guardar" envía dos lotes (≤ 32) y recién entonces limpia el borrador; si uno falla, conserva los no confirmados y muestra el error

#### Scenario: Etiquetas accesibles
- **WHEN** un lector de pantalla recorre la cara 36/O con caries
- **THEN** anuncia "Pieza 36, cara oclusal: caries"

#### Scenario: Historial de la pieza
- **WHEN** el usuario abre el historial de la pieza 36
- **THEN** ve las entradas más recientes primero con autor e instante y puede pedir más (cursor)

### Requirement: Anamnesis y evoluciones en la UI
La pestaña Anamnesis SHALL mostrar la versión vigente, permitir guardar una nueva con `expected_version` y ante `409 version_conflict` SHALL avisar y ofrecer recargar sin perder lo escrito. La pestaña Evoluciones SHALL listar con cursor ("cargar más"), permitir crear una evolución y, solo para su autor, una corrección con motivo; la original SHALL seguir visible marcada como corregida.

#### Scenario: Conflicto de versión
- **WHEN** otro usuario guardó una versión mientras se editaba
- **THEN** se renderiza el aviso `role=alert` "versión desactualizada", el campo conserva el texto escrito y existe el botón "Recargar versión vigente"

#### Scenario: Corrección solo del autor
- **WHEN** un odontólogo mira una evolución de otro odontólogo
- **THEN** no ve la acción "Corregir"

#### Scenario: Original corregida
- **WHEN** una evolución fue corregida
- **THEN** se muestra con la etiqueta "Corregida" y el enlace a su corrección

### Requirement: Adjuntos y presupuestos en la UI
La pestaña Adjuntos SHALL subir archivos validando tipo y tamaño en el cliente (espejo del backend) y descargar vía la API autenticada (blob), sin URLs públicas. La pestaña Presupuestos SHALL editar fases e ítems, mostrar los totales calculados por el servidor, registrar la decisión y descargar el PDF.

#### Scenario: Archivo no permitido
- **WHEN** el usuario elige un `.exe` o un archivo de 11 MiB
- **THEN** la UI lo rechaza antes de enviarlo con el motivo

#### Scenario: Descarga autenticada
- **WHEN** el usuario descarga un adjunto
- **THEN** la petición lleva el access token por cabecera y el blob se descarga sin exponer una URL reutilizable

#### Scenario: Totales del servidor
- **WHEN** se guarda un presupuesto
- **THEN** la UI muestra los totales de la respuesta, no los calculados localmente

#### Scenario: Decisión
- **WHEN** el odontólogo registra "Aceptado" sobre la última versión
- **THEN** la UI muestra el estado y deshabilita la acción

### Requirement: Sin datos clínicos en el navegador
La SPA SHALL no persistir contenido clínico en `localStorage`, `sessionStorage`, IndexedDB ni en la cola de reintentos de C-14, y SHALL descartar el estado clínico en memoria al cerrar sesión o al cambiar de paciente. Los errores mostrados SHALL no contener texto clínico.

#### Scenario: Almacenamiento limpio
- **WHEN** el usuario trabaja una sesión completa en la historia clínica
- **THEN** `localStorage` y `sessionStorage` no contienen ninguna cadena de las ingresadas (verificado con datos sintéticos)

#### Scenario: Cierre de sesión
- **WHEN** el usuario cierra sesión y otro inicia
- **THEN** el DOM y el estado en memoria del segundo usuario no contienen ninguna cadena sintética cargada por el primero

#### Scenario: Sin red
- **WHEN** falla la red al guardar una evolución
- **THEN** la UI informa el error, conserva el texto en el formulario (memoria) y no encola el reintento
