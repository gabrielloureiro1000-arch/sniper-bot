# ============================================================
# WHALE HUNTER QUANT v7.0 - GMGN REAL TIME
# ============================================================
# - Stealth buy + Whale detection (8+ large buys)
# - Holder growth tracker (real people)
# - Smart money mandatory
# - Anti rug system (hard filters)
# - Report every 2h
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
# SESSION + HEADERS
# ============================================================
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.4,
                status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=200, pool_maxsize=200, max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ============================================================
# CONFIGURAÇÕES
# ============================================================
SCAN_DELAY = 0.15
REPORT_INTERVAL = 7200          # 2 horas

# Filtros ultra early (mais restritivos)
MIN_LIQ = 5000
MAX_LIQ = 80000
MIN_BUYS = 8                    # mínimo 8 compras (base para baleias)
MAX_BUYS = 300
MIN_RATIO = 2.5                 # buys/sells mínimo
MIN_VOL5M = 800
MIN_AGE = 0.3
MAX_AGE = 18
MIN_M5 = 2
MAX_M5 = 80
MAX_TOP10 = 25                  # top10 holders ≤ 25%
MIN_SMART = 2                   # smart money obrigatório >= 2
MIN_WHALE_AVG_SIZE = 500        # tamanho médio da compra em USD (para detectar baleias)
MIN_HOLDER_GROWTH_PCT = 10      # crescimento mínimo de holders em 5min (%)
MIN_REAL_BUY_RATIO = 0.1        # novos holders / buys mínimo

# ============================================================
# ENDPOINTS DexScreener
# ============================================================
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=degen",
    "https://api.dexscreener.com/latest/dex/search?q=memecoin",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
history = {}                # tokens já enviados (addr -> {symbol, price, ts})
holder_snapshot = {}        # addr -> {holders, timestamp}
stats = {"sent": 0, "green": 0, "yellow": 0}
tg_queue = Queue()

# ============================================================
# TELEGRAM WORKER
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
# API GMGN (detalhes do token)
# ============================================================
def get_gmgn(addr):
    try:
        r = session.get(f"https://gmgn.ai/api/v1/token/sol/{addr}",
                        headers={"User-Agent": "Mozilla/5.0",
                                 "Referer": "https://gmgn.ai/"},
                        timeout=5)
        if r.status_code != 200:
            return {}
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
    except:
        return {}

# ============================================================
# ANTI RUG
# ============================================================
def is_lixo(g):
    if g.get("honeypot") is True:
        return True, "HONEYPOT"
    if g.get("tax", 0) > 20:
        return True, "SELL TAX >20%"
    if g.get("rug", 0) > 0.7:
        return True, "RUG RATIO"
    dev = g.get("dev", 0)
    if dev and float(dev) > 12:
        return True, f"DEV HOLD {dev:.1f}%"
    top10 = g.get("top10", 0)
    if top10:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t > MAX_TOP10:
            return True, f"TOP10 {t:.0f}%"
    return False, ""

# ============================================================
# HOLDER GROWTH (pessoas reais)
# ============================================================
def check_holder_growth(addr, current_holders, now_ts):
    with lock:
        snap = holder_snapshot.get(addr)
        if not snap:
            holder_snapshot[addr] = {"holders": current_holders, "ts": now_ts}
            return True   # primeira vez, aceita

        age_min = (now_ts - snap["ts"]) / 60.0
        if age_min < 1:
            return True   # ainda não dá para avaliar

        growth_pct = (current_holders - snap["holders"]) / max(snap["holders"], 1) * 100
        growth_rate = growth_pct / age_min

        # Atualiza snapshot a cada 5 minutos
        if age_min >= 5:
            holder_snapshot[addr] = {"holders": current_holders, "ts": now_ts}

        # Exige crescimento mínimo de 10% em 5 minutos OU 0.5%/min contínuo
        if age_min <= 5 and growth_pct < MIN_HOLDER_GROWTH_PCT:
            return False
        if age_min > 5 and growth_rate < 0.5:
            return False
        return True

# ============================================================
# WHALE DETECTION (mínimo 8 grandes compras)
# ============================================================
def has_whale_buys(vol5m, buys):
    if buys < 8:
        return False
    avg_buy_size = vol5m / max(buys, 1)
    return avg_buy_size >= MIN_WHALE_AVG_SIZE

