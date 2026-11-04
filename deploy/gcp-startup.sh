#!/bin/bash
# Script de inicialização da VM do Google Cloud (roda sozinho em todo boot).
# Instala/atualiza o bot a partir do GitHub e deixa ele rodando como serviço,
# religando sozinho se cair. O arquivo .env (com as chaves) NÃO vem do GitHub:
# ele precisa ser copiado para /opt/bot/.env uma vez.
set -e
APP=/opt/bot
REPO=https://github.com/Dev-Deeh/bot-lol-discord.git
export DEBIAN_FRONTEND=noninteractive

# Memória extra (swap) para a e2-micro não engasgar instalando pacotes
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if ! command -v git >/dev/null || ! dpkg -s python3-venv >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y git python3-venv
fi

git config --global --add safe.directory "$APP" || true
if [ -d "$APP/.git" ]; then
  git -C "$APP" pull --ff-only || true
else
  git clone "$REPO" "$APP"
fi

id -u bot >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin bot
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R bot:bot "$APP"
[ -f "$APP/.env" ] && chmod 600 "$APP/.env"

cat > /etc/systemd/system/bot-lol.service <<EOF
[Unit]
Description=Bot Deeh LOL (Discord)
After=network-online.target
Wants=network-online.target

[Service]
User=bot
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python main.py
Restart=always
RestartSec=15
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable bot-lol
systemctl restart bot-lol
