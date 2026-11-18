#!/data/data/com.termux/files/usr/bin/bash
# Полноценный сервер бота на телефоне (Termux): python -m bot в цикле
# автоперезапуска + (опционально) SOCKS-релей для Telegram через VPS.
#
# Запуск:  bash run_bot_termux.sh [root@адрес-vps]
#
# Адрес VPS нужен ТОЛЬКО если в .env задан TELEGRAM_PROXY=socks5://127.0.0.1:1080
# (страховка на случай замедления Telegram в России). В остальных случаях
# скрипт запускают без аргумента — Telegram работает с телефона напрямую.
DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$HOME/meteo-bot"
VPS="${1:-}"

termux-wake-lock 2>/dev/null || true
trap 'termux-wake-unlock 2>/dev/null; exit 0' INT TERM

# Страховочный SOCKS-релей: держим живым, только если он включён в .env
if [ -n "$VPS" ] && grep -q "^TELEGRAM_PROXY=" "$BOT_DIR/.env" 2>/dev/null; then
    (
        while true; do
            echo "[socks] релей 127.0.0.1:1080 через $VPS"
            ssh -N -D 1080 \
                -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
                -o ExitOnForwardFailure=yes -o ConnectTimeout=15 \
                -o StrictHostKeyChecking=accept-new \
                "$VPS"
            echo "[socks] релей оборвался, переподключение через 15 c"
            sleep 15
        done
    ) &
fi

echo "[runner] бот: $BOT_DIR (лог этого скрипта и бота — один файл)"
while true; do
    if [ -d "$BOT_DIR" ]; then
        cd "$BOT_DIR"
        python -m bot
        echo "[runner] бот завершился (код $?), перезапуск через 10 c"
    else
        echo "[runner] нет папки $BOT_DIR — установите бота (termux_setup_bot.sh)"
        sleep 30
    fi
    sleep 10
done
