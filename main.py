# ============================================================
# WHALE HUNTER v17.0 - COM GMGN API OFICIAL
# ============================================================
import os
import time
import threading
import requests
import telebot
from flask import Flask
from queue import Queue, Empty
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base58
import json
import hmac
import hashlib

# ============================================================
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

GMGN_API_KEY = os.getenv("GMGN_API_KEY")
GMGN_PRIVATE_KEY = os.getenv("GMGN_PRIVATE_KEY")

app = Flask(__name__)

# ============================================================
# SESSION
# ============================================================
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.4,
                status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ============================================================
# CONFIGURAÇÕES
# ============================================================
SCAN_DELAY = 30
REPORT_INTERVAL = 7200

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
top_traders = []
tracked_tokens = {}
stats = {"alerts": 0}
tg_queue = Queue()

# ============================================================
# FUNÇÕES TELEGRAM
# ============================================================
def tg_worker():
    while True:
        try:
            msg = tg_queue.get(timeout=5)
            for _ in range(3):
                try:
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                                     disable_web_page_preview=True)
                    break
                except Exception as e:
                    print(f"[TG] {e}")
                    time.sleep(1)
        except Empty:
            continue

def send(msg):
    try:
        tg_queue.put_nowait(msg)
    except:
        pass

# ============================================================
# GMGN API (AUTENTICADA)
# ============================================================
def gmgn_api_request(endpoint, method="GET", data=None):
    """Faz requisição autenticada para a API da GMGN"""
    try:
        url = f"https://api.gmgn.ai{endpoint}"
        timestamp = str(int(time.time() * 1000))
        
        headers = {
            "X-APIKEY": GMGN_API_KEY,
            "X-TIMESTAMP": timestamp,
            "Content-Type": "application/json"
        }
        
        if method == "POST":
            payload = json.dumps(data) if data else ""
            signature = hmac.new(
                GMGN_PRIVATE_KEY.encode(),
                f"{timestamp}{payload}".encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-SIGNATURE"] = signature
            response = session.post(url, headers=headers, json=data, timeout=10)
        else:
            response = session.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[GMGN] Erro {response.status_code}: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"[GMGN] Exceção: {e}")
        return None

def get_top_traders():
    """Busca os top traders da GMGN"""
    endpoint = "/v1/rank/sol/traders"
    return gmgn_api_request(endpoint)

def get_trader_activity(wallet_addr):
    """Obtém atividades recentes de uma wallet"""
    endpoint = f"/v1/wallet/sol/{wallet_addr}/activities"
    return gmgn_api_request(endpoint)

def get_token_info(token_addr):
    """Obtém informações do token"""
    endpoint = f"/v1/token/sol/{token_addr}"
    return gmgn_api_request(endpoint)

# ============================================================
# IDENTIFICAR TOP TRADERS (VIA GMGN)
# ============================================================
def identify_top_traders():
    """Identifica os principais traders via API GMGN"""
    global top_traders, stats
    
    print("[UPDATE] Buscando top traders via GMGN API...")
    send("🔄 *Atualizando lista de Top Traders*")
    
    try:
        result = get_top_traders()
        if not result or "data" not in result:
            print("[UPDATE] Falha ao buscar top traders")
            return
        
        traders = result.get("data", [])
        if not traders:
            print("[UPDATE] Nenhum trader encontrado")
            return
        
        # Pega os 10 melhores
        with lock:
            top_traders = traders[:10]
            stats["traders_found"] = len(top_traders)
        
        send(f"📋 *TOP TRADERS IDENTIFICADOS*\n\n"
             f"Encontrados {len(top_traders)} traders:\n"
             + "\n".join([f"🐋 `{t.get('address', 'N/A')[:8]}...{t.get('address', 'N/A')[-8:]}`" for t in top_traders[:5]]) +
             f"\n\n⏰ Atualizado em {datetime.now().strftime('%H:%M')}")
        
        print(f"[UPDATE] Top traders: {len(top_traders)} encontrados")
        
    except Exception as e:
        print(f"[UPDATE] Erro: {e}")

