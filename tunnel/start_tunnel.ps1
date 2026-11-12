# Туннель «домашний ПК (Норильск) -> финский VPS» для гео-блокированных сайтов.
#
# Запускать НА ДОМАШНЕЙ МАШИНЕ. Что делает:
#   1) поднимает локальный мини-прокси (tunnel/rus_proxy.py, порт 8888);
#   2) держит SSH-реверс-туннель к VPS: порт 12080 на VPS ведёт в наш прокси;
#      при обрыве автоматически переподключается.
#
# На VPS при этом в .env бота должно быть:
#   RU_PROXY=http://127.0.0.1:12080
#
# Использование:
#   .\tunnel\start_tunnel.ps1 -VpsHost "root@1.2.3.4"
#   (порт/логин подставьте свои; ключ SSH должен уже работать к этому VPS)
param(
    [Parameter(Mandatory = $true)]
    [string]$VpsHost,

    [int]$RemotePort = 12080,   # порт на VPS, который будет слушать sshd (-R)
    [int]$LocalPort = 8888      # порт локального прокси на этой машине
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$proxy = Join-Path $root "tunnel\rus_proxy.py"

if (-not (Test-Path $python)) {
    Write-Error "Не найден интерпретатор: $python — запустите из папки проекта"
    exit 1
}

# 1) Локальный прокси (один экземпляр)
$proxyRunning = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
if (-not $proxyRunning) {
    Start-Process -WindowStyle Minimized -FilePath $python -ArgumentList @($proxy, "--port", "$LocalPort")
    Start-Sleep -Seconds 2
    Write-Host "[ok] локальный прокси запущен на 127.0.0.1:$LocalPort"
} else {
    Write-Host "[ok] локальный прокси уже слушает порт $LocalPort"
}

# 2) Реверс-туннель с автоперезапуском
Write-Host "[ok] туннель: VPS:$RemotePort -> 127.0.0.1:$LocalPort (Ctrl+C — остановить)"
while ($true) {
    ssh -N -R "$($RemotePort):127.0.0.1:$($LocalPort)" `
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
        -o ExitOnForwardFailure=yes -o ConnectTimeout=15 `
        $VpsHost
    Write-Warning "[retry] ssh оборвался, переподключение через 15 c..."
    Start-Sleep -Seconds 15
}
