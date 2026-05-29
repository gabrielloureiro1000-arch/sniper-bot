# ============================================================
# WHALE HUNTER QUANT v6.0
# FOCO:
# - PEGAR STEALTH BUY
# - PEGAR HOLDER GROWTH
# - PEGAR SMART MONEY
# - EVITAR LIXO/RUG
# - ALERTAR SOMENTE TOKENS PROMISSORES
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
# SESSION
# ============================================================

session = requests.Session()

retries = Retry(
    total=3,
    backoff_factor=0.4,
    status_forcelist=[429, 500, 502, 503, 504]
)

adapter = HTTPAdapter(
    pool_connections=200,
    pool_maxsize=200,
    max_retries=retries
)

session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ============================================================
# CONFIG
# ============================================================

SCAN_DELAY = 0.15

REPORT_INTERVAL = 7200

# ============================================================
# FILTROS ULTRA EARLY
# ============================================================

MIN_LIQ = 5000
MAX_LIQ = 80000

MIN_BUYS = 5
MAX_BUYS = 300

MIN_RATIO = 1.8

MIN_VOL5M = 800

MIN_AGE = 0.3
MAX_AGE = 18

MIN_M5 = 2
MAX_M5 = 80

MAX_TOP10 = 35

MIN_SMART = 1

# ============================================================
# ENDPOINTS
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
# ESTADO
# ============================================================

lock = threading.Lock()

history = {}

stats = {
    "sent": 0,
    "green": 0,
    "yellow": 0,
    "red": 0
}

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

                    bot.send_message(
                        CHAT_ID,
                        msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )

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
# GMGN
# ============================================================

def get_gmgn(addr):

    try:

        r = session.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gmgn.ai/"
            },
            timeout=5
        )

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

    try:

        if g.get("honeypot") is True:
            return True, "HONEYPOT"

        if g.get("tax", 0) > 20:
            return True, "SELL TAX"

        if g.get("rug", 0) > 0.7:
            return True, "RUG"

        dev = g.get("dev", 0)

        if dev:

            if float(dev) > 12:
                return True, "DEV HOLD"

        top10 = g.get("top10", 0)

        if top10:

            t = (
                float(top10) * 100
                if float(top10) <= 1
                else float(top10)
            )

            if t > MAX_TOP10:
                return True, "TOP10"

    except:
        pass

    return False, ""

# ============================================================
# SCORE
# ============================================================

def score_token(data, g):

    pontos = 0

    ratio = data["ratio"]
    buys  = data["buys"]
    age   = data["age"]
    m5    = data["m5"]
    h1    = data["h1"]
    accel = data["accel"]

    # ========================================================
    # WHALES
    # ========================================================

    if buys >= 30:
        pontos += 5

    elif buys >= 15:
        pontos += 4

    elif buys >= 8:
        pontos += 3

    # ========================================================
    # BUY/SELL
    # ========================================================

    if ratio >= 5:
        pontos += 5

    elif ratio >= 3:
        pontos += 4

    elif ratio >= 2:
        pontos += 3

    # ========================================================
    # EARLY
    # ========================================================

    if age <= 3:
        pontos += 5

    elif age <= 8:
        pontos += 4

    elif age <= 15:
        pontos += 2

    # ========================================================
    # MOMENTUM
    # ========================================================

    if m5 >= 15:
        pontos += 4

    elif m5 >= 5:
        pontos += 2

    # ========================================================
    # ACCEL
    # ========================================================

    if accel >= 3:
        pontos += 5

    elif accel >= 2:
        pontos += 3

    # ========================================================
    # SMART MONEY
    # ========================================================

    smart = g.get("smart", 0)

    if smart >= 5:
        pontos += 8

    elif smart >= 3:
        pontos += 5

    elif smart >= 1:
        pontos += 2

    # ========================================================
    # HOLDERS
    # ========================================================

    holders = g.get("holders", 0)

    if holders >= 300:
        pontos += 4

    elif holders >= 120:
        pontos += 3

    elif holders >= 50:
        pontos += 1

    # ========================================================
    # LP BURN
    # ========================================================

    burn = g.get("burn", 0)

    if burn:

        b = (
            float(burn) * 100
            if float(burn) <= 1
            else float(burn)
        )

        if b >= 80:
            pontos += 3

    # ========================================================
    # TOP10
    # ========================================================

    top10 = g.get("top10", 0)

    if top10:

        t = (
            float(top10) * 100
            if float(top10) <= 1
            else float(top10)
        )

        if t <= 20:
            pontos += 4

        elif t <= 30:
            pontos += 2

    # ========================================================
    # RESULTADO
    # ========================================================

    if pontos >= 28:
        return "🟢", "ELITE WHALE ENTRY", "Smart money forte entrando"

    elif pontos >= 20:
        return "🟡", "WHALE MOMENTUM", "Pump saudável"

    else:
        return "🔴", "RISCO", "Momentum fraco"

