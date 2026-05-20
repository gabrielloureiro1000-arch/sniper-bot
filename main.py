import os
import time
import threading
import requests
import telebot

from flask import Flask
from queue import Queue, Empty
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# AJUSTES PROFISSIONAIS
# ============================================================

# MAIS TOKENS SEM VIRAR LIXO
MIN_LIQ        = 15000
MAX_LIQ        = 350000

MIN_BUYS       = 18
MAX_BUYS       = 800

MIN_RATIO      = 1.4

MIN_VOL5M      = 4000

MIN_M5         = 2
MAX_M5         = 45

MIN_H1         = 5
MAX_H1         = 250

MIN_AGE        = 2
MAX_AGE        = 45

MAX_MC         = 4000000

# ============================================================
# VELOCIDADE
# ============================================================

SCAN_WORKERS   = 10
FETCH_TIMEOUT  = 6
REPORT_TIME    = 7200  # 2 HORAS

# ============================================================
# DEX ENDPOINTS
# ============================================================

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=solana+moon",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
]

# ============================================================
# GLOBAL
# ============================================================

seen_tokens = set()
monitored   = {}

lock        = threading.Lock()

alert_queue = Queue(maxsize=1000)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

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

        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            timeout=6,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        if r.status_code != 200:
            return {}

        d = r.json().get("data", {})

        return {
            "holders": d.get("holder_count", 0),
            "smart": d.get("smart_degen_count", 0),
            "top10": d.get("top10_holder_rate", 1),
            "lp": d.get("burn_ratio", 0),
            "honeypot": d.get("is_honeypot", False),
            "mintable": d.get("is_mintable", False),
        }

    except:
        return {}

# ============================================================
# SCORE
# ============================================================

def calculate_score(data, gmgn):

    score = 50

    # ========================================================
    # SMART MONEY
    # ========================================================

    smart = gmgn.get("smart", 0)

    if smart >= 8:
        score += 30

    elif smart >= 5:
        score += 20

    elif smart >= 2:
        score += 10

    # ========================================================
    # BUY PRESSURE
    # ========================================================

    ratio = data["ratio"]

    if ratio >= 4:
        score += 20

    elif ratio >= 2:
        score += 10

    # ========================================================
    # VOLUME ACCELERATION
    # ========================================================

    accel = data["vol5m"] / max(data["vol1h"] / 12, 1)

    if accel >= 6:
        score += 20

    elif accel >= 3:
        score += 10

    # ========================================================
    # AGE
    # ========================================================

    if data["age"] <= 10:
        score += 15

    elif data["age"] <= 20:
        score += 10

    # ========================================================
    # HOLDERS
    # ========================================================

    holders = gmgn.get("holders", 0)

    if holders >= 200:
        score += 10

    elif holders >= 80:
        score += 5

    # ========================================================
    # MC
    # ========================================================

    mc = data["mc"]

    if mc <= 150000:
        score += 15

    elif mc <= 500000:
        score += 10

    # ========================================================
    # RISK
    # ========================================================

    if gmgn.get("honeypot"):
        score -= 100

    if gmgn.get("mintable"):
        score -= 50

    top10 = gmgn.get("top10", 1)

    if top10 > 0.50:
        score -= 15

    lp = gmgn.get("lp", 0)

    if lp < 0.20:
        score -= 30

    # ========================================================
    # LIMITS
    # ========================================================

    score = max(0, min(100, score))

    # ========================================================
    # LABEL
    # ========================================================

    if score >= 80:

        signal = "🟢 VERDE"

    elif score >= 60:

        signal = "🟡 AMARELO"

    else:

        signal = "🔴 VERMELHO"

    return score, signal

# ============================================================
# FILTERS
# ============================================================

def passes(pair):

    if pair.get("chainId") != "solana":
        return False, None

    base = pair.get("baseToken", {})

    addr = base.get("address")

    if not addr:
        return False, None

    with lock:

        if addr in seen_tokens:
            return False, None

    liq = pair.get("liquidity", {}).get("usd", 0) or 0

    tx  = pair.get("txns", {}).get("m5", {})

    buys  = tx.get("buys", 0)
    sells = tx.get("sells", 1)

    ratio = buys / max(sells, 1)

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

    if liq < MIN_LIQ or liq > MAX_LIQ:
        return False, None

    if buys < MIN_BUYS or buys > MAX_BUYS:
        return False, None

    if ratio < MIN_RATIO:
        return False, None

    if vol5m < MIN_VOL5M:
        return False, None

    if m5 < MIN_M5 or m5 > MAX_M5:
        return False, None

    if h1 < MIN_H1 or h1 > MAX_H1:
        return False, None

    if age < MIN_AGE or age > MAX_AGE:
        return False, None

    if mc > MAX_MC:
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
        "price": float(pair.get("priceUsd", 0)),
    }

# ============================================================
# FETCH
# ============================================================

def fetch_pairs(url):

    try:

        r = requests.get(url, timeout=FETCH_TIMEOUT)

        if r.status_code == 200:

            return r.json().get("pairs", [])

    except:
        pass

    return []

