# ============================================================
# WHALE HUNTER v23.0 - SMART MONEY MONITOR
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

# ============================================================
# FILTROS - FOCADO EM SMART MONEY
# ============================================================
MIN_VOLUME = 20000
MIN_HOLDERS = 50
MAX_TOP10_HOLDERS = 40
MAX_DEV_HOLD = 15
MAX_SELL_TAX = 20
MIN_PRICE_CHANGE = 3.0
MIN_SMART_MONEY = 3      # PELO MENOS 3 SMART MONEY
MIN_SCORE = 50

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
tracked_tokens = {}
stats = {"alerts": 0, "tokens_found": 0}
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
# GMGN CLI - APENAS COMANDOS QUE FUNCIONAM
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

def get_trending_tokens(limit=30):
    """Busca tokens em alta (FUNCIONA)"""
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
    """Busca informações detalhadas de um token (FUNCIONA)"""
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
# ANALISAR TOKENS - FOCADO EM SMART MONEY
# ============================================================
def analyze_tokens(tokens, source="trending"):
    """Analisa tokens e envia alertas APENAS com Smart Money"""
    global stats
    
    print(f"[DEBUG] Analisando {len(tokens)} tokens de {source}")
    
    smart_money_tokens = []
    
    for token in tokens:
        try:
            address = token.get('address') or token.get('token_address') or token.get('id')
            if not address:
                continue
            
            # Verifica se já foi alertado
            with lock:
                if address in tracked_tokens:
                    continue
            
            # Dados básicos
            symbol = token.get('symbol', '???')
            price = float(token.get('price', 0) or 0)
            volume_24h = float(token.get('volume_24h', 0) or token.get('volume', 0) or 0)
            market_cap = float(token.get('market_cap', 0) or 0)
            price_change_1h = float(token.get('price_change_1h', 0) or token.get('price_change_percent', 0) or 0)
            holder_count = int(token.get('holder_count', 0) or token.get('holders', 0) or 0)
            smart_money_count = int(token.get('smart_degen_count', 0) or token.get('smart_money', 0) or 0)
            
            # 🔥 FILTRO PRINCIPAL: SÓ TOKENS COM SMART MONEY
            if smart_money_count < MIN_SMART_MONEY:
                continue
            
            # Filtros básicos
            if volume_24h < MIN_VOLUME:
                continue
            if holder_count < MIN_HOLDERS:
                continue
            if price_change_1h < MIN_PRICE_CHANGE:
                continue
            
            # Busca detalhes do token (com dados de segurança)
            token_info = get_token_info(address)
            if not token_info:
                continue
            
            # ANTI-LIXO
            is_rug, motivo = is_lixo(token_info)
            if is_rug:
                print(f"[FILTRO] {symbol} bloqueado: {motivo}")
                continue
            
            # Atualiza com dados detalhados
            symbol = token_info.get('symbol', symbol)
            price = float(token_info.get('price', price) or 0)
            holder_count = int(token_info.get('holder_count', holder_count) or 0)
            smart_money_count = int(token_info.get('smart_degen_count', smart_money_count) or 0)
            
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
                continue
            
            smart_money_tokens.append({
                'address': address,
                'symbol': symbol,
                'price': price,
                'volume_24h': volume_24h,
                'market_cap': market_cap,
                'price_change_1h': price_change_1h,
                'holder_count': holder_count,
                'smart_money_count': smart_money_count,
                'score': score,
                'token_info': token_info
            })
            
        except Exception as e:
            print(f"[ANALYZE] Erro: {e}")
    
    # Ordena por Smart Money (mais primeiro)
    smart_money_tokens.sort(key=lambda x: x['smart_money_count'], reverse=True)
    
    # Envia alertas para os top tokens com Smart Money
    for token_data in smart_money_tokens[:10]:  # Máximo 10 por ciclo
        with lock:
            if token_data['address'] in tracked_tokens:
                continue
            tracked_tokens[token_data['address']] = time.time()
            stats["tokens_found"] += 1
        
        address = token_data['address']
        symbol = token_data['symbol']
        price = token_data['price']
        volume_24h = token_data['volume_24h']
        market_cap = token_data['market_cap']
        price_change_1h = token_data['price_change_1h']
        holder_count = token_data['holder_count']
        smart_money_count = token_data['smart_money_count']
        score = token_data['score']
        token_info = token_data['token_info']
        
        # Confiança
        if score >= 80:
            confidence = "🟢 ELITE"
        elif score >= 70:
            confidence = "🟡 FORTE"
        else:
            confidence = "🟠 BOM"
        
        tp1 = price * 1.8
        tp2 = price * 3.5
        tp3 = price * 7.0
        stop = price * 0.85
        
        msg = (
            f"{confidence} *SMART MONEY DETECTADO!*\n"
            f"🧠 {smart_money_count} Smart Money comprando\n\n"
            f"💎 *${symbol}*\n"
            f"`{address[:8]}...{address[-8:]}`\n\n"
            f"💲 Preço: `${price:.8f}`\n"
            f"📊 Volume 24h: `${volume_24h:,.0f}`\n"
            f"💰 Market Cap: `${market_cap:,.0f}`\n"
            f"📈 Alta 1h: `{price_change_1h:+.1f}%`\n"
            f"👥 Holders: `{holder_count}`\n"
            f"🧠 Smart Money: `{smart_money_count}`\n"
            f"⭐ Score: `{score:.0f}`\n\n"
            f"🛡️ Segurança: ✅ Aprovado\n"
            f"🔒 Taxa venda: `{token_info.get('sell_tax', 0)}%`\n"
            f"🏦 Top10: `{token_info.get('top10_holder_rate', 0)}%`\n"
            f"👨‍💻 DEV hold: `{token_info.get('creator_hold_percent', 0)}%`\n\n"
            f"🎯 TP1: `1.8x` | TP2: `3.5x` | TP3: `7x`\n"
            f"🛑 STOP: `-15%`\n\n"
            f"🔍 GMGN: https://gmgn.ai/sol/token/{address}\n"
            f"📊 DEX: https://dexscreener.com/solana/{address}\n\n"
            f"⚠️ *MODO MANUAL* - Analise antes de comprar"
        )
        
        send(msg)
        stats["alerts"] += 1
        print(f"[ALERTA] {symbol} - Smart Money: {smart_money_count} - Score: {score:.0f}")

