import time
import sys
import json
import tempfile
from io import BytesIO
import os
import re
import requests
from datetime import datetime, timedelta
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import Conflict, NetworkError
from threading import Thread
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler


# ---------- CONFIGURAZIONE ----------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
POLL_INTERVAL = 60  # Intervallo di controllo in secondi
SOFASCORE_API_URL = "https://api.sofascore.com/api/v1"
# Proxy opzionale per SofaScore (es. Cloudflare Workers). Se settato, sostituisce la base URL.
SOFASCORE_PROXY_BASE = os.getenv("SOFASCORE_PROXY_BASE", SOFASCORE_API_URL)


# File per salvare le partite già notificate (evita duplicati)
SENT_MATCHES_FILE = "sent_matches.json"





# ---------- FUNZIONI UTILI ----------

def load_sent_matches():
    """Carica le partite già notificate da file"""
    try:
        with open(SENT_MATCHES_FILE, "r") as f:
            data = json.load(f)
            # Se è una lista (vecchio formato), converti in dict
            if isinstance(data, list):
                return {match_id: {} for match_id in data}
            return data
    except Exception:
        return {}


def save_sent_matches(sent_dict):
    """Salva le partite già notificate su file"""
    with open(SENT_MATCHES_FILE, "w") as f:
        json.dump(sent_dict, f, indent=2)


def get_match_id(home, away, league, event_id=None):
    """Genera un ID univoco per una partita"""
    if event_id:
        return str(event_id)
    return f"{home}_{away}_{league}".lower().replace(" ", "_")


def _fetch_sofascore_json(url, headers):
    """Tenta fetch diretto; su 403 usa fallback r.jina.ai come proxy pubblico."""
    now_utc = datetime.utcnow().isoformat() + "Z"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                print(f"[{now_utc}] ⚠️ JSON non valido dalla API diretta, lunghezza body={len(resp.text)}")
                sys.stdout.flush()
                return None
        if resp.status_code != 403:
            print(f"[{now_utc}] ⚠️ Errore API SofaScore: status={resp.status_code}")
            sys.stdout.flush()
            return None
        # Fallback via r.jina.ai (no crediti, spesso evita blocchi IP)
        # Convertiamo https://... in http://... per l'URL interno
        inner = url.replace("https://", "http://")
        proxy_url = f"https://r.jina.ai/{inner}"
        print(f"[{now_utc}] 🔁 Fallback via r.jina.ai: {proxy_url}")
        sys.stdout.flush()
        prox_resp = requests.get(
            proxy_url,
            headers={
                "User-Agent": headers.get("User-Agent", "Mozilla/5.0"),
                "Accept": "application/json",
            },
            timeout=20,
        )
        if prox_resp.status_code == 200:
            try:
                import json as _json
                wrapper = prox_resp.json()
                # r.jina.ai restituisce un wrapper con data.content come stringa JSON
                if isinstance(wrapper, dict) and "data" in wrapper:
                    data_obj = wrapper.get("data", {})
                    if isinstance(data_obj, dict) and "content" in data_obj:
                        content_str = data_obj.get("content", "")
                        if isinstance(content_str, str) and content_str.strip().startswith("{"):
                            # Parse il JSON annidato
                            try:
                                return _json.loads(content_str)
                            except Exception as e:
                                print(f"[{now_utc}] ⚠️ Errore parse JSON annidato da r.jina.ai: {e}")
                                sys.stdout.flush()
                # Se non è il formato r.jina.ai, restituisci direttamente
                return wrapper
            except Exception:
                # Alcuni proxy restituiscono testo JSON valido: prova json.loads
                import json as _json
                try:
                    return _json.loads(prox_resp.text)
                except Exception:
                    print(f"[{now_utc}] ⚠️ Impossibile parsare JSON dal fallback, primi 200 char: {prox_resp.text[:200]!r}")
                    sys.stdout.flush()
                    return None
        print(f"[{now_utc}] ⚠️ Fallback r.jina.ai fallito: status={prox_resp.status_code}")
        sys.stdout.flush()
        return None
    except Exception as e:
        print(f"[{now_utc}] ⚠️ Eccezione fetch SofaScore: {e}")
        sys.stdout.flush()
        return None


