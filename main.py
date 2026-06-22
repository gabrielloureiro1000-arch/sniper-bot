# ============================================================
# WHALE HUNTER v20.0 - TOP 10 TRADERS
# ============================================================
# - Identifica os 10 melhores traders do dia
# - Monitora as compras deles em tempo real
# - Envia alertas APENAS quando eles compram
# ============================================================

import os
import time
import threading
import subprocess
import json
import telebot
from flask import Flask
from queue import Queue, Empty
from datetime import datetime
import socket
import requests.packages.urllib3.util.connection as urllib3_cn

# ============================================================
# FORÇAR IPv4
# ============================================================
def allowed_gateways():
    return (socket.AF_INET,)
urllib3_cn.allowed_gateways = allowed_gateways

# ============================================================
# CONFIGURAÇÕES
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

app = Flask(__name__)

SCAN_DELAY = 30
REPORT_INTERVAL = 7200
TOP_TRADERS_UPDATE_INTERVAL = 600  # Atualiza a cada 10 min

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
top_traders = []  # Lista dos top traders do dia
tracked_tokens = {}  # Tokens já alertados
last_trader_update = 0
stats = {"alerts": 0, "traders_found": 0}
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
# GMGN CLI - COMANDOS
# ============================================================
def gmgn_cli_command(cmd):
    """Executa um comando do GMGN CLI e retorna o resultado"""
    try:
        print(f"[CLI] Executando: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "NODE_OPTIONS": "--dns-result-order=ipv4first"}
        )
        
        if result.returncode != 0:
            print(f"[CLI] Erro (cod {result.returncode}): {result.stderr[:200]}")
            return None
        
        if not result.stdout.strip():
            print("[CLI] Resposta vazia")
            return None
        
        try:
            data = json.loads(result.stdout)
            return data
        except json.JSONDecodeError as e:
            print(f"[CLI] JSON inválido: {e}")
            return None
        
    except subprocess.TimeoutExpired:
        print("[CLI] Timeout")
        return None
    except Exception as e:
        print(f"[CLI] Exceção: {e}")
        return None

def get_top_traders():
    """Busca os top traders do dia via GMGN CLI"""
    # Tenta diferentes comandos para encontrar top traders
    commands = [
        ['gmgn-cli', 'track', 'smartmoney', '--limit', '10', '--raw'],
        ['gmgn-cli', 'track', 'kol', '--limit', '10', '--raw'],
        ['gmgn-cli', 'market', 'traders', '--chain', 'sol', '--limit', '10', '--raw'],
    ]
    
    for cmd in commands:
        result = gmgn_cli_command(cmd)
        if result and 'data' in result:
            data = result['data']
            if isinstance(data, list) and data:
                return data
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, list) and value:
                        return value
    return []

