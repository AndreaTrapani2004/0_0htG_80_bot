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
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Set, Optional

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import Conflict, NetworkError

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


def normalize_country_name(name: str) -> str:
    """Normalizza nome stato (gestisce italiano -> inglese per SofaScore)"""
    if not name:
        return ""
    name = name.strip().lower()
    aliases = {
        "italia": "italy",
        "inghilterra": "england",
        "francia": "france",
        "spagna": "spain",
        "germania": "germany",
        "olanda": "netherlands",
        "paesi bassi": "netherlands",
        "svizzera": "switzerland",
        "norvegia": "norway",
        "islanda": "iceland",
        "lussemburgo": "luxembourg",
        "qatar": "qatar",
        "singapore": "singapore",
        "vietnam": "vietnam",
        "estonia": "estonia",
        "hong kong": "hong kong",
    }
    return aliases.get(name, name)


def normalize_league_name(name: str) -> str:
    """Normalizza nome lega (minuscolo, rimuove spazi extra)"""
    if not name:
        return ""
    name = " ".join(name.strip().lower().split())
    # Alcune normalizzazioni comuni
    replacements = {
        "serie a": "serie a",
        "serie b": "serie b",
        "liga 1": "ligue 1",
        "liga 2": "ligue 2",
    }
    return replacements.get(name, name)


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
    
    def get_tournaments(self, sport_id: int = 1) -> List[Dict]:
        """Recupera lista di tutti i tornei disponibili per il calcio (sport_id=1)"""
        try:
            # Prova multipli endpoint
            endpoints = [
                f"{self.base_url}/sport/football/unique-tournaments",
                f"{self.base_url}/unique-tournaments",
                f"{self.base_url}/sport/{sport_id}/unique-tournaments",
            ]
            
            for url in endpoints:
                data = _fetch_sofascore_json(url, self.headers)
                if not data:
                    continue
                
                # Prova diverse chiavi possibili
                tournaments = (
                    data.get('uniqueTournaments') or 
                    data.get('tournaments') or 
                    data.get('results') or 
                    []
                )
                
                if tournaments:
                    logger.info(f"Trovati {len(tournaments)} tornei da {url}")
                    return tournaments
            
            logger.warning("Nessun torneo trovato su tutti gli endpoint")
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
        else:
            # Nessuna configurazione o vecchio formato: inizia con lista vuota
            self.monitored_leagues = []
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
        """Verifica se la lega della partita è monitorata confrontando nome lega e stato"""
        try:
            tournament = match.get('tournament', {})
            unique_tournament = tournament.get('uniqueTournament', {})
            tournament_name = unique_tournament.get('name', tournament.get('name', '')).lower()
            category = tournament.get('category', {})
            country_name = category.get('name', '').lower() if isinstance(category, dict) else ''
            full_name = f"{tournament_name} - {country_name}".lower()
            
            # Se abbiamo tournament_id configurato, usalo come primo filtro
            unique_id = unique_tournament.get('id')
            if unique_id:
                monitored_ids = self.get_monitored_tournament_ids()
                if unique_id in monitored_ids:
                    return True
            
            # Match per nome lega e stato normalizzati
            for league in self.monitored_leagues:
                country_norm = league.get('country_norm') or normalize_country_name(league.get('country_input', '') or league.get('country', ''))
                league_norm = league.get('league_norm') or normalize_league_name(league.get('league_input', '') or league.get('name', ''))
                
                if not country_norm or not league_norm:
                    continue
                
                if country_norm in full_name and league_norm in full_name:
                    # Aggiorna tournament_id se non presente ma disponibile
                    if unique_id and not league.get('tournament_id'):
                        league['tournament_id'] = unique_id
                        self.save_leagues()
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Errore verifica lega monitorata: {e}")
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
                    
                    # Verifica se lega è monitorata (e aggiorna tournament_id se trovato)
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
        "/addLeague - Aggiungi nuova lega (stato + nome lega)\n"
        "/deleteLeague - Rimuovi leghe dalla lista\n"
        "/leagues - Mostra leghe attualmente monitorate\n"
        "/testMatch <event_id|url> - Testa se una partita appartiene a una lega monitorata\n"
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
        country_in = league.get('country_input', league.get('country', ''))
        league_in = league.get('league_input', league.get('name', 'N/A'))
        country_norm = league.get('country_norm', '')
        league_norm = league.get('league_norm', '')
        tournament_id = league.get('tournament_id')
        
        norm_str = f" → {league_norm} - {country_norm}" if league_norm or country_norm else ""
        id_str = f" [tournament_id: {tournament_id}]" if tournament_id else ""
        
        lines.append(f"{i}. {league_in} - {country_in}{norm_str}{id_str}")
    
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