# ============================================================
# MONITORAR TRADERS
# ============================================================
def monitor_traders():
    """Monitora as atividades dos top traders"""
    while True:
        try:
            with lock:
                traders = top_traders.copy()
            
            if not traders:
                identify_top_traders()
                time.sleep(30)
                continue
            
            for trader in traders:
                addr = trader.get("address")
                if not addr:
                    continue
                
                # Busca atividades recentes
                activities = get_trader_activity(addr)
                if not activities or "data" not in activities:
                    continue
                
                for activity in activities.get("data", []):
                    if activity.get("type") != "buy":
                        continue
                    
                    token_addr = activity.get("token_address")
                    if not token_addr:
                        continue
                    
                    # Verifica se já alertou este token
                    with lock:
                        if token_addr in tracked_tokens:
                            continue
                        tracked_tokens[token_addr] = time.time()
                    
                    # Busca informações do token
                    token_info = get_token_info(token_addr)
                    if not token_info:
                        continue
                    
                    token_data = token_info.get("data", {})
                    symbol = token_data.get("symbol", "???")
                    price = token_data.get("price", 0)
                    
                    # Envia alerta
                    msg = (
                        f"🐋 *TOP TRADER COMPROU!*\n\n"
                        f"Trader: `{addr[:8]}...{addr[-8:]}`\n"
                        f"💎 *${symbol}*\n"
                        f"`{token_addr[:8]}...{token_addr[-8:]}`\n\n"
                        f"💲 Preço: `${price:.8f}`\n"
                        f"👥 Holders: `{token_data.get('holder_count', 0)}`\n"
                        f"🧠 Smart Money: `{token_data.get('smart_degen_count', 0)}`\n\n"
                        f"🔍 GMGN: https://gmgn.ai/sol/token/{token_addr}\n"
                        f"📊 DEX: https://dexscreener.com/solana/{token_addr}\n\n"
                        f"⚠️ *MODO MANUAL* - Analise antes de comprar"
                    )
                    
                    send(msg)
                    stats["alerts"] += 1
                    print(f"[ALERTA] {symbol} - Trader: {addr[:8]}...")
                    
                time.sleep(1)
            
            time.sleep(SCAN_DELAY)
            
        except Exception as e:
            print(f"[MONITOR] Erro: {e}")
            time.sleep(10)

# ============================================================
# RELATÓRIO
# ============================================================
def relatorio():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                alerts = stats["alerts"]
                traders = stats.get("traders_found", 0)
            
            txt = (
                f"📊 *RELATÓRIO 2H*\n\n"
                f"🐋 Traders monitorados: `{traders}`\n"
                f"📈 Alertas enviados: `{alerts}`\n\n"
                f"✅ GMGN API conectada\n"
                f"🔍 Monitorando compras dos top traders"
            )
            send(txt)
        except Exception as e:
            print(f"[REL] {e}")
        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH
# ============================================================
@app.route("/")
def health():
    with lock:
        traders = len(top_traders)
    return f"GMGN BOT | traders={traders} | alerts={stats['alerts']}"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v17.0 (GMGN API) ===")
    
    if not GMGN_API_KEY or not GMGN_PRIVATE_KEY:
        send("⚠️ *ERRO: Variáveis GMGN_API_KEY e GMGN_PRIVATE_KEY não configuradas!*")
        print("ERRO: Variáveis GMGN_API_KEY e GMGN_PRIVATE_KEY não configuradas!")
    else:
        send("🟢 *WHALE HUNTER v17.0 ONLINE*\n\n"
             "🐋 *GMGN API CONECTADA*\n"
             "🔍 Monitorando top traders em tempo real\n"
             "📝 Alertas quando eles compram\n\n"
             "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
        
        identify_top_traders()
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
