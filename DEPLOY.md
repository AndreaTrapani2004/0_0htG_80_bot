# Guida al Deploy su Render.com

## Setup su Render.com

### 1. Crea un nuovo Web Service

1. Vai su [Render.com](https://render.com) e accedi/registrati
2. Clicca su **"New +"** → **"Web Service"**
3. Connetti il tuo repository GitHub: `AndreaTrapani2004/0_0htG_80_bot`
4. Render rileverà automaticamente il repository

### 2. Configurazione del Servizio

**Impostazioni base:**
- **Name**: `0-0htg-80-bot` (o un nome a tua scelta)
- **Region**: Scegli la regione più vicina (es. Frankfurt, Ireland)
- **Branch**: `main`
- **Root Directory**: (lascia vuoto)
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python bot.py`
- **Instance Type**: Free tier va bene (puoi upgradare se necessario)

### 3. Variabili d'Ambiente

Aggiungi queste variabili d'ambiente nella sezione **"Environment"**:

```
TELEGRAM_TOKEN=your_telegram_bot_token_here
CHAT_ID=your_chat_id_here
PORT=8080
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

**Come ottenere i valori:**
- **TELEGRAM_TOKEN**: Crea un bot tramite [@BotFather](https://t.me/botfather) su Telegram
- **CHAT_ID**: 
  1. Invia un messaggio al bot
  2. Visita: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
  3. Cerca `"chat":{"id":...}` nel JSON

### 4. Deploy

1. Clicca su **"Create Web Service"**
2. Render inizierà automaticamente il build e il deploy
3. Attendi che il deploy sia completato (circa 2-3 minuti)
4. Il bot sarà disponibile all'URL: `https://0-0htg-80-bot.onrender.com` (o il nome che hai scelto)

## Keep-Alive con Servizi di Ping

Render.com mette in sleep i servizi gratuiti dopo 15 minuti di inattività. Per mantenerli attivi, usa un servizio di ping cron.

### Opzione 1: cron-job.org (Consigliato)

1. Vai su [cron-job.org](https://cron-job.org)
2. Crea un account gratuito
3. Clicca su **"Create cronjob"**
4. Configurazione:
   - **Title**: `Keep-alive Render Bot`
   - **Address**: `https://0-0htg-80-bot.onrender.com` (il tuo URL Render)
   - **Schedule**: Ogni 5 minuti (`*/5 * * * *`)
   - **Request Method**: `GET`
5. Salva e attiva il cronjob

### Opzione 2: UptimeRobot

1. Vai su [UptimeRobot](https://uptimerobot.com)
2. Crea un account gratuito
3. Clicca su **"Add New Monitor"**
4. Configurazione:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Render Bot Keep-Alive`
   - **URL**: `https://0-0htg-80-bot.onrender.com`
   - **Monitoring Interval**: `5 minutes`
5. Salva il monitor

### Opzione 3: EasyCron

1. Vai su [EasyCron](https://www.easycron.com)
2. Crea un account gratuito
3. Crea un nuovo cron job
4. Configurazione:
   - **URL**: `https://0-0htg-80-bot.onrender.com`
   - **Schedule**: Ogni 5 minuti
5. Salva e attiva

## Verifica Funzionamento

1. Controlla i log su Render.com per verificare che il bot si sia avviato correttamente
2. Invia `/start` al bot su Telegram per testare
3. Verifica che l'HTTP server risponda visitando l'URL del servizio nel browser
4. Controlla che il servizio di ping stia funzionando (dovresti vedere richieste nei log)

## Note Importanti

- Il servizio gratuito di Render può avere limiti di risorse
- I servizi gratuiti possono essere più lenti al primo avvio dopo un periodo di inattività
- Considera di upgradare a un piano a pagamento per prestazioni migliori
- Il bot continuerà a funzionare anche durante il "cold start" di Render

## Troubleshooting

**Bot non risponde:**
- Verifica che le variabili d'ambiente siano configurate correttamente
- Controlla i log su Render per errori
- Assicurati che il CHAT_ID sia corretto

**Servizio va in sleep:**
- Verifica che il servizio di ping sia attivo e funzionante
- Controlla che l'URL del servizio sia corretto nel servizio di ping
- Assicurati che l'HTTP server risponda correttamente (dovresti vedere "Bot is alive!" visitando l'URL)