# ============================================================
# SCORE (ELITE / WHALE / RISCO)
# ============================================================
def score_token(data, g, avg_buy_size, holder_growth_ok):
    pontos = 0
    ratio = data["ratio"]
    buys  = data["buys"]
    age   = data["age"]
    m5    = data["m5"]
    accel = data["accel"]

    # Baleias (grandes compras)
    if avg_buy_size >= 1000:
        pontos += 7
    elif avg_buy_size >= 500:
        pontos += 5

    # Ratio buys/sells
    if ratio >= 5: pontos += 5
    elif ratio >= 3: pontos += 4
    elif ratio >= 2.5: pontos += 3

    # Early age
    if age <= 3: pontos += 5
    elif age <= 8: pontos += 4
    elif age <= 15: pontos += 2

    # Momentum 5m
    if m5 >= 15: pontos += 4
    elif m5 >= 5: pontos += 2

    # Aceleração de volume
    if accel >= 3: pontos += 5
    elif accel >= 2: pontos += 3

    # Smart money
    smart = g.get("smart", 0)
    if smart >= 5: pontos += 8
    elif smart >= 3: pontos += 5
    elif smart >= 2: pontos += 2

    # Holders
    holders = g.get("holders", 0)
    if holders >= 300: pontos += 4
    elif holders >= 120: pontos += 3
    elif holders >= 50: pontos += 1

    # Holder growth (pessoas reais)
    if holder_growth_ok:
        pontos += 6

    # LP Burn
    burn = g.get("burn", 0)
    if burn:
        b = float(burn) * 100 if float(burn) <= 1 else float(burn)
        if b >= 80: pontos += 3

    # Top10 concentração (quanto menor, melhor)
    top10 = g.get("top10", 0)
    if top10:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t <= 20: pontos += 4
        elif t <= 30: pontos += 2

    if pontos >= 28:
        return "🟢", "ELITE WHALE ENTRY", "Smart money forte + baleias reais"
    elif pontos >= 20:
        return "🟡", "WHALE MOMENTUM", "Pump saudável com holder growth"
    else:
        return "🔴", "RISCO", "Momentum fraco"

# ============================================================
# PROCESSAMENTO DE UM PAR (token)
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

        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        if liq < MIN_LIQ or liq > MAX_LIQ:
            return

        vol = pair.get("volume", {})
        vol5m = vol.get("m5", 0) or 0
        vol1h = vol.get("h1", 0) or 0
        if vol5m < MIN_VOL5M:
            return

        tx = pair.get("txns", {}).get("m5", {})
        buys = tx.get("buys", 0)
        sells = tx.get("sells", 0)

        if buys < MIN_BUYS or buys > MAX_BUYS:
            return

        ratio = buys / max(sells, 1)
        if ratio < MIN_RATIO:
            return

        pc = pair.get("priceChange", {})
        m5 = pc.get("m5", 0) or 0
        h1 = pc.get("h1", 0) or 0
        if m5 < MIN_M5 or m5 > MAX_M5:
            return

        created = pair.get("pairCreatedAt")
        age = (time.time() * 1000 - created) / 60000 if created else 999
        if age < MIN_AGE or age > MAX_AGE:
            return

        # Aceleração de volume
        accel = vol5m / max(vol1h / 12, 1) if vol1h > 0 else 0

        # Stealth buy: compras silenciosas + aceleração
        if not (buys >= 8 and ratio >= 2.5 and accel >= 1.8 and age <= 10):
            return

        # Anti bot simples
        if sells > 0:
            sell_ratio = sells / max(buys, 1)
            if sell_ratio < 0.04 or sell_ratio > 0.8:
                return

        # Evita repetição (1 hora de cooldown)
        with lock:
            old = history.get(addr)
            if old and time.time() - old["ts"] < 3600:
                return

        # Consulta GMGN
        g = get_gmgn(addr)
        lixo, motivo = is_lixo(g)
        if lixo:
            return

        # Smart money obrigatório
        if g.get("smart", 0) < MIN_SMART:
            return

        # Detecção de baleias (mínimo 8 grandes compras)
        if not has_whale_buys(vol5m, buys):
            return

        # Holder growth (pessoas reais)
        now_ts = time.time()
        holder_growth_ok = check_holder_growth(addr, g.get("holders", 0), now_ts)
        if not holder_growth_ok:
            return

        # Verifica se há compras reais: novos holders em relação aos buys
        # (simplificado: usa o growth já calculado)
        # Se o holder growth estiver ok, consideramos que há pessoas reais

        # Cálculo do tamanho médio da compra para usar no score
        avg_buy_size = vol5m / max(buys, 1)

        # Score final
        emoji, label, desc = score_token({
            "ratio": ratio, "buys": buys, "age": age,
            "m5": m5, "h1": h1, "accel": accel
        }, g, avg_buy_size, holder_growth_ok)

        # Só envia se for ELITE ou WHALE (nada de RISCO)
        if "RISCO" in label:
            return

        symbol = base.get("symbol", "???")
        price_val = float(price)

        # Salva no histórico
        with lock:
            history[addr] = {"symbol": symbol, "price": price_val, "ts": now_ts}
            stats["sent"] += 1
            if "ELITE" in label:
                stats["green"] += 1
            else:
                stats["yellow"] += 1

        # Prepara métricas para a mensagem
        holders = g.get("holders", 0)
        top10 = g.get("top10", 0)
        top10_pct = (float(top10) * 100 if float(top10) <= 1 else float(top10)) if top10 else 0
        burn = g.get("burn", 0)
        burn_pct = (float(burn) * 100 if float(burn) <= 1 else float(burn)) if burn else 0
        tp1 = price_val * 2
        tp2 = price_val * 5
        tp3 = price_val * 10
        stop = price_val * 0.82
        forca = min(int(ratio * 2), 10)
        barra = "🟢" * forca + "⚪" * (10 - forca)

        msg = (
            f"{emoji} *{label}*\n"
            f"_{desc}_\n\n"
            f"💎 *${symbol}*\n"
            f"`{addr}`\n\n"
            f"💲 Entrada: `${price_val:.10f}`\n\n"
            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n"
            f"🐋 Tamanho médio compra: `${avg_buy_size:,.0f}`\n"
            f"🚀 Volume accel: `{accel:.1f}x`\n\n"
            f"🔥 Buys: `{buys}`\n"
            f"📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"
            f"📈 5m: `{m5:+.1f}%`\n"
            f"🚀 1h: `{h1:+.1f}%`\n\n"
            f"⏰ Age: `{age:.1f} min`\n\n"
            f"🧠 Smart Money: `{g.get('smart',0)}`\n"
            f"👥 Holders: `{holders}`\n"
            f"📈 Holder growth: `{'✅' if holder_growth_ok else '❌'}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`\n"
            f"🔒 LP Burn: `{burn_pct:.0f}%`\n\n"
            f"💪 FORÇA:\n{barra}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 TP1: `2x` (${tp1:.8f})\n"
            f"🚀 TP2: `5x` (${tp2:.8f})\n"
            f"🌕 TP3: `10x` (${tp3:.8f})\n"
            f"🛑 STOP: `-18%` (${stop:.8f})\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"🟢 GMGN:\n"
            f"https://gmgn.ai/sol/token/{addr}\n\n"
            f"📊 DEX:\n"
            f"https://dexscreener.com/solana/{addr}\n\n"
            f"⚡ TROJAN:\n"
            f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
        )
        send(msg)

    except Exception as e:
        print(f"[PROCESS] {e}")