# ============================================================
# ENTRY ALERT
# ============================================================

def process_token(data):

    addr = data["addr"]

    gmgn = fetch_gmgn(addr)

    score, signal = calculate_score(data, gmgn)

    if score < 60:
        return

    monitored[addr] = {
        "symbol": data["symbol"],
        "entry": data["price"],
        "time": time.time(),
    }

    accel = data["vol5m"] / max(data["vol1h"] / 12, 1)

    msg = (

        f"{signal} *ENTRADA PROFISSIONAL*\n\n"

        f"💎 *${data['symbol']}*\n"
        f"`{addr}`\n\n"

        f"💲 Preço: `${data['price']:.10f}`\n"
        f"💧 Liquidez: `${data['liq']:,.0f}`\n"
        f"📊 Volume 5m: `${data['vol5m']:,.0f}`\n"
        f"🔥 Compras: `{data['buys']}`\n"
        f"📉 Vendas: `{data['sells']}`\n"
        f"⚖️ Ratio: `{data['ratio']:.1f}x`\n"
        f"🚀 Aceleração: `{accel:.1f}x`\n"
        f"📈 5m: `{data['m5']:+.1f}%`\n"
        f"📈 1h: `{data['h1']:+.1f}%`\n"
        f"⏰ Idade: `{data['age']:.0f} min`\n"
        f"📦 MC: `${data['mc']:,.0f}`\n"
        f"🧠 Smart Wallets: `{gmgn.get('smart', 0)}`\n"
        f"👥 Holders: `{gmgn.get('holders', '?')}`\n\n"

        f"🎯 SCORE: `{score}/100`\n\n"

        f"🟢 VERDE = forte probabilidade\n"
        f"🟡 AMARELO = entrada moderada\n"
        f"🔴 VERMELHO = risco elevado\n\n"

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

            ok, data = passes(pair)

            if not ok:
                continue

            with lock:

                if data["addr"] in seen_tokens:
                    continue

                seen_tokens.add(data["addr"])

            threading.Thread(
                target=process_token,
                args=(data,),
                daemon=True
            ).start()

        time.sleep(0.5)

# ============================================================
# EXIT MONITOR
# ============================================================

def exit_monitor():

    time.sleep(180)

    while True:

        try:

            for addr, info in list(monitored.items()):

                try:

                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{addr}",
                        timeout=8
                    )

                    pairs = r.json().get("pairs", [])

                    if not pairs:
                        continue

                    price = float(pairs[0].get("priceUsd", 0))

                    entry = info["entry"]

                    if entry <= 0:
                        continue

                    pnl = ((price - entry) / entry) * 100

                    # ====================================================
                    # TAKE PROFIT
                    # ====================================================

                    if pnl >= 70:

                        send(
                            f"🤑 *TAKE PROFIT*\n\n"
                            f"💎 *${info['symbol']}*\n"
                            f"📈 Lucro: `+{pnl:.1f}%`\n\n"
                            f"🔗 https://gmgn.ai/sol/token/{addr}"
                        )

                        del monitored[addr]

                    # ====================================================
                    # STOP LOSS
                    # ====================================================

                    elif pnl <= -18:

                        send(
                            f"🚨 *STOP LOSS*\n\n"
                            f"💎 *${info['symbol']}*\n"
                            f"📉 Resultado: `{pnl:.1f}%`\n\n"
                            f"🔗 https://gmgn.ai/sol/token/{addr}"
                        )

                        del monitored[addr]

                except:
                    pass

        except Exception as e:

            print(f"[EXIT] {e}")

        time.sleep(120)

# ============================================================
# REPORT 2H
# ============================================================

def report_worker():

    while True:

        time.sleep(REPORT_TIME)

        try:

            send(
                f"📊 *RELATÓRIO 2H*\n\n"
                f"🤖 Scanner online\n"
                f"📡 Tokens monitorados: `{len(monitored)}`\n"
                f"⚡ Workers: `{SCAN_WORKERS}`\n"
                f"🕒 {datetime.utcnow().strftime('%H:%M UTC')}"
            )

        except:
            pass

# ============================================================
# HEALTH
# ============================================================

@app.route("/")

def home():

    return (
        f"WHALE QUANT PRO X | "
        f"Tokens: {len(monitored)}"
    )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("WHALE QUANT PRO X ONLINE")

    send(
        "🟢 *WHALE QUANT PRO X ONLINE*\n\n"
        "🏦 Sistema Quantitativo Institucional\n"
        "🐋 Detecção de fluxo de baleias\n"
        "📈 Momentum + aceleração de volume\n"
        "🛡️ Gestão automática de risco\n"
        "⚡ Entrada ultra early\n"
        "📊 Relatórios a cada 2 horas"
    )

    threading.Thread(
        target=telegram_sender,
        daemon=True
    ).start()

    threading.Thread(
        target=exit_monitor,
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

        time.sleep(0.1)

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 10000))
    )