def scrape_sofascore():
    """Ottiene tutte le partite live tramite API SofaScore"""
    try:
        # Header per sembrare un browser reale
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com"
        }
        
        # Prova multipli endpoint per recuperare eventi live
        endpoints = [
            f"{SOFASCORE_PROXY_BASE}/sport/football/events/live",
            f"{SOFASCORE_PROXY_BASE}/sport/football/events/inplay",
            f"{SOFASCORE_PROXY_BASE}/sport/football/livescore",
        ]
        
        now_utc = datetime.utcnow().isoformat() + "Z"
        events = []
        for idx, url in enumerate(endpoints, start=1):
            print(f"[{now_utc}] Richiesta API SofaScore: {url}... (tentativo {idx})")
            sys.stdout.flush()
            data = _fetch_sofascore_json(url, headers)
            if not data:
                continue
            # Normalizza le possibili chiavi
            events = data.get("events") or data.get("results") or []
            print(f"[{now_utc}] ✅ Trovate {len(events)} partite live dalla API (tentativo {idx})")
            sys.stdout.flush()
            if events:
                break
            else:
                # Log breve del payload per capire il formato
                try:
                    import json as _json
                    raw = _json.dumps(data)[:200]
                except Exception:
                    raw = str(data)[:200]
                print(f"[{now_utc}] ℹ️ Nessun evento nell'endpoint, anteprima payload: {raw}")
                sys.stdout.flush()
        
        matches = []
        if not events:
            print(f"[{now_utc}] ⚠️ Nessun evento trovato su tutti gli endpoint live")
            sys.stdout.flush()
            return []
        
        for event in events:
            try:
                # Estrai informazioni partita
                tournament = event.get("tournament", {})
                league = tournament.get("name", "Unknown")
                country = tournament.get("category", {}).get("name", "Unknown")
                
                home_team = event.get("homeTeam", {})
                away_team = event.get("awayTeam", {})
                home = home_team.get("name", "Unknown")
                away = away_team.get("name", "Unknown")
                
                # Estrai punteggio (sono oggetti con 'current' o 'display')
                score_home_obj = event.get("homeScore", {})
                score_away_obj = event.get("awayScore", {})
                
                # Estrai valore numerico dal punteggio
                if isinstance(score_home_obj, dict):
                    score_home = score_home_obj.get("current", score_home_obj.get("display", 0))
                else:
                    score_home = score_home_obj if score_home_obj is not None else 0
                
                if isinstance(score_away_obj, dict):
                    score_away = score_away_obj.get("current", score_away_obj.get("display", 0))
                else:
                    score_away = score_away_obj if score_away_obj is not None else 0
                
                # Estrai minuto e calcola attendibilità
                time_obj = event.get("time", {})
                status = event.get("status", {})
                minute = None
                reliability = 0  # Attendibilità 0-5
                
                if isinstance(time_obj, dict):
                    # Determina periodo (1st half o 2nd half)
                    status_desc = status.get("description", "").lower()
                    status_code = status.get("code")
                    is_first_half = "1st half" in status_desc or status_code == 6
                    is_second_half = "2nd half" in status_desc or status_code == 7
                    
                    # Calcola minuto corrente basato su currentPeriodStartTimestamp
                    if "currentPeriodStartTimestamp" in time_obj:
                        start_ts = time_obj.get("currentPeriodStartTimestamp")
                        if start_ts:
                            elapsed_seconds = datetime.now().timestamp() - start_ts
                            elapsed_minutes = int(elapsed_seconds / 60)
                            
                            if is_second_half:
                                # Secondo tempo: aggiungi 45 minuti
                                minute = 45 + max(0, elapsed_minutes)
                                reliability = 4  # Calcolo corretto con periodo
                            elif is_first_half:
                                # Primo tempo: minuto diretto
                                minute = max(0, elapsed_minutes)
                                reliability = 4  # Calcolo corretto con periodo
                            else:
                                # Periodo non determinato, usa solo elapsed
                                minute = max(0, elapsed_minutes)
                                reliability = 2  # Minuto calcolato ma senza periodo
                    
                    # Se non disponibile, prova a estrarre da status description
                    if minute is None:
                        desc = status.get("description", "")
                        if "1st half" in desc or "2nd half" in desc:
                            # Estrai numero se presente nella descrizione (es. "1st half 23'")
                            match = re.search(r'(\d+)\s*[\'"]', desc)
                            if match:
                                extracted_min = int(match.group(1))
                                if is_second_half and extracted_min < 45:
                                    # Se è secondo tempo ma il minuto è < 45, aggiungi 45
                                    minute = 45 + extracted_min
                                else:
                                    minute = extracted_min
                                reliability = 3  # Minuto estratto da descrizione
                elif isinstance(time_obj, (int, float)):
                    minute = int(time_obj)
                    reliability = 1  # Minuto diretto ma senza contesto
                
                # Estrai stato partita
                status = event.get("status", {})
                status_type = status.get("type", "")
                
                # Determina metà tempo (1st half o 2nd half)
                period = None
                status_desc = status.get("description", "").lower()
                if "1st half" in status_desc or status.get("code") == 6:
                    period = 1  # Primo tempo
                elif "2nd half" in status_desc or status.get("code") == 7:
                    period = 2  # Secondo tempo
                elif minute is not None:
                    # Determina dalla base del minuto
                    if minute <= 45:
                        period = 1
                    else:
                        period = 2
                
                # Estrai ID partita per recuperare eventi/gol
                event_id = event.get("id")
                
                matches.append({
                    "home": home,
                    "away": away,
                    "score_home": score_home,
                    "score_away": score_away,
                    "league": league,
                    "country": country,
                    "minute": minute,
                    "period": period,  # 1 = primo tempo, 2 = secondo tempo
                    "reliability": reliability,  # Attendibilità 0-5
                    "event_id": event_id,  # ID partita per recuperare eventi/gol
                    "status_code": status.get("code"),
                    "status_type": status.get("type"),
                    "status_description": status.get("description", "")
                })
            except Exception as e:
                print(f"Errore nell'estrazione partita: {e}")
                continue
        
        print(f"[{now_utc}] ✅ Estratte {len(matches)} partite totali dalla risposta")
        sys.stdout.flush()
        return matches
    
    except requests.exceptions.RequestException as e:
        now_utc = datetime.utcnow().isoformat() + "Z"
        print(f"[{now_utc}] Errore nella richiesta API SofaScore: {e}")
        sys.stdout.flush()
        return []
    except Exception as e:
        now_utc = datetime.utcnow().isoformat() + "Z"
        print(f"[{now_utc}] Errore nello scraping SofaScore: {e}")
        sys.stdout.flush()
        return []


