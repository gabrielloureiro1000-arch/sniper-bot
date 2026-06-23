# ============================================================
# WHALE HUNTER v21.0 - TOP 10 TRADERS + ANTI-LIXO
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

SCAN_DELAY = 30  # Verifica a cada 30 segundos
REPORT_INTERVAL = 7200
TOP_TRADERS_UPDATE_INTERVAL = 600  # Atualiza a cada 10 minutos

# ============================================================
# FILTROS ANTI-LIXO E PROMISSORES
# ============================================================
MIN_VOLUME = 20000          # Volume mínimo em USD
MIN_HOLDERS = 50            # Mínimo de holders (evita tokens novos demais)
MAX_TOP10_HOLDERS = 35      # Máximo de % da oferta em top 10 holders (anti-rug)
MAX_DEV_HOLD = 10           # Máximo de % do DEV (anti-rug)
MAX_SELL_TAX = 20           # Máximo de taxa de venda em %
MIN_PRICE_CHANGE = 5.0      # Alta mínima em % para considerar promissor
MIN_SMART_MONEY = 2         # Mínimo de Smart Money
MIN_SCORE = 50              # Score mínimo para alerta
MIN_BUYS = 10               # Mínimo de compras nos últimos 5min

# ============================================================
# TOP TRADERS MANUAIS (SUBSTITUA PELOS ENDEREÇOS REAIS)
# ============================================================
# Você pode obter esses endereços em: https://gmgn.ai/trade?chain=sol
# Clique em "Top Traders" e copie os endereços
MANUAL_TOP_TRADERS = [
    # Exemplo - substitua pelos endereços reais
    # "7VYhWQRs9kTyBxQnVuMhPq2rkXwZtM5xZkQyJYxXwE9",
    # "8XwZtM5xZkQyJYxXwE9VYhWQRs9kTyBxQnVuMhPq2",
]

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
# GMGN CLI
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
            print(f"[CLI] Erro (cod {result.returncode})")
            return None
        
        if not result.stdout.strip():
            return None
        
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        
    except subprocess.TimeoutExpired:
        print("[CLI] Timeout")
        return None
    except Exception as e:
        print(f"[CLI] Exceção: {e}")
        return None

def get_smart_money():
    """Busca Smart Money (traders mais lucrativos)"""
    cmd = ['gmgn-cli', 'track', 'smartmoney', '--chain', 'sol', '--limit', '20', '--raw']
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

def get_kols():
    """Busca KOLs (influenciadores)"""
    cmd = ['gmgn-cli', 'track', 'kol', '--chain', 'sol', '--limit', '20', '--raw']
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

def get_trader_activity(wallet_address):
    """Busca atividades recentes de uma wallet"""
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

def get_token_info(address):
    """Busca informações detalhadas de um token com dados de segurança"""
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
# IDENTIFICAR TOP TRADERS
# ============================================================
def identify_top_traders():
    """Identifica os melhores traders (Smart Money + KOLs + Manuais)"""
    global top_traders, stats, last_trader_update
    
    print("[UPDATE] Buscando top traders...")
    
    # Combina todas as fontes
    combined = {}
    
    # 1. Smart Money
    smart_money = get_smart_money()
    for trader in smart_money:
        addr = trader.get('address')
        if addr:
            combined[addr] = trader
    
    # 2. KOLs
    kols = get_kols()
    for trader in kols:
        addr = trader.get('address')
        if addr and addr not in combined:
            combined[addr] = trader
    
    # 3. Traders manuais
    for addr in MANUAL_TOP_TRADERS:
        if addr and addr not in combined:
            combined[addr] = {'address': addr, 'source': 'manual'}
    
    traders_list = list(combined.values())
    
    if not traders_list:
        print("[UPDATE] Nenhum trader encontrado")
        return
    
    with lock:
        top_traders = traders_list[:15]  # Pega até 15
        stats["traders_found"] = len(top_traders)
        last_trader_update = time.time()
    
    # Envia lista no Telegram
    msg = f"📋 *TOP TRADERS MONITORADOS*\n\n"
    msg += f"Total: {len(top_traders)} traders\n\n"
    for i, t in enumerate(top_traders[:10], 1):
        addr = t.get('address', 'N/A')
        msg += f"{i}. 🐋 `{addr[:8]}...{addr[-8:]}`\n"
    msg += f"\n⏰ Atualizado em {datetime.now().strftime('%H:%M')}"
    
    send(msg)
    print(f"[UPDATE] Top traders: {len(top_traders)} encontrados")