# ============================================================
# MONITORAR TOKENS
# ============================================================
def monitor_tokens():
    print("[MONITOR] Iniciando monitoramento de Smart Money...")
    
    while True:
        try:
            print("[MONITOR] Buscando tokens em alta...")
            trending = get_trending_tokens(limit=30)
            if trending:
                print(f"[MONITOR] Encontrados {len(trending)} tokens em alta")
                analyze_tokens(trending, "trending")
            else:
                print("[MONITOR] Nenhum token em alta encontrado")
            
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
            
            txt = (
                f"📊 *RELATÓRIO 2H - SMART MONEY*\n\n"
                f"📈 Alertas enviados: `{alerts}`\n"
                f"💎 Tokens analisados: `{tokens}`\n\n"
                f"🧠 Smart Money ≥ `{MIN_SMART_MONEY}`\n"
                f"📊 Volume ≥ `${MIN_VOLUME:,.0f}`\n"
                f"📈 Alta ≥ `{MIN_PRICE_CHANGE}%`\n"
                f"👥 Holders ≥ `{MIN_HOLDERS}`\n"
                f"⭐ Score ≥ `{MIN_SCORE}`\n\n"
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
    return f"SMART MONEY | alerts={alerts} | tokens={tokens}"

@app.route("/stats")
def get_stats():
    with lock:
        return {
            "alerts": stats["alerts"],
            "tokens_found": stats["tokens_found"],
            "tracked": len(tracked_tokens),
            "filters": {
                "min_volume": MIN_VOLUME,
                "min_holders": MIN_HOLDERS,
                "min_smart_money": MIN_SMART_MONEY,
                "min_score": MIN_SCORE
            }
        }

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v23.0 (SMART MONEY) ===")
    
    send("🟢 *WHALE HUNTER v23.0 ONLINE*\n\n"
         "🧠 *SMART MONEY MONITOR*\n"
         f"🔍 Detectando tokens com ≥ {MIN_SMART_MONEY} Smart Money\n"
         f"📊 Volume ≥ `${MIN_VOLUME:,.0f}`\n"
         f"📈 Alta ≥ `{MIN_PRICE_CHANGE}%`\n"
         f"👥 Holders ≥ `{MIN_HOLDERS}`\n"
         f"⭐ Score ≥ `{MIN_SCORE}`\n\n"
         "🛡️ Anti-lixo ativo\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_tokens, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
