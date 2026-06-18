# ============================================================
# WHALE HUNTER v12.0 - COPY TRADING DINÂMICO
# ============================================================
# - Encontra automaticamente os TOP 5 TRADERS do momento
# - Atualiza a lista a cada 10 minutos
# - Copia as compras dos traders identificados
# - Entrada com 0.01 SOL por trade
# - Saída automática quando eles vendem
# ============================================================

import os
import time
import threading
import requests
import json
import telebot
from flask import Flask
from queue import Queue, Empty
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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

# ============================================================
# FLASK
# ============================================================
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
# CONFIGURAÇÕES DE TRADING
# ============================================================
SCAN_DELAY = 3  # Verificar a cada 3 segundos
REPORT_INTERVAL = 7200  # 2 horas
TOP_TRADERS_UPDATE_INTERVAL = 600  # Atualizar top traders a cada 10 minutos
TOP_TRADERS_COUNT = 5  # Manter os 5 melhores

# Configurações de trade
TRADE_AMOUNT_SOL = 0.01  # 0.01 SOL por trade
SLIPPAGE = 15

# Filtros anti-rug
MIN_LIQ = 3000
MAX_TOP10 = 40
MAX_DEV_HOLD = 20
MAX_TAX = 25

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
top_traders = []  # Lista atualizada dos melhores traders
trader_positions = {}  # Posições ativas
executed_trades = {}  # Trades já executados
trader_cache = {}  # Cache de traders para não repetir consultas
stats = {"trades": 0, "profits": 0, "losses": 0}
tg_queue = Queue()
last_update = 0

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
# GMGN API (Autenticada)
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
            return None
            
    except Exception as e:
        print(f"[GMGN] Exceção: {e}")
        return None

def get_trending_tokens():
    """Obtém tokens em alta no momento"""
    endpoint = "/v1/rank/sol/trending"
    return gmgn_api_request(endpoint)

def get_token_top_traders(token_addr):
    """Obtém os melhores traders de um token específico"""
    endpoint = f"/v1/token/sol/{token_addr}/top_traders"
    return gmgn_api_request(endpoint)

def get_trader_activity(wallet_addr):
    """Obtém atividades recentes de uma wallet"""
    endpoint = f"/v1/wallet/sol/{wallet_addr}/activities"
    return gmgn_api_request(endpoint)

def get_token_info(addr):
    """Obtém informações detalhadas do token"""
    endpoint = f"/v1/token/sol/{addr}"
    return gmgn_api_request(endpoint)

def execute_swap(token_address, amount_sol, slippage=15):
    """Executa swap via GMGN"""
    endpoint = "/v1/swap"
    data = {
        "fromToken": "So11111111111111111111111111111111111111112",
        "toToken": token_address,
        "amount": str(amount_sol),
        "slippage": slippage,
        "chain": "solana"
    }
    return gmgn_api_request(endpoint, "POST", data)

# ============================================================
# ANÁLISE RÁPIDA DO TOKEN
# ============================================================
def quick_token_analysis(token_info):
    """Análise rápida para verificar se o token é lixo"""
    if not token_info:
        return False, "Dados não disponíveis"
    
    data = token_info.get("data", {})
    
    if data.get("is_honeypot", False):
        return False, "HONEYPOT"
    
    tax = data.get("sell_tax", 0)
    if tax > MAX_TAX:
        return False, f"TAXA {tax}%"
    
    top10 = data.get("top10_holder_rate", 0)
    if top10:
        pct = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if pct > MAX_TOP10:
            return False, f"TOP10 {pct:.0f}%"
    
    dev = data.get("creator_hold_percent", 0)
    if dev and float(dev) > MAX_DEV_HOLD:
        return False, f"DEV {dev:.0f}%"
    
    if data.get("rug_ratio", 0) > 0.7:
        return False, "RUG"
    
    liq = data.get("liquidity_usd", 0)
    if liq and liq < MIN_LIQ:
        return False, f"LIQ BAIXA ${liq:.0f}"
    
    return True, "OK"

