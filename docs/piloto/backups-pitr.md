# Backups cifrados con PITR (C-14) — runbook

Herramienta propuesta: **pgBackRest** con repositorio cifrado (`repo1-cipher-type=aes-256-cbc`) y
archivado continuo de WAL (PITR). Config de ejemplo: `ops/backup/pgbackrest.conf.example`.

1. En `db`: `archive_mode=on`, `archive_command='pgbackrest --stanza=turnos archive-push %p'`, `wal_level=replica`.
2. `pgbackrest --stanza=turnos stanza-create`.
3. Full semanal + diferencial diario (cron del host): `pgbackrest --stanza=turnos --type=full backup`.
4. Retención: `repo1-retention-full=4`.
5. **Simulacro mensual**: restaurar a un instante (`--type=time --target="AAAA-MM-DD HH:MM:SS-03"`)
   en una base aparte y correr `GET /api/reports/pilot` (integridad: 0 solapamientos).

La clave del repositorio va en el secret manager del proveedor, nunca en el repo (regla 6).
Pendiente de validar en staging: no se pudo ejecutar en el entorno del change.
