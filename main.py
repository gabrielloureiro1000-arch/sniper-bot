# ============================================================
# WHALE HUNTER v19.7 - CORRIGE PARSER DO DATA
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
MIN_VOLUME = 1000
MIN_BUYS = 3
MIN_PRICE_CHANGE = 0.3

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
# GMGN CLI
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

def get_trending_tokens(chain="sol", interval="1h", limit=20):
    """Busca tokens em alta via GMGN CLI"""
    cmd = [
        'gmgn-cli', 'market', 'trending',
        '--chain', chain,
        '--interval', interval,
        '--limit', str(limit),
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    
    # Verifica se a resposta é um dict com 'data'
    if result and isinstance(result, dict):
        print(f"[DEBUG] Chaves da resposta: {list(result.keys())}")
        
        # Se tem 'data' e é uma lista, retorna ela
        if 'data' in result:
            data = result['data']
            print(f"[DEBUG] data é do tipo: {type(data)}")
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Se 'data' for um dict, tenta extrair a lista
                for key, value in data.items():
                    if isinstance(value, list):
                        print(f"[DEBUG] Usando data['{key}'] como lista")
                        return value
                # Se não encontrar lista, retorna o dict como lista de um elemento
                return [data]
        
        # Tenta outras chaves comuns
        for key in ['tokens', 'items', 'results']:
            if key in result and isinstance(result[key], list):
                return result[key]
    
    return []

def get_trenches_tokens(chain="sol", limit=20):
    """Busca novos tokens (Trenches) via GMGN CLI"""
    cmd = [
        'gmgn-cli', 'market', 'trenches',
        '--chain', chain,
        '--type', 'new_creation',
        '--limit', str(limit),
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        data = result['data']
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    return value
            return [data]
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

def get_token_traders(chain, address):
    """Busca top traders de um token"""
    cmd = [
        'gmgn-cli', 'token', 'traders',
        '--chain', chain,
        '--address', address,
        '--limit', '10',
        '--raw'
    ]
    result = gmgn_cli_command(cmd)
    if result and 'data' in result:
        return result['data']
    return []

# ============================================================
# ANÁLISE DO TOKEN
# ============================================================
def analyze_tokens(tokens, source="trending"):
    """Analisa os tokens encontrados e envia alertas"""
    global stats
    
    print(f"[DEBUG] Tokens recebidos: {len(tokens)} - Tipo: {type(tokens)}")
    if tokens:
        print(f"[DEBUG] Primeiro token: {str(tokens[0])[:300]}")
    
    valid_tokens = []
    for token in tokens:
        if isinstance(token, str):
            if token == "rank":
                continue
            try:
                token = json.loads(token)
            except:
                continue
        
        if isinstance(token, dict):
            address = token.get('address') or token.get('token_address') or token.get('id')
            if address:
                valid_tokens.append(token)
                continue
            
            for key in ['token', 'data', 'info']:
                if key in token and isinstance(token[key], dict):
                    inner = token[key]
                    address = inner.get('address') or inner.get('token_address') or inner.get('id')
                    if address:
                        token['address'] = address
                        valid_tokens.append(token)
                        break
    
    if not valid_tokens:
        print(f"[DEBUG] Nenhum token válido encontrado em {source}")
        return
    
    print(f"[DEBUG] Analisando {len(valid_tokens)} tokens válidos de {source}")
    
    for token in valid_tokens:
        try:
            address = token.get('address') or token.get('token_address') or token.get('id')
            if not address:
                continue
            
            with lock:
                if address in tracked_tokens:
                    continue
            
            symbol = token.get('symbol', '???')
            price = float(token.get('price', 0) or 0)
            volume_24h = float(token.get('volume_24h', 0) or token.get('volume', 0) or 0)
            market_cap = float(token.get('market_cap', 0) or 0)
            price_change_1h = float(token.get('price_change_1h', 0) or token.get('price_change', {}).get('1h', 0) or 0)
            holder_count = int(token.get('holder_count', 0) or token.get('holders', 0) or 0)
            smart_money_count = int(token.get('smart_degen_count', 0) or token.get('smart_money', 0) or 0)
            
            if volume_24h < MIN_VOLUME:
                continue
            if holder_count < MIN_BUYS:
                continue
            if price_change_1h < MIN_PRICE_CHANGE:
                continue
            
            # Score
            score = 0
            if price_change_1h > 10: score += 20
            elif price_change_1h > 5: score += 10
            elif price_change_1h > 2: score += 5
            if holder_count > 100: score += 20
            elif holder_count > 50: score += 10
            elif holder_count > 20: score += 5
            if smart_money_count > 5: score += 30
            elif smart_money_count > 2: score += 15
            elif smart_money_count > 0: score += 5
            if market_cap > 100000: score += 20
            elif market_cap > 50000: score += 10
            elif market_cap > 20000: score += 5
            
            if score < 25:
                continue
            
            with lock:
                tracked_tokens[address] = time.time()
                stats["tokens_found"] += 1
            
            confidence = "🔴"
            if score >= 70:
                confidence = "🟢 FORTE"
            elif score >= 50:
                confidence = "🟡 MÉDIO"
            
            tp1 = price * 1.8
            tp2 = price * 3.5
            tp3 = price * 7.0
            stop = price * 0.85
            
            msg = (
                f"{confidence} *TOKEN PROMISSOR DETECTADO*\n"
                f"Fonte: {source.upper()}\n\n"
                f"💎 *${symbol}*\n"
                f"`{address[:8]}...{address[-8:]}`\n\n"
                f"💲 Preço: `${price:.8f}`\n"
                f"📊 Volume 24h: `${volume_24h:,.0f}`\n"
                f"💰 Market Cap: `${market_cap:,.0f}`\n"
                f"📈 Alta 1h: `{price_change_1h:+.1f}%`\n"
                f"👥 Holders: `{holder_count}`\n"
                f"🧠 Smart Money: `{smart_money_count}`\n"
                f"⭐ Score: `{score:.0f}`\n\n"
                f"🎯 TP1: `1.8x` | TP2: `3.5x` | TP3: `7x`\n"
                f"🛑 STOP: `-15%`\n\n"
                f"🔍 GMGN: https://gmgn.ai/sol/token/{address}\n"
                f"📊 DEX: https://dexscreener.com/solana/{address}\n\n"
                f"⚠️ *MODO MANUAL* - Analise antes de comprar"
            )
            
            send(msg)
            stats["alerts"] += 1
            print(f"[ALERTA] {symbol} - Score: {score:.0f}")
            
        except Exception as e:
            print(f"[ANALYZE] Erro: {e}")

# ============================================================
# MONITORAR TOKENS
# ============================================================
def monitor_tokens():
    print("[MONITOR] Iniciando monitoramento com GMGN CLI...")
    
    while True:
        try:
            print("[MONITOR] Buscando tokens em alta...")
            trending = get_trending_tokens(limit=20)
            if trending:
                print(f"[MONITOR] Encontrados {len(trending)} tokens em alta")
                analyze_tokens(trending, "trending")
            else:
                print("[MONITOR] Nenhum token em alta encontrado")
            
            print("[MONITOR] Buscando novos tokens...")
            trenches = get_trenches_tokens(limit=10)
            if trenches:
                print(f"[MONITOR] Encontrados {len(trenches)} novos tokens")
                analyze_tokens(trenches, "trenches")
            else:
                print("[MONITOR] Nenhum novo token encontrado")
            
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
                f"📊 *RELATÓRIO 2H*\n\n"
                f"📈 Alertas enviados: `{alerts}`\n"
                f"💎 Tokens analisados: `{tokens}`\n\n"
                f"🔍 Monitorando tokens em alta e novos"
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
    return f"WHALE HUNTER v19.7 | alerts={alerts} | tokens={tokens}"

@app.route("/debug")
def debug_output():
    """Endpoint para visualizar a saída do CLI"""
    try:
        with open("/tmp/cli_output.txt", "r") as f:
            content = f.read()
        return f"<pre>{content}</pre>"
    except FileNotFoundError:
        return "Arquivo /tmp/cli_output.txt não encontrado"
    except Exception as e:
        return f"Erro ao ler arquivo: {e}"

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v19.7 (PARSER CORRIGIDO) ===")
    
    test_result = get_trending_tokens(limit=1)
    if test_result:
        print(f"[TESTE] ✅ GMGN CLI funcionando! Retornou {len(test_result)} tokens")
    else:
        print("[TESTE] ⚠️ GMGN CLI não retornou dados - verifique o debug")
    
    send("🟢 *WHALE HUNTER v19.7 ONLINE*\n\n"
         "🐋 *GMGN CLI CONECTADO*\n"
         "🔍 Monitorando tokens em tempo real\n"
         "📝 Alertas completos para análise\n\n"
         "⚠️ *MODO MANUAL* - Você decide se compra ou vende")
    
    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()
    threading.Thread(target=monitor_tokens, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    print(f"=== BOT RODANDO na porta {port} ===")
    app.run(host="0.0.0.0", port=port)