# ============================================================
# ENCONTRAR TOP TRADERS DINAMICAMENTE
# ============================================================
def find_top_traders():
    """Encontra os melhores traders do momento"""
    global top_traders, last_update
    
    print("[UPDATE] Buscando top traders...")
    
    try:
        # 1. Busca tokens em alta
        trending = get_trending_tokens()
        if not trending:
            print("[UPDATE] Falha ao buscar trending tokens")
            return
        
        tokens = trending.get("data", {}).get("rank", [])
        if not tokens:
            print("[UPDATE] Nenhum token em alta encontrado")
            return
        
        print(f"[UPDATE] Encontrados {len(tokens)} tokens em alta")
        
        # 2. Para cada token, busca os top traders
        trader_scores = {}
        tokens_analisados = 0
        
        for token in tokens[:20]:  # Analisa os 20 primeiros
            token_addr = token.get("address")
            if not token_addr:
                continue
                
            top_traders_data = get_token_top_traders(token_addr)
            if not top_traders_data:
                continue
                
            traders = top_traders_data.get("data", [])
            for trader in traders[:10]:  # Pega os 10 melhores de cada token
                addr = trader.get("address")
                profit = trader.get("profit", 0)
                
                if addr:
                    # Acumula pontuação baseada no lucro
                    if addr not in trader_scores:
                        trader_scores[addr] = 0
                    trader_scores[addr] += profit
            
            tokens_analisados += 1
            time.sleep(0.3)  # Pequena pausa para não sobrecarregar
        
        # 3. Ordena traders por pontuação
        sorted_traders = sorted(trader_scores.items(), key=lambda x: x[1], reverse=True)
        
        # 4. Pega os TOP 5
        new_top_traders = [addr for addr, score in sorted_traders[:TOP_TRADERS_COUNT]]
        
        if new_top_traders:
            with lock:
                top_traders = new_top_traders
                last_update = time.time()
            
            send(f"📋 *TOP TRADERS ATUALIZADOS*\n\n"
                 f"Novos top traders encontrados:\n"
                 + "\n".join([f"`{t[:8]}...{t[-8:]}`" for t in top_traders]) +
                 f"\n\n🔄 Baseado em {tokens_analisados} tokens em alta\n"
                 f"⏰ Atualizado em {datetime.now().strftime('%H:%M')}")
            
            print(f"[UPDATE] Novos top traders: {len(top_traders)} encontrados")
        else:
            print("[UPDATE] Nenhum trader encontrado - mantendo lista anterior")
            
    except Exception as e:
        print(f"[UPDATE] Erro: {e}")

# ============================================================
# MONITORAR ATIVIDADES DOS TRADERS
# ============================================================
def monitor_traders():
    """Monitora as atividades dos top traders em tempo real"""
    global last_update
    
    while True:
        try:
            # Atualiza lista de top traders periodicamente
            if time.time() - last_update > TOP_TRADERS_UPDATE_INTERVAL:
                find_top_traders()
            
            with lock:
                traders = top_traders.copy()
            
            if not traders:
                time.sleep(10)
                continue
            
            for trader in traders:
                # Busca atividades recentes
                activities = get_trader_activity(trader)
                if not activities:
                    continue
                
                # Analisa cada atividade
                for activity in activities.get("data", []):
                    if activity.get("type") != "buy":
                        continue
                    
                    token_addr = activity.get("token_address")
                    if not token_addr:
                        continue
                    
                    # Verifica se já executou este trade
                    trade_key = f"{trader}_{token_addr}"
                    with lock:
                        if trade_key in executed_trades:
                            continue
                        executed_trades[trade_key] = time.time()
                    
                    # Análise rápida do token
                    token_info = get_token_info(token_addr)
                    is_ok, reason = quick_token_analysis(token_info)
                    
                    if not is_ok:
                        continue
                    
                    symbol = token_info.get("data", {}).get("symbol", "???")
                    price = token_info.get("data", {}).get("price", 0)
                    
                    # ============================================
                    # EXECUTA COPY TRADE
                    # ============================================
                    try:
                        send(f"🔄 *COPY TRADE DETECTADO*\n\n"
                             f"🐋 Trader: `{trader[:8]}...{trader[-8:]}`\n"
                             f"💎 Token: *${symbol}*\n\n"
                             f"⏳ Executando compra com `{TRADE_AMOUNT_SOL} SOL`...")
                        
                        result = execute_swap(token_addr, TRADE_AMOUNT_SOL, SLIPPAGE)
                        
                        if result and result.get("success"):
                            with lock:
                                stats["trades"] += 1
                            
                            if trader not in trader_positions:
                                trader_positions[trader] = {}
                            trader_positions[trader][token_addr] = {
                                "symbol": symbol,
                                "entry_price": price,
                                "amount": TRADE_AMOUNT_SOL,
                                "entry_time": time.time(),
                                "trader": trader,
                                "tx": result.get("txid", "N/A")
                            }
                            
                            send(f"✅ *COPY TRADE EXECUTADO*\n\n"
                                 f"💎 *${symbol}*\n"
                                 f"💲 Entrada: `${price:.8f}`\n"
                                 f"📊 Montante: `{TRADE_AMOUNT_SOL} SOL`\n"
                                 f"🔗 Tx: `{result.get('txid', 'N/A')[:16]}...`")
                        else:
                            send(f"❌ *FALHA NO COPY TRADE*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Erro: {result}")
                            
                    except Exception as e:
                        send(f"❌ *ERRO:* {str(e)}")
                        print(f"[COPY] Erro: {e}")
            
        except Exception as e:
            print(f"[MONITOR] Erro: {e}")
        
        time.sleep(SCAN_DELAY)

