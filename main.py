# ============================================================
# WHALE HUNTER v10.0 - TRADING AUTOMATIZADO
# ============================================================
# - Monitora DexScreener + GMGN em tempo real
# - Compra automaticamente tokens promissores
# - Vende automaticamente nos alvos (1.8x, 3.5x, 7x)
# - Stop-loss automático (-15%)
# - Alerta de saída por Telegram
# ============================================================

import os
import time
import threading
import requests
import json
import telebot
from flask import Flask
from queue import Queue, Empty
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import base64
import hashlib
import hmac

# ============================================================
# CONFIGURAÇÕES DO TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

# ============================================================
# CONFIGURAÇÕES DA GMGN
# ============================================================
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
adapter = HTTPAdapter(pool_connections=150, pool_maxsize=150, max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ============================================================
# CONFIGURAÇÕES DE TRADING
# ============================================================
SCAN_DELAY = 0.5
REPORT_INTERVAL = 7200  # 2 horas

# Filtros de entrada
MIN_LIQ = 4000
MAX_LIQ = 200000
MIN_BUYS = 5
MAX_BUYS = 500
MIN_RATIO = 1.8
MIN_VOL5M = 500
MIN_AGE = 0.3
MAX_AGE = 60
MIN_M5 = 1.5
MAX_M5 = 150
MAX_TOP10 = 35
MIN_SMART = 1
MIN_WHALE_AVG_SIZE = 200

# Configurações de trade
TRADE_AMOUNT_SOL = 0.1  # Quantidade em SOL por trade
SLIPPAGE = 15  # Slippage em %
TP1 = 1.8  # Primeiro take-profit (1.8x)
TP2 = 3.5  # Segundo take-profit (3.5x)
TP3 = 7.0  # Terceiro take-profit (7x)
STOP_LOSS = 0.85  # Stop-loss (85% do preço = -15%)

# ============================================================
# ENDPOINTS
# ============================================================
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
history = {}  # tokens já processados
positions = {}  # posições ativas {addr: {symbol, entry_price, amount, tp1, tp2, tp3, stop_loss}}
stats = {"sent": 0, "green": 0, "yellow": 0, "trades": 0}
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
        
        # Assinatura da requisição (se necessário)
        if method == "POST":
            payload = json.dumps(data) if data else ""
            signature = hmac.new(
                GMGN_PRIVATE_KEY.encode(),
                f"{timestamp}{payload}".encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-SIGNATURE"] = signature
        
        if method == "GET":
            response = session.get(url, headers=headers, timeout=10)
        else:
            response = session.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            return response.json()
        else:
            print(f"[GMGN] Erro {response.status_code}: {response.text}")
            return None
            
    except Exception as e:
        print(f"[GMGN] Exceção: {e}")
        return None

def get_token_info(addr):
    """Obtém informações detalhadas do token na GMGN"""
    endpoint = f"/v1/token/sol/{addr}"
    return gmgn_api_request(endpoint)

def execute_swap(token_address, amount_sol, slippage=15):
    """Executa uma swap (compra/venda) via GMGN"""
    endpoint = "/v1/swap"
    data = {
        "fromToken": "So11111111111111111111111111111111111111112",  # SOL
        "toToken": token_address,
        "amount": str(amount_sol),
        "slippage": slippage,
        "chain": "solana"
    }
    return gmgn_api_request(endpoint, "POST", data)

def execute_sell(token_address, amount, slippage=15):
    """Vende um token via GMGN"""
    endpoint = "/v1/swap"
    data = {
        "fromToken": token_address,
        "toToken": "So11111111111111111111111111111111111111112",  # SOL
        "amount": str(amount),
        "slippage": slippage,
        "chain": "solana"
    }
    return gmgn_api_request(endpoint, "POST", data)

# ============================================================
# ANTI RUG
# ============================================================
def is_lixo(g):
    if not g:
        return False, ""
    if g.get("honeypot") is True:
        return True, "HONEYPOT"
    if g.get("tax", 0) > 25:
        return True, f"TAX {g['tax']}%"
    if g.get("rug", 0) > 0.8:
        return True, "RUG"
    dev = g.get("dev", 0)
    if dev and float(dev) > 15:
        return True, f"DEV {dev:.0f}%"
    top10 = g.get("top10", 0)
    if top10:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t > MAX_TOP10:
            return True, f"TOP10 {t:.0f}%"
    return False, ""

# ============================================================
# SCORE
# ============================================================
def calculate_score(data, g, avg_buy_size):
    pontos = 0
    ratio = data["ratio"]
    buys = data["buys"]
    age = data["age"]
    m5 = data["m5"]
    accel = data["accel"]

    # Baleias
    if avg_buy_size >= 800: pontos += 6
    elif avg_buy_size >= 400: pontos += 4
    elif avg_buy_size >= 200: pontos += 2

    # Ratio
    if ratio >= 4: pontos += 5
    elif ratio >= 2.5: pontos += 4
    elif ratio >= 1.8: pontos += 2

    # Idade
    if age <= 5: pontos += 5
    elif age <= 15: pontos += 3
    elif age <= 30: pontos += 1

    # Momentum
    if m5 >= 20: pontos += 4
    elif m5 >= 8: pontos += 2

    # Aceleração
    if accel >= 2.5: pontos += 4
    elif accel >= 1.5: pontos += 2

    # Smart money
    smart = g.get("smart", 0) if g else 0
    if smart >= 4: pontos += 7
    elif smart >= 2: pontos += 4
    elif smart >= 1: pontos += 2

    # Holders
    holders = g.get("holders", 0) if g else 0
    if holders >= 200: pontos += 4
    elif holders >= 80: pontos += 2
    elif holders >= 30: pontos += 1

    return pontos

# ============================================================
# PROCESSAMENTO PRINCIPAL (COM EXECUÇÃO DE TRADES)
# ============================================================
def processar(pair):
    try:
        if pair.get("chainId") != "solana":
            return

        base = pair.get("baseToken", {})
        addr = base.get("address")
        if not addr:
            return

        price = pair.get("priceUsd")
        if not price:
            return
        price_val = float(price)

        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        if liq < MIN_LIQ or liq > MAX_LIQ:
            return

        vol = pair.get("volume", {})
        vol5m = vol.get("m5", 0) or 0
        if vol5m < MIN_VOL5M:
            return

        tx = pair.get("txns", {}).get("m5", {})
        buys = tx.get("buys", 0)
        sells = tx.get("sells", 0)

        if buys < MIN_BUYS:
            return

        ratio = buys / max(sells, 1)
        if ratio < MIN_RATIO:
            return

        pc = pair.get("priceChange", {})
        m5 = pc.get("m5", 0) or 0
        if m5 < MIN_M5:
            return

        created = pair.get("pairCreatedAt")
        age = (time.time() * 1000 - created) / 60000 if created else 999
        if age < MIN_AGE or age > MAX_AGE:
            return

        accel = vol5m / max(vol.get("h1", 0) / 12, 1) if vol.get("h1", 0) > 0 else 0

        # Verifica se já está em posição ou já processado
        with lock:
            if addr in positions or addr in history:
                return

        # Consulta GMGN
        g = get_token_info(addr)
        if not g:
            return
            
        lixo, motivo = is_lixo(g)
        if lixo:
            return

        # Smart money mínimo
        if g.get("smart", 0) < MIN_SMART:
            return

        avg_buy_size = vol5m / max(buys, 1)
        if avg_buy_size < MIN_WHALE_AVG_SIZE:
            return

        # Calcula score
        score = calculate_score({
            "ratio": ratio, "buys": buys, "age": age,
            "m5": m5, "accel": accel
        }, g, avg_buy_size)

        # Só compra se score >= 20 (ELITE ou WHALE)
        if score < 20:
            return

        symbol = base.get("symbol", "???")
        now_ts = time.time()

        # ============================================================
        # EXECUTA COMPRA AUTOMÁTICA
        # ============================================================
        try:
            send(f"🟢 *EXECUTANDO COMPRA*\n\n"
                 f"Token: *${symbol}*\n"
                 f"Score: `{score}`\n"
                 f"Valor: `{TRADE_AMOUNT_SOL} SOL`\n"
                 f"Preço: `${price_val:.10f}`\n\n"
                 f"⏳ Processando...")
            
            # Executa a compra
            trade_result = execute_swap(addr, TRADE_AMOUNT_SOL, SLIPPAGE)
            
            if trade_result and trade_result.get("success"):
                # Registra a posição
                with lock:
                    positions[addr] = {
                        "symbol": symbol,
                        "entry_price": price_val,
                        "amount": TRADE_AMOUNT_SOL,
                        "tp1": price_val * TP1,
                        "tp2": price_val * TP2,
                        "tp3": price_val * TP3,
                        "stop_loss": price_val * STOP_LOSS,
                        "entry_time": now_ts,
                        "tx": trade_result.get("txid", "N/A")
                    }
                    stats["trades"] += 1
                    stats["sent"] += 1
                    stats["green"] += 1 if score >= 28 else 0
                    stats["yellow"] += 1 if 20 <= score < 28 else 0
                
                send(f"✅ *COMPRA REALIZADA COM SUCESSO!*\n\n"
                     f"💎 *${symbol}*\n"
                     f"`{addr}`\n\n"
                     f"💲 Entrada: `${price_val:.10f}`\n"
                     f"📊 Montante: `{TRADE_AMOUNT_SOL} SOL`\n"
                     f"🔗 Tx: `{trade_result.get('txid', 'N/A')[:16]}...`\n\n"
                     f"🎯 TP1: `{TP1}x` (${price_val * TP1:.8f})\n"
                     f"🚀 TP2: `{TP2}x` (${price_val * TP2:.8f})\n"
                     f"🌕 TP3: `{TP3}x` (${price_val * TP3:.8f})\n"
                     f"🛑 STOP: `-{int((1-STOP_LOSS)*100)}%` (${price_val * STOP_LOSS:.8f})")
            else:
                send(f"❌ *FALHA NA COMPRA*\n\n"
                     f"Token: *${symbol}*\n"
                     f"Erro: {trade_result}")
                     
        except Exception as e:
            send(f"❌ *ERRO NA COMPRA*\n\n"
                 f"Token: *${symbol}*\n"
                 f"Erro: {str(e)}")
            print(f"[TRADE] Erro ao comprar {symbol}: {e}")
            
        # Salva no histórico para evitar repetições
        with lock:
            history[addr] = {"symbol": symbol, "ts": now_ts}

    except Exception as e:
        print(f"[PROCESS] {e}")

# ============================================================
# MONITORAMENTO DE POSIÇÕES (SAÍDA AUTOMÁTICA)
# ============================================================
def monitorar_posicoes():
    """Monitora posições ativas e executa vendas nos alvos"""
    while True:
        try:
            with lock:
                if not positions:
                    time.sleep(5)
                    continue
                    
                for addr, pos in list(positions.items()):
                    # Consulta preço atual
                    pair_data = session.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{addr}",
                        headers=HEADERS,
                        timeout=5
                    )
                    
                    if pair_data.status_code != 200:
                        continue
                        
                    data = pair_data.json()
                    if not data.get("pairs"):
                        continue
                        
                    current_price = float(data["pairs"][0]["priceUsd"])
                    symbol = pos["symbol"]
                    
                    # Verifica stop-loss
                    if current_price <= pos["stop_loss"]:
                        # Executa venda (stop-loss)
                        send(f"🔻 *STOP-LOSS ATIVADO*\n\n"
                             f"Token: *${symbol}*\n"
                             f"Preço entrada: `${pos['entry_price']:.8f}`\n"
                             f"Preço atual: `${current_price:.8f}`\n"
                             f"Perda: `-{int((1 - current_price/pos['entry_price']) * 100)}%`\n\n"
                             f"⏳ Executando venda...")
                        
                        sell_result = execute_sell(addr, pos["amount"], SLIPPAGE)
                        if sell_result and sell_result.get("success"):
                            send(f"✅ *VENDA EXECUTADA (STOP-LOSS)*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Preço: `${current_price:.8f}`\n"
                                 f"Tx: `{sell_result.get('txid', 'N/A')[:16]}...`")
                        else:
                            send(f"❌ *FALHA NA VENDA (STOP-LOSS)*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Erro: {sell_result}")
                        
                        del positions[addr]
                        continue
                    
                    # Verifica take-profits
                    if current_price >= pos["tp3"]:
                        # Vende 50% no TP3
                        sell_amount = pos["amount"] * 0.5
                        send(f"🚀 *TP3 ATINGIDO! (7x)*\n\n"
                             f"Token: *${symbol}*\n"
                             f"Preço: `${current_price:.8f}`\n"
                             f"Lucro: `+{int((current_price/pos['entry_price'] - 1) * 100)}%`\n\n"
                             f"⏳ Vendendo 50%...")
                        
                        sell_result = execute_sell(addr, sell_amount, SLIPPAGE)
                        if sell_result and sell_result.get("success"):
                            send(f"✅ *VENDA PARCIAL (TP3)*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Preço: `${current_price:.8f}`\n"
                                 f"Tx: `{sell_result.get('txid', 'N/A')[:16]}...`\n"
                                 f"Restante: moonbag para TP4+")
                            # Atualiza posição
                            pos["amount"] -= sell_amount
                            if pos["amount"] <= 0:
                                del positions[addr]
                        continue
                    
                    if current_price >= pos["tp2"]:
                        # Vende 30% no TP2
                        sell_amount = pos["amount"] * 0.3
                        send(f"🚀 *TP2 ATINGIDO! (3.5x)*\n\n"
                             f"Token: *${symbol}*\n"
                             f"Preço: `${current_price:.8f}`\n"
                             f"Lucro: `+{int((current_price/pos['entry_price'] - 1) * 100)}%`\n\n"
                             f"⏳ Vendendo 30%...")
                        
                        sell_result = execute_sell(addr, sell_amount, SLIPPAGE)
                        if sell_result and sell_result.get("success"):
                            send(f"✅ *VENDA PARCIAL (TP2)*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Preço: `${current_price:.8f}`\n"
                                 f"Tx: `{sell_result.get('txid', 'N/A')[:16]}...`")
                            pos["amount"] -= sell_amount
                        continue
                    
                    if current_price >= pos["tp1"]:
                        # Vende 20% no TP1
                        sell_amount = pos["amount"] * 0.2
                        send(f"📈 *TP1 ATINGIDO! (1.8x)*\n\n"
                             f"Token: *${symbol}*\n"
                             f"Preço: `${current_price:.8f}`\n"
                             f"Lucro: `+{int((current_price/pos['entry_price'] - 1) * 100)}%`\n\n"
                             f"⏳ Vendendo 20%...")
                        
                        sell_result = execute_sell(addr, sell_amount, SLIPPAGE)
                        if sell_result and sell_result.get("success"):
                            send(f"✅ *VENDA PARCIAL (TP1)*\n\n"
                                 f"Token: *${symbol}*\n"
                                 f"Preço: `${current_price:.8f}`\n"
                                 f"Tx: `{sell_result.get('txid', 'N/A')[:16]}...`")
                            pos["amount"] -= sell_amount
                        continue
                        
        except Exception as e:
            print(f"[MONITOR] Erro: {e}")
            
        time.sleep(10)  # Verifica a cada 10 segundos

# ============================================================
# SCANNER
# ============================================================
def scan():
    idx = 0
    while True:
        try:
            url = ENDPOINTS[idx % len(ENDPOINTS)]
            idx += 1
            r = session.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                for pair in pairs:
                    processar(pair)
        except Exception as e:
            print(f"[SCAN] Erro: {e}")
        time.sleep(SCAN_DELAY)

# ============================================================
# RELATÓRIO
# ============================================================
def relatorio():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                st = dict(stats)
                pos_count = len(positions)
            txt = (
                f"📊 *RELATÓRIO 2H*\n\n"
                f"📤 Alertas: `{st['sent']}`\n"
                f"🟢 Elite: `{st['green']}`  |  🟡 Whale: `{st['yellow']}`\n"
                f"💰 Trades executados: `{st['trades']}`\n"
                f"📈 Posições ativas: `{pos_count}`\n\n"
                f"🐋 Whale monitor ativo\n"
                f"🧠 Smart money scanner\n"
                f"⚡ Stealth buy detector\n"
                f"🚀 Ultra early monitor\n"
                f"🛡️ Anti rug system\n"
                f"💰 Trading automatizado ativo"
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
        pos_count = len(positions)
    return f"WHALE HUNTER v10.0 | alertas={stats['sent']} | trades={stats['trades']} | posicoes={pos_count}"

@app.route("/positions")
def get_positions():
    with lock:
        return dict(positions)

@app.route("/stats")
def get_stats():
    return dict(stats)

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v10.0 (AUTOMATIZADO) ===")
    
    send("🟢 *WHALE HUNTER v10.0 ONLINE*\n\n"
         "🤖 *MODO AUTOMATIZADO ATIVO*\n"
         "💰 Compras e vendas automáticas\n"
         "🎯 TP1: 1.8x | TP2: 3.5x | TP3: 7x\n"
         "🛑 Stop-loss: -15%\n\n"
         f"📊 Trade amount: `{TRADE_AMOUNT_SOL} SOL`\n"
         f"🔍 Filtros ativos: SMART>={MIN_SMART}, BUYS>={MIN_BUYS}, RATIO>={MIN_RATIO}\n\n"
         "⚠️ *Monitore os logs para verificar execuções*")

    # Inicia threads
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitorar_posicoes, daemon=True).start()
    
    # Threads de scan
    for _ in range(5):
        threading.Thread(target=scan, daemon=True).start()
        time.sleep(0.2)

    # Inicia Flask
    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