# ============================================================
# PROCESSAMENTO
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

        if buys < MIN_BUYS:
            return

        if buys > MAX_BUYS:
            return

        ratio = buys / max(sells, 1)

        if ratio < MIN_RATIO:
            return

        pc = pair.get("priceChange", {})

        m5 = pc.get("m5", 0) or 0
        h1 = pc.get("h1", 0) or 0

        if m5 < MIN_M5:
            return

        if m5 > MAX_M5:
            return

        created = pair.get("pairCreatedAt")

        age = (
            (time.time() * 1000 - created) / 60000
            if created else 999
        )

        if age < MIN_AGE or age > MAX_AGE:
            return

        # ====================================================
        # VOLUME ACCEL
        # ====================================================

        accel = 0

        if vol1h > 0:

            accel = (
                vol5m /
                max(vol1h / 12, 1)
            )

        # ====================================================
        # STEALTH BUY
        # ====================================================

        stealth = (

            buys >= 8 and
            ratio >= 2.5 and
            accel >= 1.8 and
            age <= 10
        )

        if not stealth:
            return

        # ====================================================
        # ANTI BOT
        # ====================================================

        if sells > 0:

            sell_ratio = sells / max(buys, 1)

            if sell_ratio < 0.04:
                return

            if sell_ratio > 0.8:
                return

        # ====================================================
        # DUPLICADO
        # ====================================================

        with lock:

            old = history.get(addr)

            if old:

                if time.time() - old["ts"] < 3600:
                    return

        # ====================================================
        # GMGN
        # ====================================================

        g = get_gmgn(addr)

        lixo, motivo = is_lixo(g)

        if lixo:
            return

        # ====================================================
        # SMART MONEY OBRIGATÓRIO
        # ====================================================

        smart = g.get("smart", 0)

        if smart < MIN_SMART:
            return

        # ====================================================
        # SCORE
        # ====================================================

        emoji, label, desc = score_token({

            "ratio": ratio,
            "buys": buys,
            "age": age,
            "m5": m5,
            "h1": h1,
            "accel": accel

        }, g)

        # ====================================================
        # SOMENTE VERDE/AMARELO
        # ====================================================

        if "RISCO" in label:
            return

        symbol = base.get("symbol", "???")

        price = float(price)

        # ====================================================
        # SAVE
        # ====================================================

        with lock:

            history[addr] = {

                "symbol": symbol,
                "price": price,
                "ts": time.time()
            }

            stats["sent"] += 1

            if "ELITE" in label:
                stats["green"] += 1

            else:
                stats["yellow"] += 1

        # ====================================================
        # INFO
        # ====================================================

        holders = g.get("holders", 0)

        top10 = g.get("top10", 0)

        top10_pct = (
            float(top10) * 100
            if float(top10) <= 1
            else float(top10)
        ) if top10 else 0

        burn = g.get("burn", 0)

        burn_pct = (
            float(burn) * 100
            if float(burn) <= 1
            else float(burn)
        ) if burn else 0

        # ====================================================
        # TP
        # ====================================================

        tp1 = price * 2
        tp2 = price * 5
        tp3 = price * 10

        stop = price * 0.82

        # ====================================================
        # BARRA
        # ====================================================

        forca = min(int(ratio * 2), 10)

        barra = "🟢" * forca + "⚪" * (10 - forca)

        # ====================================================
        # ALERTA
        # ====================================================

        msg = (

            f"{emoji} *{label}*\n"
            f"_{desc}_\n\n"

            f"💎 *${symbol}*\n"
            f"`{addr}`\n\n"

            f"💲 Entrada: `${price:.10f}`\n\n"

            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n"
            f"🚀 Volume accel: `{accel:.1f}x`\n\n"

            f"🔥 Buys: `{buys}`\n"
            f"📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"

            f"📈 5m: `{m5:+.1f}%`\n"
            f"🚀 1h: `{h1:+.1f}%`\n\n"

            f"⏰ Age: `{age:.1f} min`\n\n"

            f"🧠 Smart Money: `{smart}`\n"
            f"👥 Holders: `{holders}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`\n"
            f"🔒 LP Burn: `{burn_pct:.0f}%`\n\n"

            f"💪 FORÇA:\n{barra}\n\n"

            f"━━━━━━━━━━━━━━━\n"
            f"🎯 TP1: `2x`\n"
            f"🚀 TP2: `5x`\n"
            f"🌕 TP3: `10x`\n"
            f"🛑 STOP: `-18%`\n"
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
# SCANNER
# ============================================================

def scan():

    idx = 0

    while True:

        try:

            url = ENDPOINTS[idx % len(ENDPOINTS)]

            idx += 1

            r = session.get(
                url,
                headers=HEADERS,
                timeout=6
            )

            if r.status_code == 200:

                pairs = r.json().get("pairs") or []

                for pair in pairs:

                    processar(pair)

        except Exception as e:

            print(f"[SCAN] {e}")

        time.sleep(SCAN_DELAY)

# ============================================================
# RELATORIO
# ============================================================

def relatorio():

    time.sleep(REPORT_INTERVAL)

    while True:

        try:

            with lock:

                st = dict(stats)

            txt = (

                f"📊 *RELATÓRIO 2H*\n\n"

                f"📤 Alertas: `{st['sent']}`\n"
                f"🟢 Elite: `{st['green']}`\n"
                f"🟡 Whale: `{st['yellow']}`\n\n"

                f"🐋 Whale monitor ativo\n"
                f"🧠 Smart money scanner\n"
                f"⚡ Stealth buy detector\n"
                f"📈 Holder growth tracker\n"
                f"🚀 Ultra early monitor\n"
                f"🛡️ Anti rug system"
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

    return (
        f"WHALE HUNTER ONLINE | "
        f"tokens={len(history)} | "
        f"fila={tg_queue.qsize()} | "
        f"🟢{stats['green']} "
        f"🟡{stats['yellow']}"
    )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    send(

        "🟢 *WHALE HUNTER QUANT ONLINE*\n\n"

        "🐋 Whale tracking ativo\n"
        "🧠 Smart money monitor\n"
        "⚡ Stealth buy detector\n"
        "📈 Holder growth scanner\n"
        "🚀 Ultra early sniper\n"
        "🛡️ Anti rug ativo\n"
        "💰 Somente tokens fortes"
    )

    threading.Thread(
        target=tg_worker,
        daemon=True
    ).start()

    threading.Thread(
        target=relatorio,
        daemon=True
    ).start()

    # ========================================================
    # 20 THREADS
    # ========================================================

    for _ in range(20):

        threading.Thread(
            target=scan,
            daemon=True
        ).start()

        time.sleep(0.05)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
