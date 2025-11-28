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

# Leghe iniziali da monitorare (usando tournament_id quando disponibile)
# Formato: {tournament_id: {'name': 'Nome Lega', 'slug': 'slug-lega', 'country': 'Paese'}}
# Se tournament_id non disponibile, usa slug come chiave
INITIAL_LEAGUES = {
    # Leghe principali europee (tournament_id da verificare con API)
    'italy-serie-a': {'name': 'Serie A', 'slug': 'italy-serie-a', 'country': 'Italy', 'keywords': ['serie a', 'serie-a']},
    'italy-serie-b': {'name': 'Serie B', 'slug': 'italy-serie-b', 'country': 'Italy', 'keywords': ['serie b', 'serie-b']},
    'france-ligue-1': {'name': 'Ligue 1', 'slug': 'france-ligue-1', 'country': 'France', 'keywords': ['ligue 1', 'ligue-1']},
    'france-ligue-2': {'name': 'Ligue 2', 'slug': 'france-ligue-2', 'country': 'France', 'keywords': ['ligue 2', 'ligue-2']},
    'spain-la-liga': {'name': 'La Liga', 'slug': 'spain-la-liga', 'country': 'Spain', 'keywords': ['la liga', 'la-liga']},
    'spain-segunda': {'name': 'Segunda División', 'slug': 'spain-segunda-division', 'country': 'Spain', 'keywords': ['segunda', 'segunda division']},
    'germany-bundesliga': {'name': 'Bundesliga', 'slug': 'germany-bundesliga', 'country': 'Germany', 'keywords': ['bundesliga']},
    'germany-2-bundesliga': {'name': '2. Bundesliga', 'slug': 'germany-2-bundesliga', 'country': 'Germany', 'keywords': ['2. bundesliga', '2 bundesliga']},
    'england-premier-league': {'name': 'Premier League', 'slug': 'england-premier-league', 'country': 'England', 'keywords': ['premier league', 'premier-league']},
    'england-championship': {'name': 'Championship', 'slug': 'england-championship', 'country': 'England', 'keywords': ['championship']},
    'england-league-one': {'name': 'League One', 'slug': 'england-league-one', 'country': 'England', 'keywords': ['league one', 'league-1']},
    'england-league-two': {'name': 'League Two', 'slug': 'england-league-two', 'country': 'England', 'keywords': ['league two', 'league-2']},
    'netherlands': {'name': 'Eredivisie', 'slug': 'netherlands', 'country': 'Netherlands', 'keywords': ['eredivisie', 'netherlands']},
    # Altre leghe
    'switzerland': {'name': 'Super League', 'slug': 'switzerland', 'country': 'Switzerland', 'keywords': ['super league', 'switzerland']},
    'estonia': {'name': 'Meistriliiga', 'slug': 'estonia', 'country': 'Estonia', 'keywords': ['estonia', 'meistriliiga']},
    'hong-kong': {'name': 'Premier League', 'slug': 'hong-kong', 'country': 'Hong Kong', 'keywords': ['hong kong', 'hong-kong']},
    'luxembourg': {'name': 'National Division', 'slug': 'luxembourg', 'country': 'Luxembourg', 'keywords': ['luxembourg']},
    'qatar': {'name': 'Stars League', 'slug': 'qatar', 'country': 'Qatar', 'keywords': ['qatar']},
    'singapore': {'name': 'Premier League', 'slug': 'singapore', 'country': 'Singapore', 'keywords': ['singapore']},
    'vietnam': {'name': 'V.League 1', 'slug': 'vietnam', 'country': 'Vietnam', 'keywords': ['vietnam', 'v.league']},
    'norway-elite': {'name': 'Eliteserien', 'slug': 'norway-elite', 'country': 'Norway', 'keywords': ['eliteserien', 'norway elite']},
    'norway-obos': {'name': 'OBOS-ligaen', 'slug': 'norway-obos', 'country': 'Norway', 'keywords': ['obos', 'norway obos']},
    'iceland-urva': {'name': 'Úrvalsdeild', 'slug': 'iceland-urva', 'country': 'Iceland', 'keywords': ['urvalsdeild', 'iceland urva']},
    'iceland-incasso': {'name': '1. deild karla', 'slug': 'iceland-incasso', 'country': 'Iceland', 'keywords': ['1. deild', 'iceland incasso']},
}

