import os
import time
import threading
import requests
import telebot

from flask import Flask
from queue import Queue, Empty
from datetime import datetime

# ============================================================
# WHALE FLOW QUANT X
# VERSION 2026 — INSTITUTIONAL MEMECOIN ENGINE
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# AJUSTES PROFISSIONAIS
# ============================================================

# ENTRAR ANTES DO VAREJO
MIN_MC            = 7000
MAX_MC            = 180000

# LIQUIDEZ IDEAL
MIN_LIQ           = 8000
MAX_LIQ           = 60000

# BALEIAS
MIN_BUYS          = 18
MAX_BUYS          = 450

# PRESSÃO COMPRADORA
MIN_RATIO         = 1.8

# VOLUME
MIN_VOL5M         = 2500

# TOKEN NOVO
MIN_AGE           = 1
MAX_AGE           = 25

# MOVIMENTO
MIN_M5            = 1
MAX_M5            = 35

MIN_H1            = 2
MAX_H1            = 120

# SMART MONEY
MIN_SMART_MONEY   = 2

# HOLDERS
MIN_HOLDERS       = 45

# TOP HOLDERS
MAX_TOP10         = 0.35

# DEV
MAX_DEV_HOLD      = 0.08

# RELATORIO
REPORT_INTERVAL   = 7200

# WORKERS
SCAN_WORKERS      = 14

# ============================================================
# ENDPOINTS
# ============================================================

ENDPOINTS = [

    "https://api.dexscreener.com/latest/dex/search?q=solana",

    "https://api.dexscreener.com/latest/dex/search?q=sol+new",

    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",

    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",

    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",

    "https://api.dexscreener.com/latest/dex/search?q=raydium",

    "https://api.dexscreener.com/latest/dex/search?q=moonshot",

]

# ============================================================
# GLOBAL
# ============================================================

seen_tokens = set()

monitored_tokens = {}

lock = threading.Lock()

alert_queue = Queue(maxsize=2000)

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    threaded=False
)

app = Flask(__name__)

# ============================================================
# TELEGRAM
# ============================================================

def telegram_sender():

    while True:

        try:

            msg = alert_queue.get(timeout=5)

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
        alert_queue.put_nowait(msg)
    except:
        pass

# ============================================================
# GMGN
# ============================================================

def fetch_gmgn(addr):

    try:

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gmgn.ai/"
        }

        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            timeout=6,
            headers=headers
        )

        if r.status_code != 200:
            return {}

        d = r.json().get("data", {}) or {}

        return {

            "holders": d.get("holder_count", 0),

            "smart": d.get("smart_degen_count", 0),

            "top10": d.get("top10_holder_rate", 1),

            "lp": d.get("burn_ratio", 0),

            "honeypot": d.get("is_honeypot", False),

            "mintable": d.get("is_mintable", False),

            "dev": d.get("dev_token_burn_ratio", 0),

        }

    except:
        return {}

# ============================================================
# SCORE ENGINE
# ============================================================

def calculate_score(data, g):

    score = 0

    reasons = []

    # ========================================================
    # SMART MONEY
    # ========================================================

    smart = g.get("smart", 0)

    if smart >= 10:

        score += 35
        reasons.append("🐋 whales fortes")

    elif smart >= 6:

        score += 25
        reasons.append("🐋 smart money entrando")

    elif smart >= 2:

        score += 15
        reasons.append("🐋 fluxo institucional")

    # ========================================================
    # HOLDERS
    # ========================================================

    holders = g.get("holders", 0)

    if holders >= 250:

        score += 20
        reasons.append("👥 holders explodindo")

    elif holders >= 120:

        score += 12
        reasons.append("👥 holders crescendo")

    elif holders >= 60:

        score += 6

    # ========================================================
    # BUY PRESSURE
    # ========================================================

    ratio = data["ratio"]

    if ratio >= 5:

        score += 25
        reasons.append("📈 compra agressiva")

    elif ratio >= 3:

        score += 18

    elif ratio >= 2:

        score += 10

    # ========================================================
    # VOLUME ACCELERATION
    # ========================================================

    accel = data["vol5m"] / max(data["vol1h"] / 12, 1)

    if accel >= 10:

        score += 30
        reasons.append("🚀 volume parabólico")

    elif accel >= 6:

        score += 20
        reasons.append("🚀 volume acelerando")

    elif accel >= 3:

        score += 10

    # ========================================================
    # EARLY
    # ========================================================

    if data["age"] <= 5:

        score += 20
        reasons.append("⚡ ultra early")

    elif data["age"] <= 12:

        score += 12

    # ========================================================
    # MARKET CAP
    # ========================================================

    mc = data["mc"]

    if mc <= 15000:

        score += 30
        reasons.append("💎 microcap")

    elif mc <= 40000:

        score += 20

    elif mc <= 90000:

        score += 10

    # ========================================================
    # RISK
    # ========================================================

    if g.get("honeypot"):

        score -= 200

    if g.get("mintable"):

        score -= 100

    if g.get("top10", 1) > MAX_TOP10:

        score -= 35

    if g.get("dev", 0) > MAX_DEV_HOLD:

        score -= 30

    if g.get("lp", 0) < 0.20:

        score -= 50

    # ========================================================
    # LABEL
    # ========================================================

    if score >= 80:

        signal = "🟢 VERDE"

    elif score >= 55:

        signal = "🟡 AMARELO"

    else:

        signal = "🔴 VERMELHO"

    return score, signal, reasons