# ============================================================
# ANÁLISE ANTI-LIXO
# ============================================================
def is_lixo(token_info):
    """Verifica se o token é lixo (rug pull, honeypot, etc)"""
    if not token_info:
        return True, "Sem dados"
    
    # Honeypot
    if token_info.get('is_honeypot', False):
        return True, "HONEYPOT"
    
    # Taxa de venda alta
    sell_tax = token_info.get('sell_tax', 0) or 0
    if sell_tax > MAX_SELL_TAX:
        return True, f"TAXA VENDA {sell_tax}%"
    
    # Rug ratio
    if token_info.get('rug_ratio', 0) > 0.7:
        return True, "RUG RATIO"
    
    # DEV holdings alto
    dev_hold = token_info.get('creator_hold_percent', 0) or 0
    if dev_hold > MAX_DEV_HOLD:
        return True, f"DEV HOLD {dev_hold:.0f}%"
    
    # Top 10 holders concentrado
    top10 = token_info.get('top10_holder_rate', 0) or 0
    if top10 > MAX_TOP10_HOLDERS:
        return True, f"TOP10 {top10:.0f}%"
    
    return False, "OK"

# ============================================================
# ANALISAR TOKENS DOS TRADERS
# ============================================================
def analyze_trader_token(trader_addr, token_addr, token_info, activity):
    """Analisa um token comprado por um trader"""
    global stats
    
    try:
        # Dados do token
        symbol = token_info.get('symbol', '???')
        price = float(token_info.get('price', 0) or 0)
        volume_24h = float(token_info.get('volume_24h', 0) or 0)
        market_cap = float(token_info.get('market_cap', 0) or 0)
        price_change_1h = float(token_info.get('price_change_1h', 0) or 0)
        holder_count = int(token_info.get('holder_count', 0) or 0)
        smart_money_count = int(token_info.get('smart_degen_count', 0) or 0)
        
        # Filtros de qualidade
        if volume_24h < MIN_VOLUME:
            return
        if holder_count < MIN_HOLDERS:
            return
        if price_change_1h < MIN_PRICE_CHANGE:
            return
        if smart_money_count < MIN_SMART_MONEY:
            return
        
        # Score
        score = 0
        if price_change_1h > 20: score += 25
        elif price_change_1h > 10: score += 15
        if holder_count > 500: score += 25
        elif holder_count > 200: score += 15
        if smart_money_count > 10: score += 30
        elif smart_money_count > 5: score += 20
        if market_cap > 500000: score += 20
        elif market_cap > 100000: score += 10
        
        if score < MIN_SCORE:
            return
        
        # Marca como alertado
        with lock:
            if token_addr in tracked_tokens:
                return
            tracked_tokens[token_addr] = time.time()
            stats["tokens_found"] += 1
        
        # Confiança
        if score >= 80:
            confidence = "🟢 ELITE"
        elif score >= 70:
            confidence = "🟡 FORTE"
        else:
            confidence = "🟠 BOM"
        
        # Dados da compra
        buy_amount = activity.get('amount', 0)
        buy_price = activity.get('price', 0)
        
        tp1 = price * 1.8
        tp2 = price * 3.5
        tp3 = price * 7.0
        stop = price * 0.85
        
        msg = (
            f"🐋 *TOP TRADER COMPROU!*\n\n"
            f"Trader: `{trader_addr[:8]}...{trader_addr[-8:]}`\n"
            f"{confidence} *${symbol}*\n"
            f"`{token_addr[:8]}...{token_addr[-8:]}`\n\n"
            f"💲 Preço compra: `${buy_price:.8f}`\n"
            f"💲 Preço atual: `${price:.8f}`\n"
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
        print(f"[ANALYZE] Erro: {e}")

# ============================================================
# MONITORAR TRADERS
# ============================================================
def monitor_traders():
    print("[MONITOR] Iniciando monitoramento de top traders...")
    
    while True:
        try:
            # Atualiza lista de traders
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
                
                # Busca atividades
                activities = get_trader_activity(trader_addr)
                if not activities:
                    continue
                
                for activity in activities:
                    try:
                        # Verifica se é compra
                        side = activity.get('side', '').lower()
                        if side != 'buy':
                            continue
                        
                        token_addr = activity.get('token_address') or activity.get('address')
                        if not token_addr:
                            continue
                        
                        # Verifica se já processou este token
                        with lock:
                            if token_addr in tracked_tokens:
                                continue
                        
                        # Busca info do token (com dados de segurança)
                        token_info = get_token_info(token_addr)
                        if not token_info:
                            continue
                        
                        # ANTI-LIXO: Verifica se é rug/honeypot
                        is_rug, motivo = is_lixo(token_info)
                        if is_rug:
                            print(f"[FILTRO] Token {token_addr[:8]}... bloqueado: {motivo}")
                            continue
                        
                        # Analisa o token
                        analyze_trader_token(trader_addr, token_addr, token_info, activity)
                        
                    except Exception as e:
                        print(f"[MONITOR] Erro ao processar atividade: {e}")
                
                time.sleep(2)  # Pausa entre traders
            
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
                f"📊 *RELATÓRIO 2H*\n\n"
                f"🐋 Traders monitorados: `{traders}`\n"
                f"📈 Alertas enviados: `{alerts}`\n"
                f"💎 Tokens analisados: `{tokens}`\n\n"
                f"🛡️ Filtros anti-lixo:\n"
                f"• Honeypot ❌\n"
                f"• Taxa venda ≤ {MAX_SELL_TAX}%\n"
                f"• DEV hold ≤ {MAX_DEV_HOLD}%\n"
                f"• Top10 ≤ {MAX_TOP10_HOLDERS}%\n\n"
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
    return f"TOP TRADERS | traders={traders} | alerts={alerts} | tokens={tokens}"

@app.route("/stats")
def get_stats():
    with lock:
        return {
            "alerts": stats["alerts"],
            "tokens_found": stats["tokens_found"],
            "traders_found": stats["traders_found"],
            "tracked": len(tracked_tokens),
            "filters": {
                "min_volume": MIN_VOLUME,
                "min_holders": MIN_HOLDERS,
                "max_top10": MAX_TOP10_HOLDERS,
                "max_dev_hold": MAX_DEV_HOLD,
                "max_sell_tax": MAX_SELL_TAX,
                "min_price_change": MIN_PRICE_CHANGE,
                "min_smart_money": MIN_SMART_MONEY,
                "min_score": MIN_SCORE
            }
        }

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v21.0 (TOP TRADERS + ANTI-LIXO) ===")
    
    identify_top_traders()
    
    send("🟢 *WHALE HUNTER v21.0 ONLINE*\n\n"
         "🐋 *TOP TRADERS MONITORADOS*\n"
         "🛡️ Filtros anti-lixo:\n"
         f"• Honeypot ❌ | Taxa venda ≤ {MAX_SELL_TAX}%\n"
         f"• DEV hold ≤ {MAX_DEV_HOLD}% | Top10 ≤ {MAX_TOP10_HOLDERS}%\n\n"
         f"📊 Filtros de qualidade:\n"
         f"• Volume ≥ `${MIN_VOLUME:,.0f}`\n"
         f"• Alta ≥ `{MIN_PRICE_CHANGE}%`\n"
         f"• Smart Money ≥ `{MIN_SMART_MONEY}`\n"
         f"• Score ≥ `{MIN_SCORE}`\n\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
