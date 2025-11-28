# 0_0htG_80_bot

Bot Telegram che monitora partite live da SofaScore e invia notifiche quando una partita è 0-0 al primo tempo.

## Funzionalità

- Monitora partite live da SofaScore ogni 60 secondi
- Invia notifiche quando una partita è 0-0 al primo tempo (minuto <= 45)
- Supporta configurazione di leghe da monitorare tramite comando `/addLeague`
- Salva stato in file JSON per evitare notifiche duplicate
- HTTP server integrato per keep-alive (necessario per Render.com)

## Installazione

1. Clona il repository o scarica i file

2. Installa le dipendenze:
```bash
pip install -r requirements.txt
```

3. Crea un file `.env` con le seguenti variabili:
```
TELEGRAM_TOKEN=your_telegram_bot_token_here
CHAT_ID=your_chat_id_here
PORT=8080
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

4. Ottieni il token del bot Telegram:
   - Crea un bot tramite [@BotFather](https://t.me/botfather) su Telegram
   - Copia il token ricevuto

5. Ottieni il CHAT_ID:
   
   **Per un gruppo (consigliato):**
   - Aggiungi il bot al gruppo come amministratore (opzionale ma consigliato)
   - Invia un messaggio qualsiasi nel gruppo (puoi anche usare `/chatid` se il bot è già configurato)
   - Visita `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Cerca `"chat":{"id":...}` nel JSON - il CHAT_ID sarà un numero negativo (es. `-1001234567890`)
   - **Oppure**: Usa il comando `/chatid` nel gruppo dopo aver configurato il bot
   
   **Per una chat privata:**
   - Invia un messaggio al bot
   - Visita `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Cerca `"chat":{"id":...}` nel JSON

## Esecuzione

```bash
python bot.py
```

## Deploy su Render.com

Per istruzioni dettagliate sul deploy su Render.com e configurazione del keep-alive, consulta il file [DEPLOY.md](DEPLOY.md).

**Quick start:**
1. Crea un nuovo Web Service su Render.com
2. Connetti il repository GitHub: `https://github.com/AndreaTrapani2004/0_0htG_80_bot`
3. Imposta le variabili d'ambiente (vedi DEPLOY.md)
4. Il bot si avvierà automaticamente
5. **IMPORTANTE**: Configura un servizio di ping (cron-job.org, UptimeRobot, ecc.) per mantenere il servizio attivo ogni 5 minuti

## Comandi Telegram

- `/start` - Messaggio di benvenuto
- `/help` - Guida comandi
- `/addLeague` - Gestisci leghe da monitorare (interfaccia con checkbox)
- `/leagues` - Mostra leghe attualmente monitorate
- `/chatid` - Mostra il CHAT_ID della chat/gruppo corrente
- `/stats` - Statistiche notifiche inviate
- `/status` - Stato del bot

## Leghe Supportate

Il bot supporta le seguenti leghe (configurabili tramite `/addLeague`):

- Estonia
- Hong Kong
- Olanda Eredivisie
- Islanda URVA
- Islanda Incasso
- Lussemburgo
- Qatar
- Norvegia Elite
- Norvegia OBOS
- Singapore
- Svizzera Super League
- Vietnam
- Italia Serie A e Serie B
- Francia Ligue 1 e Ligue 2
- Spagna La Liga e Segunda División
- Germania Bundesliga e 2. Bundesliga
- Inghilterra: Premier League, Championship, League 1, League 2

## Struttura File

- `bot.py` - File principale del bot
- `leagues.json` - Leghe selezionate per il monitoraggio
- `sent_matches.json` - Partite già notificate (per evitare duplicati)
- `active_matches.json` - Partite attualmente monitorate

## Note

- Il bot controlla le partite ogni 60 secondi
- Le notifiche vengono inviate solo una volta per partita
- L'HTTP server sulla porta 8080 mantiene il servizio attivo su Render.com
- Il bot filtra automaticamente solo campionati professionistici

## Licenza

MIT

