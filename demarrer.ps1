# Démarre le serveur de développement après avoir mis le schéma à jour.
#
#   .\demarrer.ps1
#
# ``manage.py migrer`` copie db.sqlite3 dans backups/ puis applique les
# migrations en attente : le serveur ne démarre plus sur une base en retard.
# Pour seulement appliquer les migrations : .\demarrer.ps1 -MigrationsSeules

param(
    [switch]$MigrationsSeules
)

$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

& $python manage.py migrer
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Migrations en échec : serveur non démarré.' -ForegroundColor Red
    exit $LASTEXITCODE
}
if ($MigrationsSeules) {
    exit 0
}

& $python manage.py runserver 127.0.0.1:8000
exit $LASTEXITCODE
