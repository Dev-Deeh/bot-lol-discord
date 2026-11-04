# 🤖 Bot de LoL para Discord

Bot simples e bonito para o servidor do time: tudo vira **card em imagem**, com splash do campeão,
emblema do elo e ícones de itens, runas e feitiços.

## 📖 Comandos

| Comando | O que faz |
|---|---|
| `/vincular Nick#TAG` | Liga sua conta da Riot ao Discord (verifica pelo ícone de perfil) e dá o cargo do seu elo |
| `/perfil` | Card com elo Solo/Flex, PDL, winrate e os 3 campeões mais jogados |
| `/partida` | Card da partida ao vivo: campeões, feitiços, runas, elo e winrate dos 10 jogadores |
| `/ranking` | Card com o ranking de elo do servidor |
| `/desvincular` | Remove sua conta |
| `/ajuda` · `/ping` | Ajuda e teste |

**Automático** (a cada 10 min, só para quem vinculou):
- 🔔 Card de alerta quando alguém **sobe ou cai de elo** (e o cargo de elo é atualizado)
- 📊 Card de **resumo de cada ranked**: resultado, KDA, itens, dano, CS, ouro, visão e participação em abates

**Admins:** `/config canal` escolhe o canal dos alertas e dos resumos · `/config ver`

## 🚀 Como rodar

### 1. Criar o bot no Discord
1. Acesse https://discord.com/developers/applications → **New Application** → dê um nome.
2. Aba **Bot** → **Reset Token** → copie o token (guarde bem, é a senha do bot).
3. Aba **OAuth2 → URL Generator**:
   - Scopes: `bot` e `applications.commands`
   - Permissões: *View Channels, Send Messages, Embed Links, Attach Files, Read Message History, Manage Roles*
4. Abra o link gerado e adicione o bot no seu servidor.
5. No Discord, **arraste o cargo do bot para cima** dos cargos de elo (senão ele não consegue dar cargos).

> Não precisa ligar nenhum "Privileged Gateway Intent".

### 2. Pegar a chave da Riot
1. Entre em https://developer.riotgames.com com sua conta Riot.
2. Copie a **Development API Key** (expira a cada 24h — é só gerar outra e colar no `.env`).
3. Quando o bot estiver estável, peça uma **Personal API Key** (não expira) em *Register Product*.

### 3. Configurar e rodar
```bash
python -m pip install -r requirements.txt
```
Copie `.env.example` para `.env` e preencha `DISCORD_TOKEN`, `GUILD_ID` e `RIOT_API_KEY`. Depois:
```bash
python main.py
```

## ☁️ Deixar online 24h (Google Cloud, VM e2-micro grátis)
1. No [Cloud Shell](https://shell.cloud.google.com), crie a VM (o script instala e liga o bot sozinho):
```bash
gcloud compute instances create bot-deeh-lol --zone=us-central1-a --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=30GB --boot-disk-type=pd-standard --metadata=startup-script-url=https://raw.githubusercontent.com/Dev-Deeh/bot-lol-discord/main/deploy/gcp-startup.sh
```
2. Envie o `.env` (e o `bot.db`, se quiser manter as contas vinculadas) pelo menu **Upload** do Cloud Shell e copie:
```bash
gcloud compute scp .env bot.db bot-deeh-lol:/tmp/ --zone=us-central1-a && gcloud compute ssh bot-deeh-lol --zone=us-central1-a --command='sudo mv /tmp/.env /tmp/bot.db /opt/bot/ && sudo chown bot:bot /opt/bot/.env /opt/bot/bot.db && sudo chmod 600 /opt/bot/.env && sudo systemctl restart bot-lol'
```
3. Ver os logs: `gcloud compute ssh bot-deeh-lol --zone=us-central1-a --command='sudo journalctl -u bot-lol -n 30'`
4. Atualizar o bot depois de mudar o código no GitHub: reinicie a VM (o script faz `git pull` em todo boot).

## ℹ️ Observações
- Os dados ficam no arquivo `bot.db` (SQLite). Faça backup dele de vez em quando.
- Imagens: [Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon) (oficial da Riot) e emblemas de elo
  do [Community Dragon](https://communitydragon.org). Fonte Montserrat (licença OFL, em `assets/fonts`).
- O bot precisa estar ligado pra funcionar. Pra deixar 24h, hospede numa VPS, numa Raspberry Pi ou em serviços
  como Railway, Fly.io ou Oracle Cloud (free tier).

*Bot Deeh LOL isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone
officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are
trademarks or registered trademarks of Riot Games, Inc.*
