# Arrêt par double-clic (Arreter.bat) : ferme les fenêtres ouvertes par dev.ps1 (API et interface) avec leurs
# sous-processus, puis vérifie que les ports 8000 et 5173 sont libres. Seuls les processus de ce projet sont arrêtés :
# les fenêtres de dev.ps1 (reconnues au chemin du projet dans leur ligne de commande, même en cours de démarrage), et
# tout processus du projet qui écoute sur ces ports, remonté jusqu'à sa fenêtre. Un autre programme est signalé, jamais
# arrêté.
$root = Split-Path -Parent $PSScriptRoot
$ports = 8000, 5173
$all = @{}
Get-CimInstance Win32_Process | ForEach-Object { $all[[int]$_.ProcessId] = $_ }

function Is-DevWindow($p) {
    $c = [string]$p.CommandLine
    return $p.Name -eq "powershell.exe" -and $c.Contains($root) -and
        ($c -match 'uvicorn backend\.app\.main:create_app' -or $c -match 'npm run dev')
}
function Parent-Of($p) {
    $q = $all[[int]$p.ParentProcessId]
    # Un PID parent peut avoir été réattribué : le parent doit être plus ancien que l'enfant.
    if ($q -and $q.CreationDate -le $p.CreationDate) { return $q }
    return $null
}

$roots = @{}
$foreign = @()
foreach ($p in $all.Values) { if (Is-DevWindow $p) { $roots[[int]$p.ProcessId] = $p } }
foreach ($port in $ports) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        $p = $all[[int]$id]
        if (-not $p) { continue }
        # Au projet : processus dont la ligne de commande contient le chemin du projet, ou descendant d'une fenêtre de
        # dev.ps1 (l'interpréteur réel de uvicorn n'a pas le chemin du projet dans sa ligne de commande).
        $top = $null
        for ($q = $p; $q; $q = Parent-Of $q) { if (Is-DevWindow $q) { $top = $q; break } }
        if (-not $top -and ([string]$p.CommandLine).Contains($root)) { $top = $p }
        if (-not $top) { $foreign += "port $port : $($p.Name) (PID $id), autre programme, non arrêté"; continue }
        $roots[[int]$top.ProcessId] = $top
    }
}

if (-not $roots.Count -and -not $foreign.Count) {
    Write-Host "L'application n'était pas lancée : rien à arrêter."
    exit 0
}
foreach ($t in $roots.Values) {
    Write-Host "Arrêt de $($t.Name) (PID $($t.ProcessId)) et de ses sous-processus"
    taskkill /PID $t.ProcessId /T /F | Out-Null
}

$deadline = (Get-Date).AddSeconds(10)
do {
    Start-Sleep -Milliseconds 500
    $busy = @($ports | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
} while ($busy.Count -gt $foreign.Count -and (Get-Date) -lt $deadline)

foreach ($port in $ports) {
    $free = -not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    Write-Host ("Port ${port} : " + $(if ($free) { "libre" } else { "OCCUPÉ" }))
}
foreach ($f in $foreign) { Write-Host $f -ForegroundColor Yellow }
if ($busy.Count) { exit 1 }
Write-Host "Application arrêtée." -ForegroundColor Green
exit 0
