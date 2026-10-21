<#
Arranca el orquestador si no está corriendo. Lo llama la tarea programada de Windows (ver instalar_tarea_windows.ps1)
al iniciar sesión y cada 10 minutos, así que el scraper se recupera solo si el notebook se reinicia o el proceso se cae.

Es seguro llamarlo todas las veces que haga falta: si ya hay un orquestador en marcha, no hace nada (nunca lanza dos).
Para detener el orquestador a propósito, crear logs\orquestador.stop: el orquestador termina el paso en curso y sale, y esta
tarea no lo relanza mientras ese archivo exista. Para reanudar, borrar el archivo (la tarea lo lanza en 10 minutos como máximo).
#>
$raiz = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\felip\miniconda3\envs\data-science\python.exe"

if (Test-Path (Join-Path $raiz "logs\orquestador.stop")) { exit 0 }

$corriendo = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "python.exe" -and $_.CommandLine -match "orquestador\.py" }
if ($corriendo) { exit 0 }

$env:PYTHONPATH = $raiz
Start-Process -FilePath $python -ArgumentList "bronze/orquestador.py --pausa-min 3 --pausa-max 6" `
    -WorkingDirectory $raiz -WindowStyle Hidden
