# Guida Configurazione Variabili d'Ambiente

## Variabili Richieste

Devi configurare queste variabili d'ambiente su Render.com (o nel file `.env` per test locali):

```
TELEGRAM_TOKEN=your_telegram_bot_token_here
CHAT_ID=your_chat_id_here
PORT=8080
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

---

## 1. TELEGRAM_TOKEN

**Come ottenerlo:**

1. Apri Telegram e cerca **[@BotFather](https://t.me/botfather)**
2. Invia il comando `/newbot`
3. Scegli un nome per il bot (es. "0-0 Monitor Bot")
4. Scegli un username per il bot (deve finire con `bot`, es. `zero_zero_monitor_bot`)
5. BotFather ti darà un token tipo: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`
6. **Copia questo token** - è il tuo `TELEGRAM_TOKEN`

**Esempio:**
```
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

⚠️ **IMPORTANTE**: Non condividere mai questo token pubblicamente!

---

## 2. CHAT_ID

**Per un gruppo Telegram (consigliato):**

1. Crea o apri il gruppo Telegram dove vuoi ricevere le notifiche
2. Aggiungi il bot al gruppo (cerca il bot per username e aggiungilo)
3. Invia un messaggio qualsiasi nel gruppo (puoi scrivere "test" o qualsiasi cosa)
4. Apri il browser e vai su:
   ```
   https://api.telegram.org/bot<TUO_TOKEN>/getUpdates
   ```
   Sostituisci `<TUO_TOKEN>` con il token ottenuto da BotFather
   
   Esempio:
   ```
   https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrsTUVwxyz/getUpdates
   ```

5. Cerca nel JSON la sezione `"chat"` e trova `"id"`:
   ```json
   {
     "message": {
       "chat": {
         "id": -1001234567890,
         "title": "Nome del Gruppo",
         "type": "supergroup"
       }
     }
   }
   ```

6. **Il CHAT_ID è il numero dopo `"id":`** - per i gruppi sarà sempre un numero **negativo** (es. `-1001234567890`)

**Esempio:**
```
CHAT_ID=-1001234567890
```

**Alternativa più semplice:**
- Dopo aver configurato il bot e aggiunto al gruppo, puoi usare il comando `/chatid` direttamente nel gruppo
- Il bot ti risponderà con il CHAT_ID corretto

---

## 3. PORT

**Valore fisso:**
```
PORT=8080
```

Questo è il numero di porta per l'HTTP server di keep-alive. Non cambiare a meno che Render.com non richieda una porta diversa.

---

## 4. SOFASCORE_PROXY_BASE

**Valore predefinito:**
```
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

Puoi lasciare questo valore così com'è. Il bot userà automaticamente un fallback se l'API diretta non funziona.

---

## Esempio Completo

Ecco un esempio completo di come dovrebbero essere le variabili d'ambiente:

```
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=-1001234567890
PORT=8080
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

---

## Come Configurare su Render.com

1. Vai su [Render.com](https://render.com) e accedi al tuo account
2. Seleziona il tuo servizio (Web Service)
3. Vai nella sezione **"Environment"** (Ambiente)
4. Clicca su **"Add Environment Variable"** per ogni variabile
5. Inserisci:
   - **Key**: `TELEGRAM_TOKEN`
   - **Value**: Il token ottenuto da BotFather
6. Ripeti per tutte le variabili
7. Salva le modifiche - Render riavvierà automaticamente il servizio

---

## Test Locale (file .env)

Se vuoi testare localmente, crea un file `.env` nella root del progetto:

```bash
# .env
TELEGRAM_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=-1001234567890
PORT=8080
SOFASCORE_PROXY_BASE=https://api.sofascore.com/api/v1
```

⚠️ **IMPORTANTE**: Non committare mai il file `.env` su GitHub! È già incluso in `.gitignore`.

---

## Verifica Configurazione

Dopo aver configurato le variabili:

1. Avvia il bot
2. Invia `/start` al bot (o nel gruppo se hai configurato un gruppo)
3. Se ricevi una risposta, la configurazione è corretta!
4. Usa `/chatid` per verificare che il CHAT_ID sia corretto
5. Usa `/status` per vedere lo stato del bot

---

## Troubleshooting

**Il bot non risponde:**
- Verifica che `TELEGRAM_TOKEN` sia corretto
- Controlla che il bot sia stato aggiunto al gruppo (se usi un gruppo)
- Verifica i log su Render.com per errori

**Le notifiche non arrivano:**
- Verifica che `CHAT_ID` sia corretto (deve essere negativo per i gruppi)
- Assicurati che il bot sia membro del gruppo
- Controlla che il bot abbia i permessi per inviare messaggi nel gruppo

**Errore "Chat not found":**
- Il CHAT_ID è sbagliato
- Il bot non è più nel gruppo
- Hai usato un CHAT_ID di una chat privata invece di un gruppo

---

## Note Importanti

- **CHAT_ID dei gruppi**: Sempre numeri negativi (es. `-1001234567890`)
- **CHAT_ID delle chat private**: Numeri positivi (es. `123456789`)
- **Token**: Non condividere mai pubblicamente
- **Porta**: Di solito `8080` va bene, ma Render potrebbe usare una porta diversa (controlla nelle impostazioni)