# ============================================================
# MONITORAR SAÍDA DOS TRADERS
# ============================================================
def monitor_exits():
    """Monitora quando os traders vendem para sair junto"""
    while True:
        try:
            with lock:
                positions = trader_positions.copy()
            
            for trader, tokens in positions.items():
                activities = get_trader_activity(trader)
                if not activities:
                    continue
                
                for token_addr, pos in list(tokens.items()):
                    for activity in activities.get("data", []):
                        if (activity.get("type") == "sell" and 
                            activity.get("token_address") == token_addr):
                            
                            symbol = pos["symbol"]
                            send(f"🔻 *SAÍDA DO TRADER*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"⏳ Executando venda...")
                            
                            sell_result = execute_swap(token_addr, pos["amount"], SLIPPAGE)
                            
                            if sell_result and sell_result.get("success"):
                                send(f"✅ *VENDA EXECUTADA*\n\n"
                                     f"Token: *${symbol}*\n"
                                     f"Preço: `${sell_result.get('price', 0):.8f}`")
                                del trader_positions[trader][token_addr]
                            break
            
        except Exception as e:
            print(f"[EXIT] Erro: {e}")
        
        time.sleep(5)

# ============================================================
# RELATÓRIO
# ============================================================
def relatorio():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                st = dict(stats)
                pos_count = sum(len(tokens) for tokens in trader_positions.values())
                traders_count = len(top_traders)
            
            txt = (
                f"📊 *RELATÓRIO 2H - COPY TRADING DINÂMICO*\n\n"
                f"💰 Trades: `{st['trades']}`\n"
                f"📈 Posições: `{pos_count}`\n"
                f"🐋 Traders monitorados: `{traders_count}`\n\n"
                f"🔄 Top traders atualizados a cada 10min\n"
                f"🛡️ Anti-rug ativo\n"
                f"💰 Entrada: `{TRADE_AMOUNT_SOL} SOL`"
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
        pos_count = sum(len(tokens) for tokens in trader_positions.values())
    return f"COPY TRADING | traders={len(top_traders)} | trades={stats['trades']} | posicoes={pos_count}"

@app.route("/traders")
def get_traders():
    with lock:
        return {"top_traders": top_traders}

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v12.0 (COPY TRADING DINÂMICO) ===")
    
    # Busca inicial de top traders
    find_top_traders()
    
    send("🟢 *WHALE HUNTER v12.0 ONLINE*\n\n"
         "🤖 *Copy Trading DINÂMICO*\n"
         "🔄 Top traders atualizados a cada 10min\n"
         f"💰 Entrada: `{TRADE_AMOUNT_SOL} SOL`\n"
         f"🐋 Monitorando top traders automaticamente\n"
         "🛡️ Anti-rug ativo\n\n"
         "⚠️ *O bot encontra os melhores traders do momento*")

    # Inicia threads
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_exits, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    # Inicia Flask
    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
