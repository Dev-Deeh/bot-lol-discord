#!/bin/bash
# Roda na VM (como root): atualiza o bot e grava as configs do servidor Bloom White.
# Uso (no Cloud Shell):
#   gcloud compute ssh bot-deeh-lol --zone=us-central1-a --quiet --command='sudo git -C /opt/bot pull -q; sudo bash /opt/bot/tools/vm_update_bloom.sh'
GUILD=1569317259581587517
google_metadata_script_runner startup >/dev/null 2>&1 || true
cd /opt/bot || exit 1
sudo -u bot git log --oneline -1
sudo -u bot .venv/bin/python tools/set_config.py bot.db "$GUILD" \
  privados:cat=1569480059251593333 \
  privados:roles=1569484939920154775 \
  autorole=1569318562756034662 \
  tierlist:cat=1569502305328566485 \
  canal:gratis=1569508627415306310 \
  canal:promos=1569508628807942217 \
  "times=1569484939920154775:1569480059251593333:1569502305328566485;1570190936443588650:1570191024721231962:1570191000251408424"
systemctl restart bot-lol
sleep 45
systemctl is-active bot-lol
journalctl -u bot-lol -n 8 --no-pager -o cat | cut -c1-150