def is_match_0_0_first_half(match):
    """
    Verifica se una partita è 0-0 a fine primo tempo.
    
    Criteri:
    - Punteggio è 0-0
    - Minuto >= 45 O periodo = 1 (fine primo tempo) O status indica fine primo tempo
    """
    score_home = match.get("score_home", 0)
    score_away = match.get("score_away", 0)
    
    # Deve essere 0-0
    if score_home != 0 or score_away != 0:
        return False
    
    minute = match.get("minute")
    period = match.get("period")
    status_code = match.get("status_code")
    status_desc = match.get("status_description", "").lower()
    
    # Verifica fine primo tempo:
    # 1. Minuto >= 45 (fine primo tempo)
    # 2. Periodo = 1 E minuto >= 40 (primo tempo avanzato)
    # 3. Status indica fine primo tempo (halftime, break, etc.)
    # 4. Status code 31 = halftime
    
    if status_code == 31 or "halftime" in status_desc or "break" in status_desc:
        return True
    
    if minute is not None:
        # Se minuto >= 45, è fine primo tempo
        if minute >= 45:
            return True
        # Se periodo = 1 e minuto >= 40, consideriamo fine primo tempo
        if period == 1 and minute >= 40:
            return True
    
    # Se periodo = 2, significa che il primo tempo è finito
    # Ma dobbiamo verificare che il punteggio sia ancora 0-0
    if period == 2:
        # Verifica che il minuto sia ancora basso (primi minuti del secondo tempo)
        # per essere sicuri che il primo tempo era 0-0
        if minute is not None and minute <= 50:
            return True
    
    return False


def format_match_notification(match):
    """Formatta il messaggio di notifica per una partita 0-0 a fine primo tempo"""
    home = match.get("home", "Unknown")
    away = match.get("away", "Unknown")
    league = match.get("league", "Unknown")
    country = match.get("country", "Unknown")
    minute = match.get("minute")
    event_id = match.get("event_id")
    
    # Costruisci link SofaScore
    match_url = f"https://www.sofascore.com/event/{event_id}" if event_id else ""
    
    # Formatta minuto
    minute_str = f"{minute}'" if minute is not None else "N/A"
    
    # Formatta paese/lega
    league_str = f"{league}"
    if country and country != "Unknown":
        league_str += f" - {country}"
    
    # Costruisci messaggio
    message = f"⚽ 0-0 al Primo Tempo\n\n"
    message += f"🏠 {home}\n"
    message += f"🆚 {away}\n"
    message += f"📊 {league_str}\n"
    message += f"⏱️ Minuto: {minute_str}"
    
    if match_url:
        message += f"\n🔗 {match_url}"
    
    return message


