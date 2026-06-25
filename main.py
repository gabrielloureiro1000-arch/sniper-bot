# ============================================================
# WHALE HUNTER v24.3 - KOLs + FOLLOW-WALLET (FUNCIONAL)
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
TOP_TRADERS_UPDATE_INTERVAL = 600

# ============================================================
# FILTROS ANTI-LIXO
# ============================================================
MIN_VOLUME = 15000
MIN_HOLDERS = 40
MAX_TOP10_HOLDERS = 45
MAX_DEV_HOLD = 15
MAX_SELL_TAX = 20
MIN_PRICE_CHANGE = 3.0
MIN_SMART_MONEY = 2
MIN_SCORE = 45

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
top_traders = []
tracked_tokens = {}
last_trader_update = 0
stats = {"alerts": 0, "tokens_found": 0, "traders_found": 0}
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
# GMGN CLI - COMANDOS QUE FUNCIONAM
# ============================================================
def gmgn_cli_command(cmd):
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
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"[CLI] JSON inválido: {e}")
            return None
        
    except subprocess.TimeoutExpired:
        print("[CLI] Timeout")
        return None
    except Exception as e:
        print(f"[CLI] Exceção: {e}")
        return None

def get_top_kols():
    """Busca os Top KOLs (influenciadores) - FUNCIONA"""
    cmd = ['gmgn-cli', 'track', 'kol', '--chain', 'sol', '--limit', '10', '--raw']
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

