# Lancement par double-clic (Lancer_Demo.bat, Lancer_Reel.bat) : vérifie les prérequis et que les ports sont libres,
# lance scripts\dev.ps1, attend que l'API et l'interface répondent, puis ouvre le navigateur. Code 1 en cas d'échec.
param([switch]$Demo, [int]$TimeoutSeconds = 40)

$root = Split-Path -Parent $PSScriptRoot
$url = "http://localhost:5173"
$mode = if ($Demo) { "démo (données simulées)" } else { "réel (vos données, cours Yahoo Finance)" }

function Fail([string]$message) {
    Write-Host ""
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Responds([string]$u) {
    try { return (Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 3).StatusCode -eq 200 } catch { return $false }
}

if (-not (Test-Path (Join-Path $root ".venv\Scripts\python.exe"))) {
    Fail "Environnement Python absent. Installation : voir « Installation » dans le README (python -m venv .venv ...)."
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Fail "Dépendances de l'interface absentes. Dans le dossier frontend : npm install."
}
$busy = @(8000, 5173 | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
if ($busy.Count) {
    $which = if ($busy.Count -gt 1) { "Ports 8000 et 5173 déjà utilisés" } else { "Port $busy déjà utilisé" }
    Fail ("$which : l'application tourne sans doute déjà.`n" +
          "Lancez Arreter.bat, puis relancez ce fichier.")
}

Write-Host "Lancement de Mini-terminal en mode $mode..."
try { & (Join-Path $PSScriptRoot "dev.ps1") -Demo:$Demo } catch { Fail "Échec du lancement : $_" }

Write-Host "Attente de l'API et de l'interface ($TimeoutSeconds s au plus)..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$api = $false; $ui = $false
while (-not ($api -and $ui) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if (-not $api) { $api = Responds "http://127.0.0.1:8000/openapi.json" }
    if (-not $ui) { $ui = Responds $url }
}
if (-not ($api -and $ui)) {
    $missing = @()
    if (-not $api) { $missing += "l'API (port 8000, fenêtre « Mini-terminal : API »)" }
    if (-not $ui) { $missing += "l'interface (port 5173, fenêtre « npm run dev »)" }
    Fail ("Rien ne répond après $TimeoutSeconds s pour " + ($missing -join " et ") + ".`n" +
          "Le message d'erreur est dans la fenêtre correspondante. Arreter.bat ferme les deux fenêtres.")
}

Start-Process $url
Write-Host "Prêt : $url ouvert dans le navigateur. Pour arrêter : Arreter.bat." -ForegroundColor Green
exit 0
