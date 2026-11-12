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
set -e
VPS="${1:?использование: bash termux_setup.sh root@адрес-vps}"

echo "== 1/4 Пакеты =="
pkg update -y
pkg install -y python openssh

echo "== 2/4 Файлы с VPS =="
mkdir -p ~/tunnel
scp "$VPS:/root/norilsk-bot-tunnel/rus_proxy.py" ~/tunnel/rus_proxy.py
scp "$VPS:/root/norilsk-bot-tunnel/run_agent_termux.sh" ~/tunnel/run_agent_termux.sh
chmod +x ~/tunnel/run_agent_termux.sh

echo "== 3/4 Автозапуск при включении телефона (Termux:Boot) =="
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/tunnel.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
bash ~/tunnel/run_agent_termux.sh $VPS >> ~/tunnel/agent.log 2>&1 &
EOF
chmod +x ~/.termux/boot/tunnel.sh

echo "== 4/4 Запуск сейчас =="
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