# ============================================================
# FILTER ENGINE
# ============================================================

def passes_filters(pair):

    if pair.get("chainId") != "solana":
        return False, None

    base = pair.get("baseToken", {})

    addr = base.get("address")

    if not addr:
        return False, None

    with lock:

        if addr in seen_tokens:
            return False, None

    tx = pair.get("txns", {}).get("m5", {})

    buys  = tx.get("buys", 0)
    sells = tx.get("sells", 1)

    ratio = buys / max(sells, 1)

    liq = pair.get("liquidity", {}).get("usd", 0) or 0

    vol5m = pair.get("volume", {}).get("m5", 0) or 0
    vol1h = pair.get("volume", {}).get("h1", 0) or 0

    pc = pair.get("priceChange", {})

    m5 = pc.get("m5", 0) or 0
    h1 = pc.get("h1", 0) or 0

    created = pair.get("pairCreatedAt")

    age = (
        (time.time() * 1000 - created) / 60000
        if created else 999
    )

    mc = pair.get("fdv") or pair.get("marketCap") or 0

    if mc < MIN_MC or mc > MAX_MC:
        return False, None

    if liq < MIN_LIQ or liq > MAX_LIQ:
        return False, None

    if buys < MIN_BUYS or buys > MAX_BUYS:
        return False, None

    if ratio < MIN_RATIO:
        return False, None

    if vol5m < MIN_VOL5M:
        return False, None

    if age < MIN_AGE or age > MAX_AGE:
        return False, None

    if m5 < MIN_M5 or m5 > MAX_M5:
        return False, None

    if h1 < MIN_H1 or h1 > MAX_H1:
        return False, None

    return True, {

        "addr": addr,

        "symbol": base.get("symbol", "???"),

        "liq": liq,

        "buys": buys,

        "sells": sells,

        "ratio": ratio,

        "vol5m": vol5m,

        "vol1h": vol1h,

        "m5": m5,

        "h1": h1,

        "age": age,

        "mc": mc,

        "price": float(pair.get("priceUsd", 0))

    }

# ============================================================
# FETCH
# ============================================================

def fetch_pairs(url):

    try:

        r = requests.get(url, timeout=6)

        if r.status_code == 200:

            return r.json().get("pairs", [])

    except:
        pass

    return []

# ============================================================
# TOKEN ANALYSIS
# ============================================================

def analyze_token(data):

    addr = data["addr"]

    g = fetch_gmgn(addr)

    # ========================================================
    # GMGN FILTERS
    # ========================================================

    if g:

        if g.get("smart", 0) < MIN_SMART_MONEY:
            return

        if g.get("holders", 0) < MIN_HOLDERS:
            return

        if g.get("top10", 1) > MAX_TOP10:
            return

        if g.get("dev", 0) > MAX_DEV_HOLD:
            return

    score, signal, reasons = calculate_score(data, g)

    if score < 55:
        return

    monitored_tokens[addr] = {

        "symbol": data["symbol"],

        "entry": data["price"],

        "time": time.time()

    }

    accel = data["vol5m"] / max(data["vol1h"] / 12, 1)

    msg = (

        f"{signal} *WHALE ENTRY DETECTADA*\n\n"

        f"💎 *${data['symbol']}*\n"

        f"`{addr}`\n\n"

        f"💲 Preço: `${data['price']:.10f}`\n"

        f"📦 MC: `${data['mc']:,.0f}`\n"

        f"💧 Liquidez: `${data['liq']:,.0f}`\n"

        f"📊 Volume 5m: `${data['vol5m']:,.0f}`\n"

        f"🔥 Compras: `{data['buys']}`\n"

        f"📉 Vendas: `{data['sells']}`\n"

        f"⚖️ Ratio: `{data['ratio']:.1f}x`\n"

        f"🚀 Aceleração: `{accel:.1f}x`\n"

        f"📈 5m: `{data['m5']:+.1f}%`\n"

        f"📈 1h: `{data['h1']:+.1f}%`\n"

        f"⏰ Idade: `{data['age']:.0f} min`\n"

        f"🐋 Smart Wallets: `{g.get('smart', 0)}`\n"

        f"👥 Holders: `{g.get('holders', '?')}`\n"

        f"🏦 Top 10: `{g.get('top10', 0)*100:.0f}%`\n\n"

        f"🎯 SCORE: `{score}/100`\n\n"

        f"🧠 Sinais:\n"

        + "\n".join([f"• {x}" for x in reasons[:5]])

        + "\n\n"

        f"🔗 GMGN:\n"

        f"https://gmgn.ai/sol/token/{addr}"

    )

    send(msg)

