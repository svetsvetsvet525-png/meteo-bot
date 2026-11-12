#!/data/data/com.termux/files/usr/bin/bash
# Однократная установка туннель-агента на старом Android-телефоне (Termux).
#
# Предполагается, что папка tunnel/ уже загружена на VPS в /root/norilsk-bot-tunnel
# (с Windows:  scp -r tunnel root@адрес-vps:/root/norilsk-bot-tunnel ).
#
# На телефоне в Termux:
#   pkg install -y openssh
#   scp root@адрес-vps:/root/norilsk-bot-tunnel/termux_setup.sh ~
#   bash ~/termux_setup.sh root@адрес-vps
#
# Скрипт спросит пароль от VPS один раз (для установки SSH-ключа),
# дальше туннель работает без пароля и перезапускается сам.
set -e
VPS="${1:?использование: bash termux_setup.sh root@адрес-vps}"

echo "== 1/4 Пакеты =="
pkg update -y
pkg install -y python openssh

echo "== 2/4 SSH-ключ (один раз вводим пароль от VPS) =="
mkdir -p ~/.ssh
chmod 700 ~/.ssh
if [ ! -f ~/.ssh/id_ed25519 ]; then
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "termux-tunnel"
fi
ssh-copy-id "$VPS"
# проверяем беспарольный доступ — без него фоновый туннель не жил бы
ssh -o BatchMode=yes "$VPS" "echo ok" >/dev/null \
    || { echo "ОШИБКА: вход по ключу не сработал"; exit 1; }

echo "== 3/4 Файлы с VPS =="
mkdir -p ~/tunnel
scp "$VPS:/root/norilsk-bot-tunnel/rus_proxy.py" ~/tunnel/rus_proxy.py
scp "$VPS:/root/norilsk-bot-tunnel/run_agent_termux.sh" ~/tunnel/run_agent_termux.sh
chmod +x ~/tunnel/run_agent_termux.sh

echo "== 4/4 Автозапуск при включении телефона (Termux:Boot) =="
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/tunnel.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
bash ~/tunnel/run_agent_termux.sh $VPS >> ~/tunnel/agent.log 2>&1 &
EOF
chmod +x ~/.termux/boot/tunnel.sh

echo "== Запуск сейчас =="
termux-wake-lock
nohup bash ~/tunnel/run_agent_termux.sh "$VPS" >> ~/tunnel/agent.log 2>&1 &
sleep 2
echo
echo "Готово! Лог агента:  tail -f ~/tunnel/agent.log"
echo
echo "ВАЖНО (иначе Android усыплит Termux):"
echo "  1) Настройки → Приложения → Termux → Батарея → «Без ограничений»"
echo "  2) Держите телефон на зарядке"
echo "  3) Для автозапуска после перезагрузки установите приложение Termux:Boot"
echo "     (тогда скрипт из ~/.termux/boot/ сработает сам)"
