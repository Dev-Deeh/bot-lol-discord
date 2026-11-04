# 🤖 Bot de LoL para Discord

Bot completo para o servidor do time: Riot API, scrims, draft, quiz, apostas e mais.

## 🚀 Como rodar (passo a passo)

### 1. Criar o bot no Discord
1. Acesse https://discord.com/developers/applications → **New Application** → dê um nome.
2. Aba **Bot** → **Reset Token** → copie o token (guarde bem, é a senha do bot).
3. Aba **OAuth2 → URL Generator**:
   - Scopes: `bot` e `applications.commands`
   - Permissões: *View Channels, Send Messages, Embed Links, Read Message History, Manage Roles,
     Manage Channels, Move Members, Connect*
4. Abra o link gerado e adicione o bot no seu servidor.
5. No Discord, **arraste o cargo do bot para cima** dos cargos de elo/nível (senão ele não consegue dar cargos).

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

### 4. Configurar no servidor (como admin)
- `/config canal tipo:Alertas de elo canal:#elo` — e o mesmo pra *Resumo pós-partida*, *Patch notes*,
  *Scrims*, *VOD review* e *Avisos de nível*
- `/config voz canal:🔊 Criar sala` — quem entrar ganha uma call própria (apagada quando esvazia)
- `/config cargo-nivel nivel:5 cargo:@Veterano`
- `/config ver`

## 🏅 Insígnia de Desenvolvedor Ativo
1. Com o bot rodando, use **`/ping`** no seu servidor.
2. Ative o **modo Comunidade** no servidor (Configurações do Servidor → Ativar Comunidade).
3. Espere até 24h e resgate em https://discord.com/developers/active-developer
4. Use algum comando do bot pelo menos 1x por mês pra não perder a insígnia.

## 📖 Comandos

| Área | Comandos |
|---|---|
| 🎮 Riot | `/vincular` (verifica pelo ícone de perfil) · `/perfil` · `/partida` (ao vivo) · `/ranking` · `/desvincular` |
| 🔔 Automático | alerta de subir/cair de elo · resumo de cada ranked · cargo de elo · patch novo (a cada 3h) |
| 🏆 Time | `/scrim marcar` (botões ✅🤔❌ + lembrete 30 min antes) · `/scrim resultado` · `/scrim historico` · `/scrim proximas` · `/lineup` · `/vod` |
| 🧠 Draft | `/draft iniciar` (ordem oficial, timer, capitães) · `/draft escolher` · `/pool` (`adicionar`, `time` com alertas, `sugerir`) · `/counter` · `/build` · `/patch` |
| 🎲 Diversão | `/times` (balanceado por elo) · `/roleta` · `/quiz` · `/nivel` · `/top` · `/diario` · `/aposta` |
| 🔧 Utilidades | `/lfg` · salas de voz temporárias · `/config` |

## ℹ️ Observações
- Os dados ficam no arquivo `bot.db` (SQLite). Faça backup dele de vez em quando.
- A Riot não tem API oficial de counters/builds; `/counter` e `/build` mandam links do U.GG, OP.GG e Lolalytics.
- `/patch` compara status base e recarga/custo das habilidades dos campeões do pool entre o patch atual e o anterior.
- O bot precisa estar ligado pra funcionar. Pra deixar 24h, hospede numa VPS, numa Raspberry Pi ou em serviços
  como Railway, Fly.io ou Oracle Cloud (free tier).
