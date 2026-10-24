# Mode développement sans Docker : API (port 8000) et interface (port 5173) dans deux fenêtres.
#   .\scripts\dev.ps1          données réelles (Yahoo Finance)
#   .\scripts\dev.ps1 -Demo    données simulées, base séparée pré-remplie
param([switch]$Demo)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Environnement virtuel absent : python -m venv .venv puis pip install -r requirements-dev.txt" }

$envDemo = if ($Demo) { '$env:MT_DEMO = "1"; ' } else { '' }
$frontend = Join-Path $root "frontend"
# Le chemin du projet figure dans la ligne de commande des deux fenêtres : scripts\arreter.ps1 les reconnaît ainsi,
# même avant qu'elles n'écoutent sur leur port.
Start-Process powershell -WorkingDirectory $root -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'Mini-terminal : API'; $envDemo& '$python' -m uvicorn backend.app.main:create_app --factory --reload --port 8000"
Start-Process powershell -WorkingDirectory $frontend -ArgumentList "-NoExit", "-Command",
    "`$host.UI.RawUI.WindowTitle = 'Mini-terminal : interface'; Set-Location -LiteralPath '$frontend'; npm run dev"
Write-Host "API : http://127.0.0.1:8000/docs    Interface : http://localhost:5173"