async def test_match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Testa se una partita SofaScore appartiene a una lega monitorata"""
    try:
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await update.message.reply_text("❌ Errore: monitor non inizializzato.")
            return
        
        text = update.message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await update.message.reply_text(
                "Uso: /testMatch <event_id oppure URL SofaScore>\n\n"
                "Esempi:\n"
                "/testMatch 1234567\n"
                "/testMatch https://www.sofascore.com/event/1234567"
            )
            return
        
        arg = parts[1].strip()
        
        # Estrai event_id da URL o stringa
        m = re.search(r"/event/(\\d+)", arg)
        if m:
            event_id_str = m.group(1)
        else:
            m = re.search(r"\\d+", arg)
            if not m:
                await update.message.reply_text("❌ Impossibile estrarre un event_id valido dall'input.")
                return
            event_id_str = m.group(0)
        
        try:
            event_id = int(event_id_str)
        except ValueError:
            await update.message.reply_text("❌ event_id non valido.")
            return
        
        api = SofaScoreAPI()
        details = api.get_match_details(event_id)
        if not details or 'event' not in details:
            await update.message.reply_text("❌ Impossibile recuperare dettagli della partita da SofaScore.")
            return
        
        event = details.get('event', {})
        tournament = event.get('tournament', {})
        unique_tournament = tournament.get('uniqueTournament', {})
        category = tournament.get('category', {})
        
        tournament_name = unique_tournament.get('name', tournament.get('name', 'N/A'))
        country_name = category.get('name', 'N/A') if isinstance(category, dict) else 'N/A'
        unique_id = unique_tournament.get('id')
        
        full_name = f"{tournament_name} - {country_name}"
        
        # Verifica se la partita sarebbe considerata in lega monitorata
        is_monitored = monitor.is_league_monitored({'tournament': tournament})
        
        # Prepara info sulle leghe monitorate
        monitored_lines = []
        for league in monitor.monitored_leagues[:10]:
            country_in = league.get('country_input', league.get('country', ''))
            league_in = league.get('league_input', league.get('name', 'N/A'))
            country_norm = league.get('country_norm', '')
            league_norm = league.get('league_norm', '')
            tid = league.get('tournament_id')
            norm_str = f" ({league_norm} - {country_norm})" if league_norm or country_norm else ""
            id_str = f" [tid:{tid}]" if tid else ""
            monitored_lines.append(f"• {league_in} - {country_in}{norm_str}{id_str}")
        
        if len(monitor.monitored_leagues) > 10:
            monitored_lines.append(f"• ... e altre {len(monitor.monitored_leagues) - 10} leghe")
        
        msg = (
            f"🔍 Test match SofaScore\n\n"
            f"Event ID: `{event_id}`\n"
            f"Torneo: *{tournament_name}* - *{country_name}*\n"
            f"Full: `{full_name}`\n"
            f"uniqueTournament.id: `{unique_id}`\n\n"
            f"👉 Appartiene a lega monitorata? {'✅ Sì' if is_monitored else '❌ No'}\n\n"
            f"📋 Leghe monitorate (prime 10):\n" +
            ("\n".join(monitored_lines) if monitored_lines else "Nessuna lega configurata.")
        )
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Errore test_match_command: {e}")
        await update.message.reply_text(f"❌ Errore: {e}")


async def add_league_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler comando /addLeague - flusso interattivo: stato -> nome lega"""
    try:
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await update.message.reply_text("❌ Errore: monitor non inizializzato.")
            return
        
        # Inizia flusso interattivo
        context.user_data['add_league_state'] = 'await_country'
        context.user_data.pop('add_league_country', None)
        await update.message.reply_text(
            "🌍 Inserisci lo **stato** della lega che vuoi aggiungere.\n"
            "Esempi: `Italia`, `Inghilterra`, `Francia`, `Germany`...",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Errore comando addLeague: {e}")
        await update.message.reply_text(f"❌ Errore: {e}")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce input testuali per flusso /addLeague"""
    try:
        state = context.user_data.get('add_league_state')
        if not state:
            # Nessun flusso attivo, ignora
            return
        
        text = (update.message.text or "").strip()
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await update.message.reply_text("❌ Errore: monitor non inizializzato.")
            context.user_data.pop('add_league_state', None)
            return
        
        # Step 1: stato
        if state == 'await_country':
            country_input = text
            country_norm = normalize_country_name(country_input)
            if not country_norm:
                await update.message.reply_text("❌ Stato non valido. Riprova.")
                return
            
            context.user_data['add_league_country'] = {
                'input': country_input,
                'norm': country_norm
            }
            context.user_data['add_league_state'] = 'await_league'
            await update.message.reply_text(
                f"✅ Stato impostato su: *{country_input}* → `{country_norm}`\n\n"
                "Ora inserisci il **nome del campionato**.\n"
                "Esempi: `Serie A`, `Serie B`, `Premier League`, `Ligue 1`...",
                parse_mode='Markdown'
            )
            return
        
        # Step 2: nome lega
        if state == 'await_league':
            league_input = text
            league_norm = normalize_league_name(league_input)
            if not league_norm:
                await update.message.reply_text("❌ Nome lega non valido. Riprova.")
                return
            
            country_data = context.user_data.get('add_league_country')
            if not country_data:
                await update.message.reply_text("❌ Errore interno. Riprova /addLeague.")
                context.user_data.pop('add_league_state', None)
                return
            
            country_input = country_data['input']
            country_norm = country_data['norm']
            
            # Crea ID unico
            league_id = f"{country_norm.replace(' ', '_')}-{league_norm.replace(' ', '_')}"
            
            # Verifica se già esiste
            for league in monitor.monitored_leagues:
                if league.get('id') == league_id:
                    await update.message.reply_text(
                        "ℹ️ Questa lega è già presente nella lista monitorata.\n"
                        f"Stato: *{country_input}* → `{country_norm}`\n"
                        f"Lega: *{league_input}* → `{league_norm}`",
                        parse_mode='Markdown'
                    )
                    context.user_data.pop('add_league_state', None)
                    context.user_data.pop('add_league_country', None)
                    return
            
            # Aggiungi lega
            monitor.monitored_leagues.append({
                'id': league_id,
                'country_input': country_input,
                'league_input': league_input,
                'country_norm': country_norm,
                'league_norm': league_norm,
                'tournament_id': None
            })
            monitor.save_leagues()
            
            context.user_data.pop('add_league_state', None)
            context.user_data.pop('add_league_country', None)
            
            await update.message.reply_text(
                "✅ Lega aggiunta alla lista monitorata!\n\n"
                f"Stato: *{country_input}* → `{country_norm}`\n"
                f"Lega: *{league_input}* → `{league_norm}`\n\n"
                "Il bot inizierà a monitorare le partite 0-0 al primo tempo in questa lega.",
                parse_mode='Markdown'
            )
            return
    except Exception as e:
        logger.error(f"Errore text_message_handler: {e}")
        await update.message.reply_text(f"❌ Errore: {e}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler per callback query (checkbox leghe, paginazione eliminazione)"""
    query = update.callback_query
    await query.answer()
    
    try:
        monitor = context.bot_data.get('monitor')
        if not monitor:
            await query.edit_message_text("❌ Errore: monitor non inizializzato.")
            return
        
        # Per ora non ci sono callback specifici per deleteLeague;
        # il supporto per checkbox di cancellazione può essere aggiunto qui in futuro.
        await query.answer("⚠️ Nessuna azione associata a questo pulsante.", show_alert=True)
    
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
    
    # Registra handler comandi
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("addLeague", add_league_command))
    application.add_handler(CommandHandler("deleteLeague", delete_league_command))
    application.add_handler(CommandHandler("leagues", leagues_command))
    application.add_handler(CommandHandler("testMatch", test_match_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Handler per input testuali dei flussi interattivi
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, delete_league_text_handler))
    
    # Gestione errori (ignora Conflict e NetworkError)
    def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Gestisce errori durante l'elaborazione degli update"""
        error = context.error
        if isinstance(error, Conflict):
            # Ignora silenziosamente errori Conflict (più istanze in esecuzione)
            logger.debug(f"Conflict ignorato: {error}")
            return
        elif isinstance(error, NetworkError):
            # Ignora silenziosamente errori di rete temporanei
            logger.debug(f"NetworkError ignorato: {error}")
            return
        else:
            # Log altri errori
            logger.error(f"Errore durante elaborazione update: {error}", exc_info=error)
    
    application.add_error_handler(error_handler)
    
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

