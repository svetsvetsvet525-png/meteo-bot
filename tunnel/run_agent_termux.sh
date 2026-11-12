#!/data/data/com.termux/files/usr/bin/bash
# Агент на старом Android-телефоне (Termux): локальный прокси + реверс-туннель к VPS.
# Телефон находится в России, поэтому бот на финском VPS через этот туннель
# ходит на гео-блокированные сайты (норильск.рф, norilsk-city.ru) с российского IP.
#
# Запуск:  bash run_agent_termux.sh root@адрес-vps [порт_на_vps]
# По умолчанию порт на VPS: 12080 (в .env бота: RU_PROXY=http://127.0.0.1:12080)
VPS="${1:?использование: bash run_agent_termux.sh root@адрес-vps [порт]}"
RPORT="${2:-12080}"
LPORT="${3:-8888}"
DIR="$(cd "$(dirname "$0")" && pwd)"

termux-wake-lock 2>/dev/null || true

python "$DIR/rus_proxy.py" --port "$LPORT" &
PROXY_PID=$!
trap 'kill $PROXY_PID 2>/dev/null; termux-wake-unlock 2>/dev/null; exit 0' INT TERM
echo "[agent] прокси на 127.0.0.1:$LPORT (pid $PROXY_PID)"

while true; do
    echo "[agent] туннель: VPS:$RPORT -> 127.0.0.1:$LPORT"
    ssh -N -R "$RPORT:127.0.0.1:$LPORT" \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        "$VPS"
    echo "[agent] ssh оборвался, переподключение через 15 c..."
    sleep 15
done
