# ============================================================
# WHALE HUNTER v20.2 - SMART MONEY + KOLs (CORRIGIDO)
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
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
top_traders = []
tracked_tokens = {}
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
# GMGN CLI - COMANDOS CORRIGIDOS
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
            print(f"[CLI] Resposta: {result.stdout[:200]}")
            return None
        
    except subprocess.TimeoutExpired:
        print("[CLI] Timeout")
        return None
    except Exception as e:
        print(f"[CLI] Exceção: {e}")
        return None

def get_smart_money():
    """Busca Smart Money (traders mais lucrativos)"""
    # Usando --chain sol explicitamente
    cmd = ['gmgn-cli', 'track', 'smartmoney', '--chain', 'sol', '--limit', '20', '--raw']
    result = gmgn_cli_command(cmd)
    
    # Se falhar, tenta sem o --chain (algumas versões podem não precisar)
    if not result:
        print("[DEBUG] Tentando smartmoney sem --chain...")
        cmd = ['gmgn-cli', 'track', 'smartmoney', '--limit', '20', '--raw']
        result = gmgn_cli_command(cmd)
    
    if result and 'data' in result:
        return result['data']
    return []

def get_kols():
    """Busca KOLs (influenciadores)"""
    cmd = ['gmgn-cli', 'track', 'kol', '--chain', 'sol', '--limit', '20', '--raw']
    result = gmgn_cli_command(cmd)
    
    if not result:
        print("[DEBUG] Tentando kol sem --chain...")
        cmd = ['gmgn-cli', 'track', 'kol', '--limit', '20', '--raw']
        result = gmgn_cli_command(cmd)
    
    if result and 'data' in result:
        return result['data']
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

def get_token_info(address):
    """Busca informações detalhadas de um token"""
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

def get_trending_tokens(limit=20):
    """Busca tokens em alta (fallback)"""
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

# ============================================================
# IDENTIFICAR TOP TRADERS
# ============================================================
def identify_top_traders():
    """Identifica os melhores traders (Smart Money + KOLs)"""
    global top_traders, stats, last_trader_update
    
    print("[UPDATE] Buscando Smart Money e KOLs...")
    send("🔄 *Atualizando lista de Top Traders*")
    
    # Busca Smart Money
    smart_money = get_smart_money()
    print(f"[UPDATE] Smart Money encontrados: {len(smart_money) if smart_money else 0}")
    
    # Busca KOLs
    kols = get_kols()
    print(f"[UPDATE] KOLs encontrados: {len(kols) if kols else 0}")
    
    # Se não encontrou nada, tenta usar tokens em alta como fallback
    if not smart_money and not kols:
        print("[UPDATE] Nenhum trader encontrado. Usando tokens em alta como fallback...")
        trending = get_trending_tokens(limit=10)
        if trending:
            # Cria traders fictícios baseados nos tokens em alta
            fallback_traders = []
            for token in trending[:5]:
                addr = token.get('address', '')
                if addr:
                    fallback_traders.append({
                        'address': addr,
                        'type': 'trending_fallback'
                    })
            if fallback_traders:
                with lock:
                    top_traders = fallback_traders
                    stats["traders_found"] = len(top_traders)
                    last_trader_update = time.time()
                
                send(f"📋 *TOP TRADERS - FALLBACK*\n\n"
                     f"Usando tokens em alta como referência:\n"
                     + "\n".join([f"🐋 `{t.get('address', 'N/A')[:8]}...`" for t in top_traders]))
                return
    
    # Combina as listas
    combined = {}
    
    if smart_money:
        for trader in smart_money:
            addr = trader.get('address')
            if addr:
                combined[addr] = trader
    
    if kols:
        for trader in kols:
            addr = trader.get('address')
            if addr and addr not in combined:
                combined[addr] = trader
    
    traders_list = list(combined.values())
    
    if not traders_list:
        print("[UPDATE] Nenhum trader encontrado")
        send("⚠️ *Nenhum trader encontrado no momento*")
        return
    
    with lock:
        top_traders = traders_list[:15]
        stats["traders_found"] = len(top_traders)
        last_trader_update = time.time()
    
    msg = f"📋 *TOP TRADERS MONITORADOS*\n\n"
    msg += f"Smart Money + KOLs: {len(top_traders)} traders\n\n"
    for i, t in enumerate(top_traders[:10], 1):
        addr = t.get('address', 'N/A')
        msg += f"{i}. 🐋 `{addr[:8]}...{addr[-8:]}`\n"
    msg += f"\n⏰ Atualizado em {datetime.now().strftime('%H:%M')}"
    
    send(msg)
    print(f"[UPDATE] Top traders: {len(top_traders)} encontrados")

# ============================================================
# MONITORAR TRADERS
# ============================================================
def monitor_traders():
    """Monitora as compras dos top traders"""
    global last_trader_update, stats
    
    print("[MONITOR] Iniciando monitoramento...")
    
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
                
                # Busca atividades
                activities = get_trader_activity(trader_addr)
                
                if not activities:
                    continue
                
                for activity in activities:
                    try:
                        side = activity.get('side', '').lower()
                        if side != 'buy':
                            continue
                        
                        token_addr = activity.get('token_address') or activity.get('address')
                        if not token_addr:
                            continue
                        
                        with lock:
                            if token_addr in tracked_tokens:
                                continue
                            tracked_tokens[token_addr] = time.time()
                        
                        # Busca info do token
                        token_info = get_token_info(token_addr)
                        if not token_info:
                            continue
                        
                        symbol = token_info.get('symbol', '???')
                        price = float(token_info.get('price', 0) or 0)
                        volume_24h = float(token_info.get('volume_24h', 0) or 0)
                        market_cap = float(token_info.get('market_cap', 0) or 0)
                        price_change_1h = float(token_info.get('price_change_1h', 0) or 0)
                        holder_count = int(token_info.get('holder_count', 0) or 0)
                        smart_money_count = int(token_info.get('smart_degen_count', 0) or 0)
                        
                        # Score
                        score = 0
                        if price_change_1h > 10: score += 20
                        elif price_change_1h > 5: score += 10
                        if holder_count > 100: score += 20
                        elif holder_count > 50: score += 10
                        if smart_money_count > 5: score += 30
                        elif smart_money_count > 2: score += 15
                        if market_cap > 100000: score += 20
                        elif market_cap > 50000: score += 10
                        
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
                        print(f"[ALERTA] {symbol} - Trader: {trader_addr[:8]}...")
                        
                    except Exception as e:
                        print(f"[MONITOR] Erro: {e}")
                
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
                traders = stats["traders_found"]
            
            txt = (
                f"📊 *RELATÓRIO 2H*\n\n"
                f"🐋 Traders monitorados: `{traders}`\n"
                f"📈 Alertas enviados: `{alerts}`\n\n"
                f"🔍 Smart Money + KOLs\n"
                f"✅ *MODO MANUAL*"
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
    except:
        return "Arquivo não encontrado"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v20.2 (CORRIGIDO) ===")
    
    identify_top_traders()
    
    send("🟢 *WHALE HUNTER v20.2 ONLINE*\n\n"
         "🐋 *SMART MONEY + KOLs*\n"
         "🔍 Monitorando compras dos melhores traders\n"
         "📝 Alertas APENAS quando eles compram\n\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_traders, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