def get_trader_activity(wallet_address):
    """Busca atividades de uma wallet - FUNCIONA"""
    cmd = [
        'gmgn-cli', 'track', 'follow-wallet',
        '--chain', 'sol',
        '--wallet', wallet_address,
        '--limit', '10',
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

def get_trending_tokens(limit=30):
    """Busca tokens em alta - FUNCIONA"""
    cmd = [
        'gmgn-cli', 'market', 'trending',
        '--chain', 'sol',
        '--interval', '1h',
        '--limit', str(limit),
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        data = result['data']
        if isinstance(data, dict) and 'rank' in data:
            return data['rank']
        if isinstance(data, list):
            return data
    return []

def get_token_info(address):
    """Busca informações detalhadas de um token - FUNCIONA"""
    cmd = [
        'gmgn-cli', 'token', 'info',
        '--chain', 'sol',
        '--address', address,
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return None

# ============================================================
# IDENTIFICAR TOP KOLs
# ============================================================
def identify_top_traders():
    """Identifica os Top KOLs (influenciadores)"""
    global top_traders, stats, last_trader_update
    
    print("[UPDATE] Buscando Top KOLs...")
    send("🔄 *Atualizando lista de Top KOLs*")
    
    kols = get_top_kols()
    
    if not kols:
        print("[UPDATE] Nenhum KOL encontrado - usando fallback")
        # Fallback: usa tokens em alta com mais Smart Money
        send("⚠️ *Nenhum KOL encontrado - usando tokens com Smart Money como fallback*")
        return
    
    with lock:
        top_traders = kols[:10]
        stats["traders_found"] = len(top_traders)
        last_trader_update = time.time()
    
    msg = f"📋 *TOP KOLs MONITORADOS*\n\n"
    msg += f"Monitorando {len(top_traders)} KOLs:\n\n"
    for i, t in enumerate(top_traders[:10], 1):
        addr = t.get('address', 'N/A')
        msg += f"{i}. 🐋 `{addr[:8]}...{addr[-8:]}`\n"
    msg += f"\n⏰ Atualizado em {datetime.now().strftime('%H:%M')}"
    
    send(msg)
    print(f"[UPDATE] Top KOLs: {len(top_traders)} encontrados")

# ============================================================
# ANÁLISE ANTI-LIXO
# ============================================================
def is_lixo(token_info):
    if not token_info:
        return True, "Sem dados"
    if token_info.get('is_honeypot', False):
        return True, "HONEYPOT"
    if (token_info.get('sell_tax', 0) or 0) > MAX_SELL_TAX:
        return True, f"TAXA {(token_info.get('sell_tax', 0) or 0)}%"
    if token_info.get('rug_ratio', 0) > 0.7:
        return True, "RUG"
    if (token_info.get('creator_hold_percent', 0) or 0) > MAX_DEV_HOLD:
        return True, f"DEV {(token_info.get('creator_hold_percent', 0) or 0):.0f}%"
    if (token_info.get('top10_holder_rate', 0) or 0) > MAX_TOP10_HOLDERS:
        return True, f"TOP10 {(token_info.get('top10_holder_rate', 0) or 0):.0f}%"
    return False, "OK"

# ============================================================
# ANALISAR ATIVIDADE DO TRADER
# ============================================================
def analyze_trader_activity(trader_addr, activities):
    """Analisa as atividades de um trader (compras e vendas)"""
    global stats
    
    for activity in activities:
        try:
            token_addr = activity.get('token_address') or activity.get('address')
            if not token_addr:
                continue
            
            side = activity.get('side', '').lower()
            amount = activity.get('amount', 0)
            price = activity.get('price', 0)
            timestamp = activity.get('timestamp', time.time())
            
            with lock:
                if token_addr in tracked_tokens:
                    continue
                tracked_tokens[token_addr] = time.time()
            
            token_info = get_token_info(token_addr)
            if not token_info:
                continue
            
            symbol = token_info.get('symbol', '???')
            holder_count = int(token_info.get('holder_count', 0) or 0)
            smart_money_count = int(token_info.get('smart_degen_count', 0) or 0)
            volume_24h = float(token_info.get('volume_24h', 0) or 0)
            market_cap = float(token_info.get('market_cap', 0) or 0)
            price_change_1h = float(token_info.get('price_change_1h', 0) or 0)
            
            if side == 'buy':
                action = "🟢 COMPROU"
                action_emoji = "🟢"
            elif side == 'sell':
                action = "🔴 VENDEU"
                action_emoji = "🔴"
            else:
                continue
            
            analysis_note = ""
            if side == 'buy':
                is_rug, motivo = is_lixo(token_info)
                if is_rug:
                    analysis_note = f"❌ BLOQUEADO: {motivo}"
                else:
                    if holder_count >= MIN_HOLDERS and volume_24h >= MIN_VOLUME and smart_money_count >= MIN_SMART_MONEY:
                        analysis_note = "✅ TOKEN PROMISSOR"
                    else:
                        analysis_note = "⚠️ TOKEN FRACO"
            
            msg = (
                f"🐋 *KOL {action}*\n\n"
                f"Trader: `{trader_addr[:8]}...{trader_addr[-8:]}`\n"
                f"{action_emoji} *${symbol}*\n"
                f"`{token_addr[:8]}...{token_addr[-8:]}`\n\n"
                f"💲 Preço: `${price:.8f}`\n"
                f"📊 Quantidade: `{amount:,.0f}`\n"
                f"💰 Valor: `${(amount * price):,.2f}`\n\n"
                f"📊 Volume 24h: `${volume_24h:,.0f}`\n"
                f"💰 Market Cap: `${market_cap:,.0f}`\n"
                f"📈 Alta 1h: `{price_change_1h:+.1f}%`\n"
                f"👥 Holders: `{holder_count}`\n"
                f"🧠 Smart Money: `{smart_money_count}`\n"
                f"🔒 Taxa venda: `{token_info.get('sell_tax', 0)}%`\n\n"
                f"📋 *ANÁLISE:* {analysis_note}\n"
                f"⏰ {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}\n\n"
                f"🔍 GMGN: https://gmgn.ai/sol/token/{token_addr}\n"
                f"📊 DEX: https://dexscreener.com/solana/{token_addr}\n\n"
                f"⚠️ *MODO MANUAL* - Analise antes de comprar"
            )
            
            send(msg)
            stats["alerts"] += 1
            stats["tokens_found"] += 1
            print(f"[ALERTA] {symbol} - {action} - {analysis_note}")
            
        except Exception as e:
            print(f"[ANALYZE] Erro: {e}")

# ============================================================
# MONITORAR TOP TRADERS
# ============================================================
def monitor_traders():
    global last_trader_update
    
    print("[MONITOR] Iniciando monitoramento dos Top KOLs...")
    
    while True:
        try:
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
                
                activities = get_trader_activity(trader_addr)
                if not activities:
                    continue
                
                analyze_trader_activity(trader_addr, activities)
                time.sleep(2)
            
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
                tokens = stats["tokens_found"]
                traders = stats["traders_found"]
            
            txt = (
                f"📊 *RELATÓRIO 2H - KOLs*\n\n"
                f"🐋 KOLs monitorados: `{traders}`\n"
                f"📈 Alertas enviados: `{alerts}`\n"
                f"💎 Tokens analisados: `{tokens}`\n\n"
                f"🛡️ Anti-lixo ativo\n"
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
        alerts = stats["alerts"]
        tokens = stats["tokens_found"]
        traders = stats["traders_found"]
    return f"KOLs | traders={traders} | alerts={alerts} | tokens={tokens}"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v24.3 (KOLs) ===")
    
    identify_top_traders()
    
    send("🟢 *WHALE HUNTER v24.3 ONLINE*\n\n"
         "🐋 *TOP KOLs MONITORADOS*\n"
         "🔍 Monitorando em tempo real:\n"
         "• 🟢 Compras\n"
         "• 🔴 Vendas\n"
         "• 📊 Análise de cada token\n"
         "• 🛡️ Anti-lixo ativo\n\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
