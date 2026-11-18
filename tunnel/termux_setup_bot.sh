#!/data/data/com.termux/files/usr/bin/bash
# Однократная установка ПОЛНОГО бота на телефон (Termux).
# Код берётся из GitHub: https://github.com/svetsvetsvet525-png/meteo-bot
#
# Использование:  bash termux_setup_bot.sh [root@адрес-vps]
# Адрес VPS нужен только для страховочного SOCKS-релея Telegram
# (см. TELEGRAM_PROXY в tunnel/README.md). Обычно запускайте без аргумента.
#
# Файл .env (токен бота) в репозитории не хранится — пользователь
# вставляет его сам, скрипт подскажет как.
set -e
REPO="https://github.com/svetsvetsvet525-png/meteo-bot.git"
VPS="${1:-}"

echo "== 1/5 Пакеты =="
pkg update -y
# rust нужен для сборки pydantic-core (зависимость aiogram 3.x): под Android
# готового wheel нет, а rustup не знает таргет aarch64-linux-android —
# поэтому берём нативный rust из репозитория Termux.
pkg install -y python python-pip git openssh build-essential binutils rust libc++
# maturin (сборщик pydantic-core) на Android хочет знать API level
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || echo 30)"

echo "== 2/5 Код из GitHub =="
if [ -d "$HOME/meteo-bot/.git" ]; then
    git -C "$HOME/meteo-bot" pull --ff-only || true
else
    git clone "$REPO" "$HOME/meteo-bot"
fi

echo "== 3/5 Зависимости (несколько минут; pydantic-core собирается из Rust) =="
python -m pip install -r "$HOME/meteo-bot/requirements.txt"

echo "== 4/5 Файл .env с токеном =="
if [ ! -f "$HOME/meteo-bot/.env" ]; then
    echo
    echo "  Файл .env ещё не создан. Сделайте так:"
    echo "    nano ~/meteo-bot/.env"
    echo "  и вставьте строки (токен — от @BotFather):"
    echo "    BOT_TOKEN=ваш_токен"
    echo "    CHECK_INTERVAL=120"
    echo "  Сохранить в nano: Ctrl+O, Enter, Ctrl+X"
    echo
else
    echo "  .env на месте — ок."
fi

# SSH-ключ и релей — только когда задан VPS
if [ -n "$VPS" ]; then
    echo "== Доп.: SSH-ключ для VPS (пароль от VPS — один раз) =="
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    if [ ! -f ~/.ssh/id_ed25519 ]; then
        ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "termux-bot"
    fi
    ssh-copy-id "$VPS"
    ssh -o BatchMode=yes "$VPS" "echo ok" >/dev/null \
        || { echo "ОШИБКА: вход по ключу не сработал"; exit 1; }
fi

echo "== 5/5 Автозапуск при включении телефона (Termux:Boot) =="
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/bot.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
bash ~/meteo-bot/tunnel/run_bot_termux.sh $VPS >> ~/bot.log 2>&1 &
EOF
chmod +x ~/.termux/boot/bot.sh

echo "== Запуск сейчас =="
termux-wake-lock
nohup bash "$HOME/meteo-bot/tunnel/run_bot_termux.sh" "$VPS" >> "$HOME/bot.log" 2>&1 &
sleep 3
echo
echo "Готово! Лог бота:  tail -f ~/bot.log"
echo "Обновление кода:   cd ~/meteo-bot && git pull, затем перезапуск:"
echo "                   pkill -f run_bot_termux; bash ~/meteo-bot/tunnel/run_bot_termux.sh $VPS &"
echo
echo "ВАЖНО (иначе Android усыплит Termux и бот замолчит):"
echo "  1) Настройки → Приложения → Termux → Батарея → «Без ограничений»"
echo "  2) Держите телефон на зарядке"
echo "  3) Установите приложение Termux:Boot (F-Droid) — автозапуск после перезагрузки"