async def send_notification(match, application):
    """Invia notifica Telegram per partita 0-0 a fine primo tempo"""
    global total_notifications_sent
    
    try:
        message = format_match_notification(match)
        await application.bot.send_message(chat_id=CHAT_ID, text=message)
        
        # Aggiorna statistiche
        total_notifications_sent += 1
        today = datetime.now().strftime("%Y-%m-%d")
        daily_notifications[today] += 1
        
        now_utc = datetime.utcnow().isoformat() + "Z"
        print(f"[{now_utc}] ✅ Notifica inviata: {match.get('home')} - {match.get('away')} (0-0 HT)")
        sys.stdout.flush()
    except Exception as e:
        now_utc = datetime.utcnow().isoformat() + "Z"
        print(f"[{now_utc}] ⚠️ Errore invio notifica: {e}")
        sys.stdout.flush()


# ---------- LOGICA PRINCIPALE ----------

def process_matches(application):
    """Processa tutte le partite live e invia notifiche per 0-0 a fine primo tempo"""
    import asyncio
    sent_matches = load_sent_matches()
    
    # Scraping partite live
    print("Scraping SofaScore...")
    live_matches = scrape_sofascore()
    print(f"Trovate {len(live_matches)} partite live")
    
    now = datetime.now()
    
    for match in live_matches:
        home = match["home"]
        away = match["away"]
        league = match["league"]
        event_id = match.get("event_id")
        
        # Usa event_id come match_id se disponibile, altrimenti genera uno
        match_id = get_match_id(home, away, league, event_id)
        
        # Se la partita è già stata notificata, salta
        if match_id in sent_matches:
            continue
        
        # Verifica se è 0-0 a fine primo tempo
        if is_match_0_0_first_half(match):
            # Invia notifica (async) usando application.bot
            try:
                # Ottieni il loop dell'application
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    # Se non c'è loop, prova a ottenerlo dall'application
                    if hasattr(application, '_updater') and hasattr(application._updater, '_loop'):
                        loop = application._updater._loop
                    else:
                        # Crea un nuovo loop
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                
                # Usa run_coroutine_threadsafe se il loop è in esecuzione
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(send_notification(match, application), loop)
                else:
                    # Altrimenti esegui direttamente
                    loop.run_until_complete(send_notification(match, application))
            except Exception as e:
                now_utc = datetime.utcnow().isoformat() + "Z"
                print(f"[{now_utc}] ⚠️ Errore invio notifica async: {e}")
                sys.stdout.flush()
            
            # Salva come notificata
            sent_matches[match_id] = {
                "home": home,
                "away": away,
                "league": league,
                "country": match.get("country", "Unknown"),
                "event_id": event_id,
                "minute": match.get("minute"),
                "period": match.get("period"),
                "notified_at": now.isoformat()
            }
    
    # Salva stato
    save_sent_matches(sent_matches)


# ---------- STATO RUNTIME PER COMANDI ----------

from collections import defaultdict

last_check_started_at = None
last_check_finished_at = None
last_check_error = None
total_notifications_sent = 0
daily_notifications = defaultdict(int)


# ---------- COMANDI TELEGRAM ----------

async def cmd_start(update, context):
    """Messaggio di benvenuto"""
    welcome_text = (
        "👋 Benvenuto in 0-0 HT Bot!\n\n"
        "⚽ Bot per notifiche 0-0 al Primo Tempo\n\n"
        "Il bot monitora tutte le partite live da SofaScore e ti avvisa quando:\n"
        "• Una partita è 0-0\n"
        "• È alla fine del primo tempo (minuto >= 45 o periodo = 1 finito)\n\n"
        "📋 Usa /help per vedere tutti i comandi disponibili\n"
        "📊 Usa /status per lo stato del bot"
    )
    await update.message.reply_text(welcome_text)


async def cmd_ping(update, context):
    """Verifica se il bot è attivo"""
    await update.message.reply_text("pong ✅")