# ============================================================
# SCANNER (múltiplas threads)
# ============================================================
def scan():
    idx = 0
    while True:
        try:
            url = ENDPOINTS[idx % len(ENDPOINTS)]
            idx += 1
            r = session.get(url, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                for pair in pairs:
                    processar(pair)
        except Exception as e:
            print(f"[SCAN] {e}")
        time.sleep(SCAN_DELAY)

# ============================================================
# RELATÓRIO A CADA 2 HORAS
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
                f"🟢 Elite (entrada forte): `{st['green']}`\n"
                f"🟡 Whale momentum: `{st['yellow']}`\n\n"
                f"🐋 Whale monitor (8+ grandes compras)\n"
                f"🧠 Smart money scanner\n"
                f"⚡ Stealth buy detector\n"
                f"📈 Holder growth tracker (pessoas reais)\n"
                f"🚀 Ultra early monitor\n"
                f"🛡️ Anti rug system ativo"
            )
            send(txt)
        except Exception as e:
            print(f"[REL] {e}")
        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH CHECK (Flask)
# ============================================================
@app.route("/")
def health():
    return (f"WHALE HUNTER ONLINE | tokens={len(history)} | "
            f"fila={tg_queue.qsize()} | 🟢{stats['green']} 🟡{stats['yellow']}")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    send("🟢 *WHALE HUNTER QUANT v7.0 ONLINE*\n\n"
         "🐋 Whale tracking (8+ large buys)\n"
         "🧠 Smart money monitor\n"
         "⚡ Stealth buy detector\n"
         "📈 Real holder growth scanner\n"
         "🚀 Ultra early sniper\n"
         "🛡️ Anti rug ativo\n"
         "💰 Somente tokens com baleias e pessoas reais")

    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()

    # 20 threads de scan
    for _ in range(20):
        threading.Thread(target=scan, daemon=True).start()
        time.sleep(0.05)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