# Configurazione logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class KeepAliveHandler(BaseHTTPRequestHandler):
    """HTTP Handler per keep-alive su Render.com"""
    
    def _send_health_response(self):
        """Invia risposta di health check"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        response = b'<html><body><h1>Bot is alive!</h1><p>0-0 Monitor Bot is running.</p></body></html>'
        self.wfile.write(response)
    
    def do_GET(self):
        """Gestisce richieste GET"""
        if self.path == '/health' or self.path == '/':
            self._send_health_response()
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_HEAD(self):
        """Gestisce richieste HEAD (usate da Render e servizi di ping)"""
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
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
        """Disabilita logging HTTP per ridurre spam"""
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


def _fetch_sofascore_json(url: str, headers: Dict) -> Optional[Dict]:
    """Tenta fetch diretto; su 403 usa fallback r.jina.ai come proxy pubblico."""
    now_utc = datetime.utcnow().isoformat() + "Z"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                logger.warning(f"[{now_utc}] ⚠️ JSON non valido dalla API diretta, lunghezza body={len(resp.text)}")
                return None
        if resp.status_code != 403:
            logger.warning(f"[{now_utc}] ⚠️ Errore API SofaScore: status={resp.status_code}")
            return None
        
        # Fallback via r.jina.ai (no crediti, spesso evita blocchi IP)
        inner = url.replace("https://", "http://")
        proxy_url = f"https://r.jina.ai/{inner}"
        logger.info(f"[{now_utc}] 🔁 Fallback via r.jina.ai: {proxy_url}")
        
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
                wrapper = prox_resp.json()
                # r.jina.ai restituisce un wrapper con data.content come stringa JSON
                if isinstance(wrapper, dict) and "data" in wrapper:
                    data_obj = wrapper.get("data", {})
                    if isinstance(data_obj, dict) and "content" in data_obj:
                        content_str = data_obj.get("content", "")
                        if isinstance(content_str, str) and content_str.strip().startswith("{"):
                            try:
                                return json.loads(content_str)
                            except Exception as e:
                                logger.warning(f"[{now_utc}] ⚠️ Errore parse JSON annidato da r.jina.ai: {e}")
                # Se non è il formato r.jina.ai, restituisci direttamente
                return wrapper
            except Exception:
                # Alcuni proxy restituiscono testo JSON valido: prova json.loads
                try:
                    return json.loads(prox_resp.text)
                except Exception:
                    logger.warning(f"[{now_utc}] ⚠️ Impossibile parsare JSON dal fallback")
                    return None
        logger.warning(f"[{now_utc}] ⚠️ Fallback r.jina.ai fallito: status={prox_resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"[{now_utc}] ⚠️ Eccezione fetch SofaScore: {e}")
        return None


class SofaScoreAPI:
    """Classe per interagire con SofaScore API"""
    
    def __init__(self, base_url: str = SOFASCORE_BASE):
        self.base_url = base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.sofascore.com/",
            "Origin": "https://www.sofascore.com"
        }
    
    def get_tournaments(self) -> List[Dict]:
        """Recupera lista di tutti i tornei disponibili"""
        try:
            url = f"{self.base_url}/unique-tournaments"
            data = _fetch_sofascore_json(url, self.headers)
            if data:
                return data.get('uniqueTournaments', [])
            return []
        except Exception as e:
            logger.error(f"Errore recupero tornei: {e}")
            return []
    
    def get_live_matches(self) -> List[Dict]:
        """Recupera tutte le partite live"""
        try:
            # Prova multipli endpoint per recuperare eventi live
            endpoints = [
                f"{self.base_url}/sport/football/events/live",
                f"{self.base_url}/sport/football/events/inplay",
                f"{self.base_url}/sport/football/livescore",
            ]
            
            for url in endpoints:
                data = _fetch_sofascore_json(url, self.headers)
                if not data:
                    continue
                
                # Normalizza le possibili chiavi
                events = data.get("events") or data.get("results") or []
                if events:
                    logger.info(f"Trovate {len(events)} partite live da {url}")
                    return events
            
            logger.warning("Nessun evento trovato su tutti gli endpoint live")
            return []
        except Exception as e:
            logger.error(f"Errore recupero partite live: {e}")
            return []
    
    def get_match_details(self, event_id: int) -> Optional[Dict]:
        """Recupera dettagli di una partita specifica"""
        try:
            url = f"{self.base_url}/event/{event_id}"
            return _fetch_sofascore_json(url, self.headers)
        except Exception as e:
            logger.error(f"Errore recupero dettagli partita {event_id}: {e}")
            return None


class MatchMonitor:
    """Classe per monitorare partite 0-0 al primo tempo"""
    
    def __init__(self, api: SofaScoreAPI, app: Application):
        self.api = api
        self.app = app
        
        # Carica sent_matches (supporta sia lista che dict)
        sent_data = load_json_file(SENT_MATCHES_FILE, [])
        if isinstance(sent_data, list):
            # Vecchio formato: lista di ID
            self.sent_matches: Set[int] = set(sent_data)
        else:
            # Nuovo formato: dict con ID come chiavi
            self.sent_matches: Set[int] = set(sent_data.keys() if isinstance(sent_data, dict) else [])
        
        self.active_matches: Dict[int, Dict] = load_json_file(ACTIVE_MATCHES_FILE, {})
        
        # Carica leghe monitorate (nuovo formato con dettagli)
        leagues_data = load_json_file(LEAGUES_FILE, {})
        if isinstance(leagues_data, dict) and 'monitored' in leagues_data:
            # Nuovo formato: dict con 'monitored' che contiene lista di dict con dettagli
            self.monitored_leagues: List[Dict] = leagues_data.get('monitored', [])
        elif isinstance(leagues_data, dict) and 'leagues' in leagues_data:
            # Vecchio formato: lista di ID/stringhe
            old_leagues = leagues_data.get('leagues', [])
            # Converti in nuovo formato
            self.monitored_leagues = []
            for league_id in old_leagues:
                if league_id in INITIAL_LEAGUES:
                    self.monitored_leagues.append({
                        'id': league_id,
                        'name': INITIAL_LEAGUES[league_id]['name'],
                        'slug': INITIAL_LEAGUES[league_id].get('slug', ''),
                        'country': INITIAL_LEAGUES[league_id].get('country', ''),
                        'tournament_id': None  # Da aggiornare quando disponibile
                    })
        else:
            # Nessuna configurazione: usa leghe iniziali
            self.monitored_leagues = []
            for league_id, league_info in INITIAL_LEAGUES.items():
                self.monitored_leagues.append({
                    'id': league_id,
                    'name': league_info['name'],
                    'slug': league_info.get('slug', ''),
                    'country': league_info.get('country', ''),
                    'tournament_id': None
                })
            self.save_leagues()
    
    def save_leagues(self):
        """Salva leghe monitorate in formato strutturato"""
        save_json_file(LEAGUES_FILE, {
            'monitored': self.monitored_leagues,
            'last_updated': datetime.now().isoformat()
        })
    
    def get_monitored_tournament_ids(self) -> Set[int]:
        """Restituisce set di tournament_id monitorati"""
        ids = set()
        for league in self.monitored_leagues:
            tournament_id = league.get('tournament_id')
            if tournament_id:
                ids.add(tournament_id)
        return ids
    
    def get_monitored_slugs(self) -> Set[str]:
        """Restituisce set di slug monitorati"""
        slugs = set()
        for league in self.monitored_leagues:
            slug = league.get('slug', '').lower()
            if slug:
                slugs.add(slug)
        return slugs
    
    def get_monitored_keywords(self) -> Set[str]:
        """Restituisce set di keywords monitorate"""
        keywords = set()
        for league in self.monitored_leagues:
            league_id = league.get('id', '')
            if league_id in INITIAL_LEAGUES:
                for kw in INITIAL_LEAGUES[league_id].get('keywords', []):
                    keywords.add(kw.lower())
        return keywords
    
    def is_match_0_0_first_half(self, match: Dict) -> bool:
        """Verifica se partita è 0-0 al primo tempo"""
        try:
            # Gestisce sia formato con 'event' che formato diretto
            event = match.get('event', match)
            
            # Estrai punteggio (sono oggetti con 'current' o 'display')
            score_home_obj = event.get('homeScore', {})
            score_away_obj = event.get('awayScore', {})
            
            if isinstance(score_home_obj, dict):
                home_score = score_home_obj.get('current', score_home_obj.get('display', 0))
            else:
                home_score = score_home_obj if score_home_obj is not None else 0
            
            if isinstance(score_away_obj, dict):
                away_score = score_away_obj.get('current', score_away_obj.get('display', 0))
            else:
                away_score = score_away_obj if score_away_obj is not None else 0
            
            # Deve essere 0-0
            if home_score != 0 or away_score != 0:
                return False
            
            # Verifica periodo e minuto
            status = event.get('status', {})
            time_obj = event.get('time', {})
            
            # Estrai periodo
            period = status.get('period', 0)
            status_desc = status.get('description', '').lower()
            status_code = status.get('code')
            
            # Determina periodo da status
            if '1st half' in status_desc or status_code == 6:
                period = 1
            elif '2nd half' in status_desc or status_code == 7:
                period = 2
            
            # Estrai minuto
            minute = None
            if isinstance(time_obj, dict):
                if 'currentPeriodStartTimestamp' in time_obj:
                    start_ts = time_obj.get('currentPeriodStartTimestamp')
                    if start_ts:
                        elapsed_seconds = datetime.now().timestamp() - start_ts
                        elapsed_minutes = int(elapsed_seconds / 60)
                        if period == 2:
                            minute = 45 + max(0, elapsed_minutes)
                        elif period == 1:
                            minute = max(0, elapsed_minutes)
                        else:
                            minute = max(0, elapsed_minutes)
            
            if minute is None:
                minute = status.get('minute', 0)
            
            # Primo tempo: periodo = 1 o minuto <= 45
            if period == 1 or (period == 0 and minute > 0 and minute <= 45):
                return True
            
            return False
        except Exception as e:
            logger.error(f"Errore verifica 0-0: {e}")
            return False
    
    def get_league_info_from_match(self, match: Dict) -> tuple:
        """Estrae informazioni lega da match (slug, nome, tournament_id)"""
        try:
            tournament = match.get('tournament', {})
            unique_tournament = tournament.get('uniqueTournament', {})
            slug = unique_tournament.get('slug', '').lower() if unique_tournament else ''
            name = unique_tournament.get('name', '').lower() if unique_tournament else ''
            tournament_id = unique_tournament.get('id') if unique_tournament else None
            return (slug, name, tournament_id)
        except:
            return (None, None, None)
    
    def is_league_monitored(self, match: Dict) -> bool:
        """Verifica se la lega della partita è monitorata usando tournament_id, slug o keywords"""
        slug, name, tournament_id = self.get_league_info_from_match(match)
        
        if not slug and not name and not tournament_id:
            return False
        
        # 1. Match per tournament_id (più affidabile)
        if tournament_id:
            monitored_ids = self.get_monitored_tournament_ids()
            if tournament_id in monitored_ids:
                return True
        
        # 2. Match per slug
        if slug:
            monitored_slugs = self.get_monitored_slugs()
            for monitored_slug in monitored_slugs:
                if slug == monitored_slug or slug.startswith(monitored_slug) or monitored_slug in slug:
                    return True
        
        # 3. Match per keywords nel nome
        if name:
            monitored_keywords = self.get_monitored_keywords()
            name_lower = name.lower()
            for keyword in monitored_keywords:
                if keyword in name_lower:
                    # Verifica che sia un match valido (non troppo generico)
                    if len(keyword) > 3:  # Evita match troppo generici
                        return True
        
        # 4. Match specifici per leghe note (fallback)
        for league in self.monitored_leagues:
            league_id = league.get('id', '')
            if league_id in INITIAL_LEAGUES:
                league_info = INITIAL_LEAGUES[league_id]
                league_name = league_info['name'].lower()
                
                # Match esatto per nome
                if name and league_name in name or name in league_name:
                    return True
                
                # Match per keywords specifiche
                for keyword in league_info.get('keywords', []):
                    if keyword.lower() in name:
                        return True
        
        return False
    
    def format_match_notification(self, match: Dict) -> str:
        """Formatta messaggio notifica partita"""
        try:
            # Gestisce sia formato con 'event' che formato diretto
            event = match.get('event', match)
            
            home_team_obj = event.get('homeTeam', {})
            away_team_obj = event.get('awayTeam', {})
            home_team = home_team_obj.get('name', 'N/A') if isinstance(home_team_obj, dict) else str(home_team_obj)
            away_team = away_team_obj.get('name', 'N/A') if isinstance(away_team_obj, dict) else str(away_team_obj)
            
            tournament = match.get('tournament', {})
            tournament_name = tournament.get('name', 'N/A') if isinstance(tournament, dict) else 'N/A'
            
            status = event.get('status', {})
            time_obj = event.get('time', {})
            
            # Estrai minuto
            minute = 0
            if isinstance(time_obj, dict) and 'currentPeriodStartTimestamp' in time_obj:
                start_ts = time_obj.get('currentPeriodStartTimestamp')
                if start_ts:
                    elapsed_seconds = datetime.now().timestamp() - start_ts
                    minute = int(elapsed_seconds / 60)
            
            if minute == 0:
                minute = status.get('minute', 0)
            
            event_id = event.get('id', 0)
            
            message = f"⚽ 0-0 al primo tempo!\n\n"
            message += f"🏠 {home_team} - {away_team} 🏠\n"
            message += f"📊 {tournament_name}\n"
            message += f"⏱️ Minuto: {minute}'\n"
            if event_id:
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
            
            # Salva stato (sent_matches come lista per compatibilità)
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
        "/addLeague - Gestisci leghe da monitorare\n"
        "/leagues - Mostra leghe attualmente monitorate\n"
        "/chatid - Mostra il CHAT_ID di questa chat/gruppo\n"
        "/stats - Statistiche notifiche inviate\n"
        "/status - Stato del bot\n\n"
        "Il bot controlla automaticamente le partite ogni 60 secondi e "
        "ti invia una notifica quando rileva una partita 0-0 al primo tempo."
    )
    await update.message.reply_text(message)


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /chatid - mostra CHAT_ID della chat corrente"""
    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    
    if chat_type == 'private':
        message = f"📱 CHAT_ID (Chat Privata):\n`{chat_id}`\n\nCopia questo valore nella variabile d'ambiente CHAT_ID"
    elif chat_type == 'group' or chat_type == 'supergroup':
        message = (
            f"👥 CHAT_ID (Gruppo):\n`{chat_id}`\n\n"
            f"⚠️ Nota: I CHAT_ID dei gruppi sono numeri negativi.\n"
            f"Copia questo valore nella variabile d'ambiente CHAT_ID.\n\n"
            f"Tipo: {chat_type}\n"
            f"Nome gruppo: {chat.title if hasattr(chat, 'title') else 'N/A'}"
        )
    else:
        message = f"CHAT_ID: `{chat_id}`\nTipo: {chat_type}"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def leagues_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /leagues - mostra leghe monitorate"""
    monitor = context.bot_data.get('monitor')
    if not monitor:
        await update.message.reply_text("❌ Errore: monitor non inizializzato.")
        return
    
    if not monitor.monitored_leagues:
        await update.message.reply_text("📋 Nessuna lega configurata. Usa /addLeague per aggiungere leghe.")
        return
    
    lines = [f"📋 Leghe monitorate ({len(monitor.monitored_leagues)}):\n"]
    
    for i, league in enumerate(monitor.monitored_leagues, 1):
        name = league.get('name', 'N/A')
        country = league.get('country', '')
        tournament_id = league.get('tournament_id')
        
        country_str = f" ({country})" if country else ""
        id_str = f" [ID: {tournament_id}]" if tournament_id else ""
        
        lines.append(f"{i}. {name}{country_str}{id_str}")
    
    await update.message.reply_text("\n".join(lines))


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /stats - mostra statistiche"""
    monitor = context.bot_data.get('monitor')
    if not monitor:
        await update.message.reply_text("❌ Errore: monitor non inizializzato.")
        return
    
    total_sent = len(monitor.sent_matches)
    active_tracking = len(monitor.active_matches)
    monitored_leagues = len(monitor.monitored_leagues)
    
    message = (
        f"📊 Statistiche Bot:\n\n"
        f"✅ Notifiche inviate: {total_sent}\n"
        f"🔍 Partite in tracking: {active_tracking}\n"
        f"📋 Leghe monitorate: {monitored_leagues}\n"
        f"⏱️ Intervallo controllo: {POLL_INTERVAL} secondi"
    )
    
    await update.message.reply_text(message)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /status - mostra stato del bot"""
    message = (
        f"🤖 Stato Bot:\n\n"
        f"✅ Bot attivo e funzionante\n"
        f"⏱️ Controlla partite ogni {POLL_INTERVAL} secondi\n"
        f"🌐 HTTP server: Porta {PORT}\n"
        f"📡 API SofaScore: {SOFASCORE_BASE}\n\n"
        f"Usa /help per vedere tutti i comandi disponibili."
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


def main():
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
    application.add_handler(CommandHandler("leagues", leagues_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Avvia HTTP server in thread separato
    http_thread = threading.Thread(target=start_http_server, args=(PORT,), daemon=True)
    http_thread.start()
    
    # Configura job scheduler per monitoraggio periodico
    # Usa post_init per configurare dopo che l'applicazione è inizializzata
    async def post_init(app: Application) -> None:
        """Callback chiamato dopo l'inizializzazione dell'applicazione"""
        job_queue = app.job_queue
        if job_queue:
            job_queue.run_repeating(
                monitor.monitor_loop,
                interval=POLL_INTERVAL,
                first=10  # Inizia dopo 10 secondi
            )
            logger.info(f"Job scheduler configurato: controllo ogni {POLL_INTERVAL} secondi")
        else:
            logger.warning("JobQueue non disponibile - monitoraggio periodico disabilitato")
    
    application.post_init = post_init
    
    # Avvia bot
    logger.info("Bot avviato!")
    # run_polling gestisce l'event loop internamente (non è async)
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == '__main__':
    import sys
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot fermato dall'utente")
    except Exception as e:
        logger.error(f"Errore fatale: {e}")
        sys.exit(1)