async def cmd_help(update, context):
    """Mostra guida dettagliata"""
    help_text = (
        "⚽ 0-0 HT Bot - Notifiche 0-0 al Primo Tempo\n\n"
        "Cosa fa: Monitora tutte le partite live (SofaScore) e invia notifiche "
        "quando una partita è 0-0 a fine primo tempo.\n\n"
        "📋 Comandi disponibili:\n"
        "/start - Messaggio di benvenuto\n"
        "/ping - Verifica se il bot è attivo\n"
        "/help - Questa guida\n"
        "/status - Stato ultimo check, errori, statistiche\n"
        "/live - Elenco partite live 0-0\n"
        "/stats - Statistiche notifiche (ultimi 7 giorni)"
    )
    await update.message.reply_text(help_text)


async def cmd_status(update, context):
    """Mostra stato del bot"""
    lines = []
    lines.append("📊 Stato Bot:")
    lines.append(f"Intervallo controlli: {POLL_INTERVAL} secondi ({POLL_INTERVAL // 60} minuto{'i' if POLL_INTERVAL // 60 > 1 else ''})")
    
    if last_check_started_at:
        lines.append(f"Ultimo check start: {last_check_started_at.strftime('%H:%M:%S')}")
    else:
        lines.append("Ultimo check start: Nessuno")
    
    if last_check_finished_at:
        lines.append(f"Ultimo check end: {last_check_finished_at.strftime('%H:%M:%S')}")
        if last_check_started_at:
            elapsed = (last_check_finished_at - last_check_started_at).total_seconds()
            lines.append(f"Durata ultimo check: {elapsed:.1f}s")
    else:
        lines.append("Ultimo check end: Nessuno")
    
    if last_check_error:
        lines.append(f"⚠️ Ultimo errore: {last_check_error}")
    else:
        lines.append("✅ Nessun errore")
    
    # Statistiche giornaliere
    today = datetime.now().strftime("%Y-%m-%d")
    lines.append(f"Notifiche oggi: {daily_notifications.get(today, 0)}")
    lines.append(f"Totale notifiche: {total_notifications_sent}")
    
    await update.message.reply_text("\n".join(lines))


async def cmd_live(update, context):
    """Mostra partite live 0-0"""
    try:
        # Esegui uno scraping veloce
        matches = scrape_sofascore()
        
        if not matches:
            await update.message.reply_text("Nessuna partita live al momento.")
            return
        
        # Filtra solo partite 0-0
        zero_zero = [m for m in matches if m["score_home"] == 0 and m["score_away"] == 0]
        
        if not zero_zero:
            await update.message.reply_text(f"Trovate {len(matches)} partite live, nessuna in 0-0.")
            return
        
        lines = [f"📊 Partite live 0-0: {len(zero_zero)}"]
        for m in zero_zero[:20]:  # Limita a 20 per non superare limiti Telegram
            minute_str = f" {m['minute']}'" if m.get('minute') is not None else " N/A'"
            period_str = f" (1H)" if m.get('period') == 1 else f" (2H)" if m.get('period') == 2 else ""
            lines.append(f"• {m['home']} - {m['away']} 0-0{minute_str}{period_str} ({m['league']})")
        
        if len(zero_zero) > 20:
            lines.append(f"... e altre {len(zero_zero) - 20} partite")
        
        await update.message.reply_text("\n".join(lines)[:4000])
    except Exception as e:
        await update.message.reply_text(f"Errore nel recupero partite: {e}")


async def cmd_stats(update, context):
    """Mostra statistiche notifiche"""
    today = datetime.now().date()
    lines = ["📊 Statistiche notifiche (ultimi 7 giorni):"]
    
    total_week = 0
    for i in range(7):
        d = today - timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        count = daily_notifications.get(date_str, 0)
        total_week += count
        day_name = d.strftime("%a %d/%m")
        lines.append(f"• {day_name}: {count}")
    
    lines.append(f"\nTotale settimana: {total_week}")
    lines.append(f"Totale generale: {total_notifications_sent}")
    
    await update.message.reply_text("\n".join(lines))


