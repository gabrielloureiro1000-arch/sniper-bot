# ============================================================
# WHALE HUNTER v9.0 - MODO AGGRESSIVO (para testes)
# ============================================================
# Filtros muito mais leves para gerar alertas imediatamente
# ============================================================

import os
import time
import threading
import requests
import telebot
from flask import Flask
from queue import Queue, Empty
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

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
# CONFIGURAÇÕES - MODO AGGRESSIVO (para gerar alertas)
# ============================================================
SCAN_DELAY = 0.5
REPORT_INTERVAL = 7200

# Filtros MUITO mais leves
MIN_LIQ = 2000              # reduzido de 4000
MAX_LIQ = 200000            # aumentado
MIN_BUYS = 3                # reduzido de 6 - qualquer token com 3 compras
MAX_BUYS = 1000
MIN_RATIO = 1.2             # reduzido de 2.0 - apenas um pouco mais buys que sells
MIN_VOL5M = 300             # reduzido de 600
MIN_AGE = 0.1
MAX_AGE = 120               # aumentado para 2 horas
MIN_M5 = 0.5                # qualquer alta positiva
MAX_M5 = 500
MAX_TOP10 = 50              # mais tolerante
MIN_SMART = 0               # ZERO - não exige smart money
MIN_WHALE_AVG_SIZE = 100    # reduzido drasticamente
MIN_HOLDER_GROWTH_PCT = 0   # zero
ENABLE_HOLDER_REQUIREMENT = False

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
history = {}
stats = {"sent": 0, "green": 0, "yellow": 0}
tg_queue = Queue()

# ============================================================
# TELEGRAM
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
# API GMGN simplificada
# ============================================================
def get_gmgn(addr):
    try:
        r = session.get(f"https://gmgn.ai/api/v1/token/sol/{addr}",
                        headers={"User-Agent": "Mozilla/5.0",
                                 "Referer": "https://gmgn.ai/"},
                        timeout=5)
        if r.status_code != 200:
            return None
        d = r.json().get("data", {}) or {}
        return {
            "smart": d.get("smart_degen_count", 0) or 0,
            "holders": d.get("holder_count", 0) or 0,
            "top10": d.get("top10_holder_rate", 0) or 0,
            "burn": d.get("burn_ratio", 0) or 0,
            "rug": d.get("rug_ratio", 0) or 0,
            "tax": d.get("sell_tax", 0) or 0,
            "honeypot": d.get("is_honeypot", False),
            "dev": d.get("creator_hold_percent", 0) or 0,
        }
    except Exception as e:
        print(f"[GMGN] Erro: {e}")
        return None

# ============================================================
# ANTI RUG básico
# ============================================================
def is_lixo(g):
    if not g:
        return False, ""
    if g.get("honeypot") is True:
        return True, "HONEYPOT"
    if g.get("tax", 0) > 30:
        return True, f"TAX {g['tax']}%"
    if g.get("rug", 0) > 0.9:
        return True, "RUG"
    dev = g.get("dev", 0)
    if dev and float(dev) > 20:
        return True, f"DEV {dev:.0f}%"
    return False, ""

# ============================================================
# PROCESSAMENTO PRINCIPAL (versão simplificada)
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

        # Evita repetição (30 minutos de cooldown)
        with lock:
            old = history.get(addr)
            if old and time.time() - old["ts"] < 1800:
                return

        # Tenta pegar dados GMGN (não obrigatório)
        g = get_gmgn(addr)
        lixo, motivo = is_lixo(g)
        if lixo:
            return

        symbol = base.get("symbol", "???")
        now_ts = time.time()

        with lock:
            history[addr] = {"symbol": symbol, "price": price_val, "ts": now_ts}
            stats["sent"] += 1

        # Prepara mensagem
        avg_buy = vol5m / max(buys, 1)
        holders = g.get("holders", 0) if g else 0
        smart = g.get("smart", 0) if g else 0
        
        # Emoji baseado na qualidade (para orientação)
        quality = "🟢" if (buys >= 20 and ratio >= 2 and smart >= 2) else "🟡" if (buys >= 10 and ratio >= 1.5) else "🔵"
        quality_label = "ELITE" if quality == "🟢" else "WHALE" if quality == "🟡" else "EARLY"

        msg = (
            f"{quality} *{quality_label} DETECTED* {quality}\n\n"
            f"💎 *${symbol}*\n"
            f"`{addr[:8]}...{addr[-8:]}`\n\n"
            f"💲 Preço: `${price_val:.10f}`\n"
            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n"
            f"🐋 Ticket médio: `${avg_buy:.0f}`\n\n"
            f"🔥 Buys: `{buys}` | 📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n"
            f"📈 5m: `{m5:+.1f}%`\n"
            f"⏰ Age: `{age:.1f} min`\n\n"
            f"🧠 Smart: `{smart}` | 👥 Holders: `{holders}`\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 SUGESTÃO:\n"
            f"{'✅ FORTE - Considere entrar' if quality == '🟢' else '⚠️ MÉDIO - Analise antes' if quality == '🟡' else '🔍 INÍCIO - Monitore'}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"🟢 GMGN: https://gmgn.ai/sol/token/{addr}\n"
            f"📊 DEX: https://dexscreener.com/solana/{addr}"
        )
        send(msg)
        
        # Log no console para debug
        print(f"[ALERTA] {symbol} - buys:{buys} ratio:{ratio:.1f} vol:{vol5m:.0f}")

    except Exception as e:
        print(f"[PROCESS] {e}")

# ============================================================
# SCANNER
# ============================================================
def scan():
    idx = 0
    while True:
        try:
            url = ENDPOINTS[idx % len(ENDPOINTS)]
            idx += 1
            print(f"[SCAN] Buscando: {url}")
            r = session.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                print(f"[SCAN] Encontrou {len(pairs)} pares")
                for pair in pairs:
                    processar(pair)
            else:
                print(f"[SCAN] HTTP {r.status_code}")
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
            txt = (
                f"📊 *RELATÓRIO 2H*\n\n"
                f"📤 Alertas enviados: `{st['sent']}`\n"
                f"🟢 Elite: `{st['green']}`\n"
                f"🟡 Whale: `{st['yellow']}`\n\n"
                f"Bot rodando em modo AGGRESSIVO\n"
                f"Filtros leves para detectar qualquer movimento"
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
    return f"WHALE HUNTER v9.0 | alertas={stats['sent']} | tokens={len(history)}"

@app.route("/stats")
def get_stats():
    return {
        "alertas_enviados": stats["sent"],
        "tokens_unicos": len(history),
        "fila_tg": tg_queue.qsize()
    }

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=== INICIANDO WHALE HUNTER v9.0 (MODO AGGRESSIVO) ===")
    
    send("🟢 *WHALE HUNTER v9.0 ONLINE - MODO AGGRESSIVO*\n\n"
         "⚡ Filtros reduzidos para DETECTAR TUDO\n"
         "📊 Agora vamos ver o que aparece\n"
         "🔍 Ajuste os filtros depois se quiser menos alerts\n\n"
         f"✅ MIN_BUYS={MIN_BUYS} | MIN_RATIO={MIN_RATIO} | MIN_VOL5M={MIN_VOL5M}\n"
         f"✅ Smart Money = {MIN_SMART} (não obrigatório)")

    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()

    # 5 threads apenas para começar
    for _ in range(5):
        threading.Thread(target=scan, daemon=True).start()
        time.sleep(0.2)

    print(f"=== BOT RODANDO na porta {int(os.environ.get('PORT', 10000))} ===")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