def get_trader_activity(trader_address):
    """Busca atividades recentes de um trader"""
    cmd = [
        'gmgn-cli', 'track', 'follow-wallet',
        '--chain', 'sol',
        '--wallet', trader_address,
        '--limit', '5',
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

def get_token_info(chain, address):
    """Busca informações detalhadas de um token"""
    cmd = [
        'gmgn-cli', 'token', 'info',
        '--chain', chain,
        '--address', address,
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return None

# ============================================================
# IDENTIFICAR TOP TRADERS
# ============================================================
def identify_top_traders():
    """Identifica os 10 melhores traders do momento"""
    global top_traders, stats, last_trader_update
    
    print("[UPDATE] Buscando top traders do dia...")
    send("🔄 *Atualizando lista de Top 10 Traders*")
    
    traders = get_top_traders()
    
    if not traders:
        print("[UPDATE] Nenhum trader encontrado")
        send("⚠️ *Nenhum top trader encontrado no momento*")
        return
    
    with lock:
        top_traders = traders[:10]
        stats["traders_found"] = len(top_traders)
        last_trader_update = time.time()
    
    # Envia lista dos traders no Telegram
    msg = f"📋 *TOP 10 TRADERS DO DIA*\n\n"
    msg += f"Monitorando {len(top_traders)} traders:\n\n"
    for i, t in enumerate(top_traders[:10], 1):
        addr = t.get('address', 'N/A')[:8] + '...' + t.get('address', 'N/A')[-8:]
        profit = t.get('profit', 0)
        msg += f"{i}. 🐋 `{addr}`\n"
        if profit:
            msg += f"   Lucro: `${profit:,.0f}`\n"
    msg += f"\n⏰ Atualizado em {datetime.now().strftime('%H:%M')}"
    
    send(msg)
    print(f"[UPDATE] Top traders: {len(top_traders)} encontrados")

# ============================================================
# MONITORAR ATIVIDADES DOS TRADERS
# ============================================================
def monitor_traders():
    """Monitora as compras dos top traders em tempo real"""
    global last_trader_update, stats
    
    print("[MONITOR] Iniciando monitoramento de top traders...")
    
    while True:
        try:
            # Atualiza lista de traders periodicamente
            if time.time() - last_trader_update > TOP_TRADERS_UPDATE_INTERVAL:
                identify_top_traders()
            
            with lock:
                traders = top_traders.copy()
            
            if not traders:
                print("[MONITOR] Nenhum trader para monitorar")
                time.sleep(10)
                continue
            
            for trader in traders:
                trader_addr = trader.get('address')
                if not trader_addr:
                    continue
                
                print(f"[MONITOR] Verificando trader: {trader_addr[:8]}...")
                
                # Busca atividades do trader
                activities = get_trader_activity(trader_addr)
                
                if not activities:
                    continue
                
                for activity in activities:
                    try:
                        # Verifica se é uma compra
                        side = activity.get('side', '').lower()
                        if side != 'buy':
                            continue
                        
                        token_addr = activity.get('token_address') or activity.get('address')
                        if not token_addr:
                            continue
                        
                        # Verifica se já alertou este token
                        with lock:
                            if token_addr in tracked_tokens:
                                continue
                            tracked_tokens[token_addr] = time.time()
                        
                        # Busca informações do token
                        token_info = get_token_info('sol', token_addr)
                        if not token_info:
                            continue
                        
                        symbol = token_info.get('symbol', '???')
                        price = float(token_info.get('price', 0) or 0)
                        volume_24h = float(token_info.get('volume_24h', 0) or 0)
                        market_cap = float(token_info.get('market_cap', 0) or 0)
                        price_change_1h = float(token_info.get('price_change_1h', 0) or 0)
                        holder_count = int(token_info.get('holder_count', 0) or 0)
                        smart_money_count = int(token_info.get('smart_degen_count', 0) or 0)
                        
                        # Calcula score
                        score = 0
                        if price_change_1h > 10: score += 20
                        elif price_change_1h > 5: score += 10
                        if holder_count > 100: score += 20
                        elif holder_count > 50: score += 10
                        if smart_money_count > 5: score += 30
                        elif smart_money_count > 2: score += 15
                        if market_cap > 100000: score += 20
                        elif market_cap > 50000: score += 10
                        
                        # Envia alerta
                        confidence = "🔴"
                        if score >= 70:
                            confidence = "🟢 FORTE"
                        elif score >= 50:
                            confidence = "🟡 MÉDIO"
                        elif score >= 25:
                            confidence = "🟠 INTERESSANTE"
                        
                        tp1 = price * 1.8
                        tp2 = price * 3.5
                        tp3 = price * 7.0
                        stop = price * 0.85
                        
                        msg = (
                            f"🐋 *TOP TRADER COMPROU!*\n\n"
                            f"Trader: `{trader_addr[:8]}...{trader_addr[-8:]}`\n"
                            f"{confidence} *${symbol}*\n"
                            f"`{token_addr[:8]}...{token_addr[-8:]}`\n\n"
                            f"💲 Preço: `${price:.8f}`\n"
                            f"📊 Volume 24h: `${volume_24h:,.0f}`\n"
                            f"💰 Market Cap: `${market_cap:,.0f}`\n"
                            f"📈 Alta 1h: `{price_change_1h:+.1f}%`\n"
                            f"👥 Holders: `{holder_count}`\n"
                            f"🧠 Smart Money: `{smart_money_count}`\n"
                            f"⭐ Score: `{score:.0f}`\n\n"
                            f"🎯 TP1: `1.8x` | TP2: `3.5x` | TP3: `7x`\n"
                            f"🛑 STOP: `-15%`\n\n"
                            f"🔍 GMGN: https://gmgn.ai/sol/token/{token_addr}\n"
                            f"📊 DEX: https://dexscreener.com/solana/{token_addr}\n\n"
                            f"⚠️ *MODO MANUAL* - Analise antes de comprar"
                        )
                        
                        send(msg)
                        stats["alerts"] += 1
                        print(f"[ALERTA] {symbol} - Trader: {trader_addr[:8]}... - Score: {score:.0f}")
                        
                    except Exception as e:
                        print(f"[MONITOR] Erro ao processar atividade: {e}")
                
                time.sleep(2)  # Pequena pausa entre traders
            
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
                traders = stats["traders_found"]
            
            txt = (
                f"📊 *RELATÓRIO 2H - TOP TRADERS*\n\n"
                f"🐋 Traders monitorados: `{traders}`\n"
                f"📈 Alertas enviados: `{alerts}`\n\n"
                f"🔍 Monitorando compras dos top 10 traders\n"
                f"✅ *MODO MANUAL* - Você decide as entradas"
            )
            send(txt)
        except Exception as e:
            print(f"[REL] Erro: {e}")
        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH
# ============================================================
@app.route("/")
def health():
    with lock:
        traders = len(top_traders)
        alerts = stats["alerts"]
    return f"TOP TRADERS | traders={traders} | alerts={alerts}"

@app.route("/debug")
def debug_output():
    try:
        with open("/tmp/cli_output.txt", "r") as f:
            content = f.read()
        return f"<pre>{content}</pre>"
    except FileNotFoundError:
        return "Arquivo não encontrado"
    except Exception as e:
        return f"Erro: {e}"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v20.0 (TOP TRADERS) ===")
    
    # Identifica os top traders inicialmente
    identify_top_traders()
    
    send("🟢 *WHALE HUNTER v20.0 ONLINE*\n\n"
         "🐋 *TOP 10 TRADERS DO DIA*\n"
         "🔍 Monitorando compras dos melhores traders\n"
         "📝 Alertas APENAS quando eles compram\n\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende\n\n"
         "✅ *Copy trading de elite ativado*")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