# ============================================================
# WORKERS
# ============================================================

def scan_worker(worker_id):

    endpoint = worker_id

    while True:

        url = ENDPOINTS[endpoint % len(ENDPOINTS)]

        endpoint += 1

        pairs = fetch_pairs(url)

        for pair in pairs:

            ok, data = passes_filters(pair)

            if not ok:
                continue

            with lock:

                if data["addr"] in seen_tokens:
                    continue

                seen_tokens.add(data["addr"])

            threading.Thread(
                target=analyze_token,
                args=(data,),
                daemon=True
            ).start()

        time.sleep(0.3)

# ============================================================
# EXIT ENGINE
# ============================================================

def monitor_exit():

    time.sleep(180)

    while True:

        try:

            for addr, info in list(monitored_tokens.items()):

                try:

                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{addr}",
                        timeout=6
                    )

                    pairs = r.json().get("pairs", [])

                    if not pairs:
                        continue

                    p = float(pairs[0].get("priceUsd", 0))

                    pnl = (
                        (p - info["entry"])
                        / info["entry"]
                    ) * 100

                    # TAKE PROFIT

                    if pnl >= 80:

                        send(

                            f"🤑 *TAKE PROFIT*\n\n"

                            f"💎 *${info['symbol']}*\n"

                            f"📈 Resultado: `+{pnl:.1f}%`\n\n"

                            f"🔗 https://gmgn.ai/sol/token/{addr}"

                        )

                        del monitored_tokens[addr]

                    # STOP LOSS

                    elif pnl <= -18:

                        send(

                            f"🚨 *STOP LOSS*\n\n"

                            f"💎 *${info['symbol']}*\n"

                            f"📉 Resultado: `{pnl:.1f}%`\n\n"

                            f"🔗 https://gmgn.ai/sol/token/{addr}"

                        )

                        del monitored_tokens[addr]

                except:
                    pass

        except:
            pass

        time.sleep(120)

# ============================================================
# REPORT
# ============================================================

def report_worker():

    while True:

        time.sleep(REPORT_INTERVAL)

        send(

            f"📊 *RELATÓRIO 2H*\n\n"

            f"🤖 Scanner online\n"

            f"📡 Tokens monitorados: `{len(monitored_tokens)}`\n"

            f"⚡ Workers: `{SCAN_WORKERS}`\n"

            f"🕒 {datetime.utcnow().strftime('%H:%M UTC')}"

        )

# ============================================================
# HEALTH
# ============================================================

@app.route("/")

def health():

    return (
        f"WHALE FLOW QUANT X | "
        f"Tokens: {len(monitored_tokens)}"
    )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("WHALE FLOW QUANT X ONLINE")

    send(

        "🟢 *WHALE FLOW QUANT X ONLINE*\n\n"

        "🏦 Quantitative Memecoin Engine\n"

        "🐋 Whale flow detection\n"

        "📈 Volume acceleration engine\n"

        "⚡ Ultra early scanner\n"

        "🛡️ Institutional filters enabled\n"

        "📊 Reports every 2h"

    )

    threading.Thread(
        target=telegram_sender,
        daemon=True
    ).start()

    threading.Thread(
        target=monitor_exit,
        daemon=True
    ).start()

    threading.Thread(
        target=report_worker,
        daemon=True
    ).start()

    for i in range(SCAN_WORKERS):

        threading.Thread(
            target=scan_worker,
            args=(i,),
            daemon=True
        ).start()

        time.sleep(0.05)

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )
