#!/usr/bin/env python3
"""
Bot Telegram per monitorare partite 0-0 al primo tempo da SofaScore
"""

import os
import json
import time
import logging
import threading
import asyncio
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Set, Optional

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Carica variabili d'ambiente
load_dotenv()

# Configurazione
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
PORT = int(os.getenv('PORT', '8080'))
SOFASCORE_BASE = os.getenv('SOFASCORE_PROXY_BASE', 'https://api.sofascore.com/api/v1')
POLL_INTERVAL = 60  # secondi

# File JSON
LEAGUES_FILE = 'leagues.json'
SENT_MATCHES_FILE = 'sent_matches.json'
ACTIVE_MATCHES_FILE = 'active_matches.json'

# Leghe iniziali da monitorare (slug/id da SofaScore)
INITIAL_LEAGUES = {
    'estonia': {'name': 'Estonia', 'slug': 'estonia'},
    'hong-kong': {'name': 'Hong Kong', 'slug': 'hong-kong'},
    'netherlands': {'name': 'Olanda Eredivisie', 'slug': 'netherlands'},
    'iceland-urva': {'name': 'Islanda URVA', 'slug': 'iceland-urva'},
    'iceland-incasso': {'name': 'Islanda Incasso', 'slug': 'iceland-incasso'},
    'luxembourg': {'name': 'Lussemburgo', 'slug': 'luxembourg'},
    'qatar': {'name': 'Qatar', 'slug': 'qatar'},
    'norway-elite': {'name': 'Norvegia Elite', 'slug': 'norway-elite'},
    'norway-obos': {'name': 'Norvegia OBOS', 'slug': 'norway-obos'},
    'singapore': {'name': 'Singapore', 'slug': 'singapore'},
    'switzerland': {'name': 'Svizzera Super League', 'slug': 'switzerland'},
    'vietnam': {'name': 'Vietnam', 'slug': 'vietnam'},
    'italy-serie-a': {'name': 'Italia Serie A', 'slug': 'italy-serie-a'},
    'italy-serie-b': {'name': 'Italia Serie B', 'slug': 'italy-serie-b'},
    'france-ligue-1': {'name': 'Francia Ligue 1', 'slug': 'france-ligue-1'},
    'france-ligue-2': {'name': 'Francia Ligue 2', 'slug': 'france-ligue-2'},
    'spain-la-liga': {'name': 'Spagna La Liga', 'slug': 'spain-la-liga'},
    'spain-segunda': {'name': 'Spagna Segunda División', 'slug': 'spain-segunda-division'},
    'germany-bundesliga': {'name': 'Germania Bundesliga', 'slug': 'germany-bundesliga'},
    'germany-2-bundesliga': {'name': 'Germania 2. Bundesliga', 'slug': 'germany-2-bundesliga'},
    'england-premier-league': {'name': 'Inghilterra Premier League', 'slug': 'england-premier-league'},
    'england-championship': {'name': 'Inghilterra Championship', 'slug': 'england-championship'},
    'england-league-one': {'name': 'Inghilterra League 1', 'slug': 'england-league-one'},
    'england-league-two': {'name': 'Inghilterra League 2', 'slug': 'england-league-two'},
}

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class KeepAliveHandler(BaseHTTPRequestHandler):
    """HTTP Handler per keep-alive su Render.com"""
    
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'Bot is alive!')
    
    def log_message(self, format, *args):
        """Disabilita logging HTTP"""
        pass


def load_json_file(filename: str, default: any = None) -> any:
    """Carica file JSON, ritorna default se non esiste"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Errore caricamento {filename}: {e}")
    return default if default is not None else {}


def save_json_file(filename: str, data: any):
    """Salva dati in file JSON"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Errore salvataggio {filename}: {e}")


class SofaScoreAPI:
    """Classe per interagire con SofaScore API"""
    
    def __init__(self, base_url: str = SOFASCORE_BASE):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        })
    
    def get_tournaments(self) -> List[Dict]:
        """Recupera lista di tutti i tornei disponibili"""
        try:
            url = f"{self.base_url}/unique-tournaments"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('uniqueTournaments', [])
        except Exception as e:
            logger.error(f"Errore recupero tornei: {e}")
            return []
    
    def get_live_matches(self) -> List[Dict]:
        """Recupera tutte le partite live"""
        try:
            url = f"{self.base_url}/sport/football/events/live"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('events', [])
        except Exception as e:
            logger.error(f"Errore recupero partite live: {e}")
            return []
    
    def get_match_details(self, event_id: int) -> Optional[Dict]:
        """Recupera dettagli di una partita specifica"""
        try:
            url = f"{self.base_url}/event/{event_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Errore recupero dettagli partita {event_id}: {e}")
            return None


class MatchMonitor:
    """Classe per monitorare partite 0-0 al primo tempo"""
    
    def __init__(self, api: SofaScoreAPI, app: Application):
        self.api = api
        self.app = app
        self.sent_matches: Set[int] = set(load_json_file(SENT_MATCHES_FILE, []))
        self.active_matches: Dict[int, Dict] = load_json_file(ACTIVE_MATCHES_FILE, {})
        self.monitored_leagues: Set[str] = set(load_json_file(LEAGUES_FILE, {}).get('leagues', []))
        
        # Se non ci sono leghe configurate, usa quelle iniziali
        if not self.monitored_leagues:
            self.monitored_leagues = set(INITIAL_LEAGUES.keys())
            self.save_leagues()
    
    def save_leagues(self):
        """Salva leghe monitorate"""
        save_json_file(LEAGUES_FILE, {'leagues': list(self.monitored_leagues)})
    
    def is_match_0_0_first_half(self, match: Dict) -> bool:
        """Verifica se partita è 0-0 al primo tempo"""
        try:
            event = match.get('event', {})
            home_score = event.get('homeScore', {}).get('current', 0)
            away_score = event.get('awayScore', {}).get('current', 0)
            
            # Deve essere 0-0
            if home_score != 0 or away_score != 0:
                return False
            
            # Verifica periodo e minuto
            status = event.get('status', {})
            period = status.get('period', 0)
            minute = status.get('minute', 0)
            
            # Primo tempo: periodo = 1 o minuto <= 45
            if period == 1 or (period == 0 and minute > 0 and minute <= 45):
                return True
            
            return False
        except Exception as e:
            logger.error(f"Errore verifica 0-0: {e}")
            return False
    
    def get_league_info_from_match(self, match: Dict) -> tuple:
        """Estrae informazioni lega da match (slug, nome, id)"""
        try:
            tournament = match.get('tournament', {})
            unique_tournament = tournament.get('uniqueTournament', {})
            slug = unique_tournament.get('slug', '').lower()
            name = unique_tournament.get('name', '').lower()
            tournament_id = unique_tournament.get('id')
            return (slug, name, tournament_id)
        except:
            return (None, None, None)
    
    def is_league_monitored(self, match: Dict) -> bool:
        """Verifica se la lega della partita è monitorata"""
        slug, name, tournament_id = self.get_league_info_from_match(match)
        if not slug and not name:
            return False
        
        # Controlla se lo slug o il nome corrispondono a una lega monitorata
        for league_id, league_info in INITIAL_LEAGUES.items():
            if league_id in self.monitored_leagues:
                league_slug = league_info['slug'].lower()
                league_name = league_info['name'].lower()
                
                # Match per slug
                if slug and (slug == league_slug or slug.startswith(league_slug) or league_slug in slug):
                    return True
                
                # Match per nome (parziale)
                if name:
                    # Controlla se il nome contiene parole chiave della lega
                    name_keywords = league_name.split()
                    if any(keyword in name for keyword in name_keywords if len(keyword) > 3):
                        # Match specifici per leghe note
                        if 'italy' in league_id and ('serie a' in name or 'serie b' in name):
                            return True
                        if 'france' in league_id and ('ligue 1' in name or 'ligue 2' in name):
                            return True
                        if 'spain' in league_id and ('la liga' in name or 'segunda' in name):
                            return True
                        if 'germany' in league_id and ('bundesliga' in name):
                            return True
                        if 'england' in league_id and ('premier' in name or 'championship' in name or 'league' in name):
                            return True
                        if 'netherlands' in league_id and ('eredivisie' in name):
                            return True
        
        return False
    
    def format_match_notification(self, match: Dict) -> str:
        """Formatta messaggio notifica partita"""
        try:
            event = match.get('event', {})
            home_team = event.get('homeTeam', {}).get('name', 'N/A')
            away_team = event.get('awayTeam', {}).get('name', 'N/A')
            tournament = match.get('tournament', {})
            tournament_name = tournament.get('name', 'N/A')
            status = event.get('status', {})
            minute = status.get('minute', 0)
            event_id = event.get('id', 0)
            
            message = f"⚽ 0-0 al primo tempo!\n\n"
            message += f"🏠 {home_team} - {away_team} 🏠\n"
            message += f"📊 {tournament_name}\n"
            message += f"⏱️ Minuto: {minute}'\n"
            message += f"🔗 https://www.sofascore.com/event/{event_id}"
            
            return message
        except Exception as e:
            logger.error(f"Errore formattazione messaggio: {e}")
            return "Partita 0-0 al primo tempo rilevata!"
    
    async def check_matches(self):
        """Controlla partite live e invia notifiche"""
        try:
            live_matches = self.api.get_live_matches()
            logger.info(f"Trovate {len(live_matches)} partite live")
            
            for match in live_matches:
                try:
                    event = match.get('event', {})
                    event_id = event.get('id')
                    
                    if not event_id:
                        continue
                    
                    # Verifica se lega è monitorata
                    if not self.is_league_monitored(match):
                        continue
                    
                    # Verifica se è 0-0 al primo tempo
                    if not self.is_match_0_0_first_half(match):
                        # Rimuovi da active_matches se non è più 0-0
                        if event_id in self.active_matches:
                            del self.active_matches[event_id]
                        continue
                    
                    # Se già notificata, salta
                    if event_id in self.sent_matches:
                        continue
                    
                    # Invia notifica
                    message = self.format_match_notification(match)
                    await self.app.bot.send_message(
                        chat_id=CHAT_ID,
                        text=message
                    )
                    
                    # Salva come notificata
                    self.sent_matches.add(event_id)
                    self.active_matches[event_id] = {
                        'event_id': event_id,
                        'timestamp': datetime.now().isoformat(),
                        'match': match
                    }
                    
                    logger.info(f"Notifica inviata per partita {event_id}")
                    
                except Exception as e:
                    logger.error(f"Errore processamento partita: {e}")
                    continue
            
            # Salva stato
            save_json_file(SENT_MATCHES_FILE, list(self.sent_matches))
            save_json_file(ACTIVE_MATCHES_FILE, self.active_matches)
            
        except Exception as e:
            logger.error(f"Errore controllo partite: {e}")
    
    async def monitor_loop(self, context: ContextTypes.DEFAULT_TYPE):
        """Loop principale di monitoraggio (chiamato da job scheduler)"""
        try:
            await self.check_matches()
        except Exception as e:
            logger.error(f"Errore nel loop di monitoraggio: {e}")


# Handler comandi Telegram
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /start"""
    message = (
        "👋 Benvenuto nel bot 0-0 Monitor!\n\n"
        "Questo bot monitora partite live da SofaScore e ti notifica quando "
        "una partita è 0-0 al primo tempo nelle leghe selezionate.\n\n"
        "Usa /help per vedere tutti i comandi disponibili."
    )
    await update.message.reply_text(message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /help"""
    message = (
        "📖 Comandi disponibili:\n\n"
        "/start - Messaggio di benvenuto\n"
        "/help - Mostra questa guida\n"
        "/addLeague - Gestisci leghe da monitorare\n\n"
        "Il bot controlla automaticamente le partite ogni 60 secondi e "
        "ti invia una notifica quando rileva una partita 0-0 al primo tempo."
    )
    await update.message.reply_text(message)


async def add_league_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /addLeague - mostra interfaccia con checkbox"""
    try:
        api = SofaScoreAPI()
        tournaments = api.get_tournaments()
        
        if not tournaments:
            await update.message.reply_text(
                "❌ Errore: impossibile recuperare lista tornei da SofaScore."
            )
            return
        
        # Carica leghe monitorate
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await update.message.reply_text("❌ Errore: monitor non inizializzato.")
            return
        
        # Crea keyboard con checkbox
        keyboard = []
        row = []
        
        # Aggiungi leghe iniziali
        for league_id, league_info in INITIAL_LEAGUES.items():
            is_selected = "✅" if league_id in monitor.monitored_leagues else "☐"
            button_text = f"{is_selected} {league_info['name']}"
            callback_data = f"toggle_league:{league_id}"
            
            row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
            if len(row) == 1:  # Un pulsante per riga per leggibilità
                keyboard.append(row)
                row = []
        
        if row:
            keyboard.append(row)
        
        # Pulsante conferma
        keyboard.append([InlineKeyboardButton("✅ Conferma", callback_data="confirm_leagues")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📋 Seleziona le leghe da monitorare:\n\n"
            "Clicca su una lega per aggiungerla/rimuoverla dalla lista.",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Errore comando addLeague: {e}")
        await update.message.reply_text(f"❌ Errore: {e}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per callback query (checkbox leghe)"""
    query = update.callback_query
    await query.answer()
    
    try:
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await query.edit_message_text("❌ Errore: monitor non inizializzato.")
            return
        
        if query.data.startswith("toggle_league:"):
            league_id = query.data.split(":", 1)[1]
            
            # Toggle lega
            if league_id in monitor.monitored_leagues:
                monitor.monitored_leagues.remove(league_id)
            else:
                monitor.monitored_leagues.add(league_id)
            
            monitor.save_leagues()
            
            # Ricrea keyboard aggiornata
            keyboard = []
            for league_id_check, league_info in INITIAL_LEAGUES.items():
                is_selected = "✅" if league_id_check in monitor.monitored_leagues else "☐"
                button_text = f"{is_selected} {league_info['name']}"
                callback_data = f"toggle_league:{league_id_check}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            
            keyboard.append([InlineKeyboardButton("✅ Conferma", callback_data="confirm_leagues")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "📋 Seleziona le leghe da monitorare:\n\n"
                "Clicca su una lega per aggiungerla/rimuoverla dalla lista.",
                reply_markup=reply_markup
            )
        
        elif query.data == "confirm_leagues":
            count = len(monitor.monitored_leagues)
            await query.edit_message_text(
                f"✅ Configurazione salvata!\n\n"
                f"Leghe monitorate: {count}\n"
                f"Il bot monitorerà queste leghe per partite 0-0 al primo tempo."
            )
    
    except Exception as e:
        logger.error(f"Errore callback handler: {e}")
        await query.edit_message_text(f"❌ Errore: {e}")


def start_http_server(port: int):
    """Avvia HTTP server per keep-alive"""
    server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
    logger.info(f"HTTP server avviato su porta {port}")
    server.serve_forever()


async def main():
    """Funzione principale"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN non configurato!")
        return
    
    if not CHAT_ID:
        logger.error("CHAT_ID non configurato!")
        return
    
    # Crea applicazione Telegram
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Inizializza API e monitor
    api = SofaScoreAPI()
    monitor = MatchMonitor(api, application)
    application.bot_data['monitor'] = monitor
    
    # Registra handler
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addLeague", add_league_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Avvia HTTP server in thread separato
    http_thread = threading.Thread(target=start_http_server, args=(PORT,), daemon=True)
    http_thread.start()
    
    # Configura job scheduler per monitoraggio periodico
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            monitor.monitor_loop,
            interval=POLL_INTERVAL,
            first=10  # Inizia dopo 10 secondi
        )
        logger.info(f"Job scheduler configurato: controllo ogni {POLL_INTERVAL} secondi")
    
    # Avvia bot
    logger.info("Bot avviato!")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())

