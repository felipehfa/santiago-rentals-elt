<#
Registra la tarea programada "SantiagoRentalsOrquestador": al iniciar sesión y cada 10 minutos ejecuta
vigilar_orquestador.ps1, que lanza el orquestador solo si no está corriendo. Corre con el usuario actual, sin
privilegios de administrador, y también con el notebook a batería.

Uso (una sola vez):   powershell -ExecutionPolicy Bypass -File scripts\instalar_tarea_windows.ps1
Quitarla:             Unregister-ScheduledTask -TaskName SantiagoRentalsOrquestador -Confirm:$false
#>
$nombre = "SantiagoRentalsOrquestador"
$script = Join-Path $PSScriptRoot "vigilar_orquestador.ps1"

$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$alIniciar = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$cada10min = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10)
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $nombre -Action $accion -Trigger @($alIniciar, $cada10min) -Settings $ajustes `
    -Description "Mantiene corriendo el orquestador del scraper de santiago-rentals" -Force | Out-Null
Write-Host "Tarea '$nombre' registrada."
