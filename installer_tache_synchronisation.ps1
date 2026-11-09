# Installe la synchronisation horaire dans le Planificateur de tâches Windows.
#
#   .\installer_tache_synchronisation.ps1
#   .\installer_tache_synchronisation.ps1 -Heure 07:30
#   .\installer_tache_synchronisation.ps1 -SansExecution
#   .\installer_tache_synchronisation.ps1 -Desinstaller
#
# La tâche tourne sous l'utilisateur courant, toutes les heures, à partir de
# l'heure demandée (par défaut : dans cinq minutes). Elle est visible dans
# taskschd.msc sous « UniversAcademy - Synchronisation ».
#
# Sans compte de service, la tâche reste installée mais synchroniser.ps1
# journalise l'attente et n'échoue pas : elle commencera à importer dès que
# le JSON sera déposé.

param(
    [string]$Nom = 'UniversAcademy - Synchronisation',
    [string]$Heure = '',
    [string]$Credentials = '',
    [switch]$SansEcrire,
    [switch]$SansExecution,
    [switch]$Desinstaller
)

$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'synchroniser.ps1'

if ($Desinstaller) {
    Unregister-ScheduledTask -TaskName $Nom -Confirm:$false `
        -ErrorAction SilentlyContinue
    Write-Host "Tâche « $Nom » supprimée."
    exit 0
}

if (-not (Test-Path -LiteralPath $script)) {
    throw "Script introuvable : $script"
}

$identifiants = $Credentials
if (-not $identifiants) {
    $identifiants = $env:GOOGLE_APPLICATION_CREDENTIALS
}
if (-not $identifiants) {
    $identifiants = Join-Path $HOME '.config\academy\service-account.json'
}
if (-not (Test-Path -LiteralPath $identifiants -PathType Leaf)) {
    Write-Host ("Attention : compte de service absent ({0})." -f $identifiants) `
        -ForegroundColor Yellow
    Write-Host 'La tâche sera installée mais ignorera Google jusqu''à ce que le JSON existe.' `
        -ForegroundColor Yellow
}

if (-not $Heure) {
    $Heure = (Get-Date).AddMinutes(5).ToString('HH:mm')
}

try {
    $heureLancement = [datetime]::ParseExact($Heure, 'HH:mm', $null)
} catch {
    throw "Heure invalide : « $Heure ». Format attendu : HH:mm (par exemple 07:30)."
}

$prochain = (Get-Date).Date.Add($heureLancement.TimeOfDay)
if ($prochain -lt (Get-Date)) { $prochain = $prochain.AddDays(1) }

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $script) `
    -WorkingDirectory $PSScriptRoot

if ($SansEcrire) {
    $action.Arguments += ' -SansEcrire'
}
if ($Credentials) {
    $action.Arguments += (' -Credentials "{0}"' -f $Credentials)
}

$declencheur = New-ScheduledTaskTrigger -Once -At $prochain `
    -RepetitionInterval (New-TimeSpan -Hours 1)

$reglages = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 50) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $Nom -Action $action -Trigger $declencheur `
    -Settings $reglages -Principal $principal -Force `
    -Description 'Synchronise les classeurs Google et applique les migrations en attente.' `
    | Out-Null

Write-Host ("Tâche « {0} » installée." -f $Nom)
Write-Host ("Premier lancement : {0}, puis toutes les heures." -f `
    $prochain.ToString('yyyy-MM-dd HH:mm'))
if ($SansEcrire) {
    Write-Host 'Mode prévisualisation : aucun import ne sera écrit en base.'
}
Write-Host 'Journal : synchronisation.log à la racine du projet.'

if (-not $SansExecution) {
    Start-ScheduledTask -TaskName $Nom
    Start-Sleep -Seconds 3
    $info = Get-ScheduledTaskInfo -TaskName $Nom
    Write-Host ("Lancement immédiat demandé (dernier résultat : {0})." -f `
        $info.LastTaskResult)
    Write-Host 'Le détail du passage est dans synchronisation.log.'
} else {
    Write-Host 'Lancement immédiat non demandé (-SansExecution).'
}
