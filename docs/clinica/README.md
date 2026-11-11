# Historia clínica (C-15) — política operativa

> Datos de salud (Ley 26.529 / 27.706 / 25.326). Las preguntas legales siguen abiertas para el
> asesor legal (`knowledge-base/10_preguntas_abiertas.md`).

## Acceso

- **Recepción**: sin acceso a ningún endpoint clínico (`403 forbidden_role`); la SPA no muestra la ruta.
- **Odontólogo**: solo pacientes con al menos un turno suyo (cualquier estado). Fuera de alcance
  responde `404`, igual que un paciente inexistente.
- **Admin**: lee toda la clínica; escribe solo si su usuario tiene `professional_id`. Solo el admin
  consulta la bitácora (`GET /api/clinical-records/{id}/access-log`) y ve adjuntos dados de baja.
- Cada lectura y escritura deja un `clinical_access_event` (sin contenido ni PII) en la misma
  transacción. Respuestas `Cache-Control: no-store`.

## Integridad y retención

- Nada se modifica ni se borra: anamnesis por versiones, evoluciones con correcciones como entradas
  nuevas (solo el autor, con motivo), odontograma como historial, bajas lógicas de adjuntos.
  Triggers append-only + rol `app_writer` sin `UPDATE`/`DELETE`.
- **Sin purga** en C-15 (10 años por Ley 26.529 art. 18, a confirmar por el asesor legal).
- Las exportaciones de C-13/C-14 **no** incluyen datos clínicos; la portabilidad clínica es follow-up.
- Fusión de pacientes: bloqueada si el absorbido tiene ficha (`409 patient_has_clinical_record`).

## Firma

Las evoluciones llevan **firma simple**: identidad autenticada + sello de tiempo del servidor +
SHA-256 del contenido canónico (verificable offline). **No** es firma digital Ley 25.506.

## Catálogos provisionales (pendiente validación — task 0.3)

Viven como datos en `backend/app/modules/clinical/catalog.py`:

- Estados del odontograma: sano, caries, obturación, sellador, corona, prótesis fija, endodoncia,
  implante, fractura, extracción indicada, ausente (alcance cara/pieza completa por estado).
- Anamnesis: alergias, medicación, condiciones sistémicas (casilleros), embarazo, tabaquismo,
  anticoagulantes, observaciones ≤ 1000 caracteres.

Un odontólogo de la clínica piloto debe validarlos; el resultado final se commitea acá.

## Backup del volumen de adjuntos

Los bytes viven en el volumen Docker `clinical_files` (montado en `api` en `/data/clinical_files`);
PITR (`docs/piloto/backups-pitr.md`) cubre la base pero **no** el volumen. Respaldo diario cifrado:

```bash
docker run --rm -v sistema_de_turnos_odontologico_clinical_files:/data:ro -v "$PWD":/out \
  alpine:3.20 tar czf /out/clinical_files-$(date +%F).tgz -C /data .
# cifrar (p. ej. age/gpg) y copiar fuera del host; nunca a un repo.
```

Restaurar: detener `api`, extraer en el volumen y verificar `sha256` contra `clinical_attachment`.
El downgrade de la migración `c15_clinical_record` **destruye** los datos clínicos: exigir dump previo.

## Follow-ups registrados

Periodontograma, ortodoncia/cefalometría, firma digital Ley 25.506 y consentimientos firmados,
HL7 FHIR/ReNaPDiS y portabilidad clínica, seguimiento de ítems del plan, edición del catálogo,
antivirus y S3 para adjuntos, pestañas de anamnesis/adjuntos/presupuestos en la SPA.
