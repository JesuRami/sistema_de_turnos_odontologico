<#
.SYNOPSIS
  Entorno de desarrollo con Docker en un solo comando.

.DESCRIPTION
  .\dev.ps1            Levanta todo (crea .env si falta, construye, migra, siembra y espera).
  .\dev.ps1 up         Igual que sin argumentos.
  .\dev.ps1 down       Apaga los contenedores (conserva los datos).
  .\dev.ps1 reset      Borra contenedores Y DATOS de dev (base y Redis) y levanta de cero.
  .\dev.ps1 logs [svc] Sigue los logs (todos o de un servicio: api, worker, frontend, migrate).
  .\dev.ps1 status     Estado de los servicios.

  Las migraciones y el seed corren solos en el servicio `migrate` antes de la API: no hace
  falta `alembic upgrade head` a mano después de un change nuevo, solo volver a levantar.
#>
param(
  [ValidateSet("up", "down", "reset", "logs", "status")]
  [string]$Command = "up",
  [string]$Service = ""
)

# "Continue": Docker escribe su progreso en stderr y PowerShell 5.1 lo trataría como error
# fatal con "Stop". Los fallos se detectan por `$LASTEXITCODE`.
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

function Ensure-EnvFile {
  if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Se creó .env a partir de .env.example (valores de ejemplo, no secretos)."
  }
}

function Wait-Healthy {
  param([int]$TimeoutSeconds = 300)
  $limite = (Get-Date).AddSeconds($TimeoutSeconds)
  $servicios = @("api", "worker", "frontend")
  while ((Get-Date) -lt $limite) {
    $migrate = docker compose ps -a migrate --format "{{.State}} {{.Status}}"
    if ($migrate -match "exited" -and $migrate -notmatch "Exited \(0\)") {
      Write-Host "La migración o el seed fallaron. Logs:" -ForegroundColor Red
      docker compose logs migrate --tail 40
      exit 1
    }
    $listos = 0
    foreach ($s in $servicios) {
      if ((docker compose ps $s --format "{{.Status}}") -match "\(healthy\)") { $listos++ }
    }
    if ($listos -eq $servicios.Count) { return }
    Start-Sleep -Seconds 3
  }
  Write-Host "Algún servicio no quedó healthy a tiempo:" -ForegroundColor Red
  docker compose ps -a
  exit 1
}

function Start-Stack {
  Ensure-EnvFile
  docker compose up -d --build --remove-orphans
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Write-Host "Esperando que los servicios queden healthy..."
  Wait-Healthy
  Write-Host ""
  Write-Host "Listo." -ForegroundColor Green
  Write-Host "  Frontend (Vite):  http://localhost:5174"
  Write-Host "  API (Swagger):    http://localhost:8000/docs"
  Write-Host "  Reserva pública:  http://localhost:5174/b/clinica-demo"
  Write-Host "  Credenciales de acceso demo (ver DOCS_ROLES_Y_ACCESO.md):"
  Write-Host "    - Admin:       admin@example.com      (clave de SEED_ADMIN_PASSWORD, pide cambio al entrar)"
  Write-Host "    - Recepción:   recepcion@example.com  (misma clave, acceso directo a agenda)"
  Write-Host "    - Odontólogo:  odontologo@example.com (misma clave, vista restringida a sus turnos)"
}

switch ($Command) {
  "up" { Start-Stack }
  "down" { docker compose down --remove-orphans }
  "reset" {
    $respuesta = Read-Host "Esto borra la base y Redis de desarrollo. ¿Continuar? (s/N)"
    if ($respuesta -notin @("s", "S", "si", "sí")) { Write-Host "Cancelado."; exit 0 }
    docker compose down --volumes --remove-orphans
    Start-Stack
  }
  "logs" {
    if ($Service) { docker compose logs -f --tail 100 $Service } else { docker compose logs -f --tail 100 }
  }
  "status" { docker compose ps -a }
}