def setup_telegram_commands():
    """Configura e avvia Application per comandi Telegram"""
    try:
        # Crea Application
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Configura logging per sopprimere errori Conflict
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.WARNING
        )
        
        # Filtra errori Conflict dal logging di python-telegram-bot
        class ConflictFilter(logging.Filter):
            def filter(self, record):
                msg = str(record.getMessage())
                return "Conflict" not in msg and "conflict" not in msg.lower()
        
        # Applica filtro ai logger di telegram
        telegram_logger = logging.getLogger('telegram')
        telegram_logger.addFilter(ConflictFilter())
        httpx_logger = logging.getLogger('httpx')
        httpx_logger.addFilter(ConflictFilter())
        
        # Gestione errori
        async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
            """Gestisce errori durante l'elaborazione degli update"""
            error = context.error
            if isinstance(error, Conflict):
                # Ignora silenziosamente errori Conflict (più istanze in esecuzione)
                return
            elif isinstance(error, NetworkError):
                # Ignora silenziosamente errori di rete temporanei
                return
            else:
                # Log altri errori
                print(f"⚠️ Errore durante elaborazione update: {error}")
        
        application.add_error_handler(error_handler)
        
        # Registra comandi
        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CommandHandler("ping", cmd_ping))
        application.add_handler(CommandHandler("help", cmd_help))
        application.add_handler(CommandHandler("status", cmd_status))
        application.add_handler(CommandHandler("live", cmd_live))
        application.add_handler(CommandHandler("stats", cmd_stats))
        
        # Avvia polling in thread separato
        def run_polling():
            try:
                application.run_polling(drop_pending_updates=True)
                print("✅ Application Telegram avviato - Comandi disponibili")
            except Conflict:
                print("⚠️ Errore Conflict all'avvio (probabilmente più istanze in esecuzione)")
                print("⚠️ Il bot continuerà a funzionare ma potrebbe non ricevere comandi")
            except Exception as e:
                print(f"⚠️ Errore all'avvio polling: {e}")
        
        polling_thread = Thread(target=run_polling, daemon=True)
        polling_thread.start()
        
        return application
    except Exception as e:
        print(f"⚠️ Errore nell'avvio Application: {e}")
        return None


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Handler per HTTP server di keep-alive"""
    def _send_health_response(self):
        """Invia risposta di health check"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'OK')
    
    def do_GET(self):
        """Gestisce richieste GET"""
        if self.path == '/health' or self.path == '/':
            self._send_health_response()
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_HEAD(self):
        """Gestisce richieste HEAD (usate da Render e UptimeRobot)"""
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        """Gestisce richieste OPTIONS"""
        self.send_response(200)
        self.send_header('Allow', 'GET, HEAD, OPTIONS')
        self.end_headers()
    
    def log_message(self, format, *args):
        # Disabilita logging HTTP per ridurre spam
        pass


def start_http_server(port=8080):
    """Avvia HTTP server per keep-alive (evita che Render si addormenti)"""
    try:
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        Thread(target=server.serve_forever, daemon=True).start()
        print(f"✅ HTTP server avviato su porta {port} (keep-alive)")
    except Exception as e:
        print(f"⚠️ Errore avvio HTTP server: {e}")


def main():
    """Loop principale: controlla partite ogni POLL_INTERVAL secondi"""
    global last_check_started_at, last_check_finished_at, last_check_error
    
    print("Bot avviato. Monitoraggio partite live su SofaScore...")
    sys.stdout.flush()
    
    # Avvia HTTP server per keep-alive (se PORT è definito, usa quello)
    port = int(os.getenv('PORT', 8080))
    start_http_server(port)
    
    # Avvia Application per comandi Telegram in background
    application = setup_telegram_commands()
    
    # Attendi un po' per permettere all'application di inizializzarsi
    time.sleep(2)
    
    while True:
        try:
            last_check_started_at = datetime.now()
            cycle_start_utc = datetime.utcnow().isoformat() + "Z"
            print(f"[{cycle_start_utc}] ▶️ Inizio ciclo controllo partite")
            sys.stdout.flush()
            last_check_error = None
            if application:
                process_matches(application)
            else:
                print("⚠️ Application non disponibile, salto controllo")
            last_check_finished_at = datetime.now()
            cycle_end_utc = datetime.utcnow().isoformat() + "Z"
            print(f"[{cycle_end_utc}] ⏹️ Fine ciclo controllo partite")
            sys.stdout.flush()
        except Exception as e:
            last_check_error = str(e)
            print(f"Errore: {e}")
            sys.stdout.flush()
        print(f"Attesa {POLL_INTERVAL} secondi prima del prossimo controllo...")
        sys.stdout.flush()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
