import os
import time
import threading
import requests
import telebot
from flask import Flask
from queue import Queue, Empty

# ============================================================
# TELEGRAM
# ============================================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# CONFIG
# ============================================================
SCAN_DELAY = 0.15
SCAN_WORKERS = 10

MIN_LIQ = 12000
MAX_LIQ = 350000

MIN_BUYS = 12
MAX_BUYS = 800

MIN_RATIO = 1.7
MIN_VOLUME = 2500

MIN_AGE = 1
MAX_AGE = 30

MAX_MC = 4000000

TAKE_PROFIT = 35
STOP_LOSS = -15
TRAILING_STOP = -18

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20new",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20pump",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20trending",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20meme",
]

# ============================================================
# GLOBAL
# ============================================================
seen = set()
positions = {}

scan_queue = Queue(maxsize=3000)
alert_queue = Queue(maxsize=3000)

lock = threading.Lock()

# ============================================================
# TELEGRAM SENDER
# ============================================================
def sender():
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
                except Exception:
                    time.sleep(1)
        except Empty:
            pass


def send(msg):
    try:
        alert_queue.put_nowait(msg)
    except:
        pass

# ============================================================
# GMGN
# ============================================================
def gmgn(addr):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0"
        }

        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers=headers,
            timeout=5
        )

        if r.status_code != 200:
            return {}

        d = r.json().get("data", {})

        return {
            "honeypot": d.get("is_honeypot", False),
            "holders": d.get("holder_count", 0),
            "top10": d.get("top10_holder_rate", 1),
            "smart": d.get("smart_degen_count", 0),
            "tax": d.get("sell_tax", 0),
            "burn": d.get("burn_ratio", 0),
        }

    except:
        return {}

# ============================================================
# SECURITY FILTER
# ============================================================
def safe(g):
    if not g:
        return True

    if g.get("honeypot"):
        return False

    if g.get("tax", 0) > 12:
        return False

    holders = g.get("holders", 0)
    if holders > 0 and holders < 25:
        return False

    top10 = g.get("top10", 0)
    if top10:
        top10_pct = top10 * 100 if top10 <= 1 else top10
        if top10_pct > 75:
            return False

    return True

# ============================================================
# FEATURE EXTRACTION
# ============================================================
def extract(pair):

    base = pair.get("baseToken", {})

    addr = base.get("address")
    symbol = base.get("symbol", "???")

    liq = pair.get("liquidity", {}).get("usd", 0) or 0

    vol5 = pair.get("volume", {}).get("m5", 0) or 0
    vol1 = pair.get("volume", {}).get("h1", 0) or 0

    tx = pair.get("txns", {}).get("m5", {})

    buys = tx.get("buys", 0)
    sells = tx.get("sells", 0)

    ratio = buys / max(sells, 1)

    created = pair.get("pairCreatedAt")

    age = ((time.time() * 1000 - created) / 60000) if created else 999

    mc = pair.get("fdv") or pair.get("marketCap") or 0

    price = pair.get("priceUsd")

    price_change = pair.get("priceChange", {})

    m5 = price_change.get("m5", 0) or 0
    h1 = price_change.get("h1", 0) or 0

    accel = 1

    if vol1 > 0:
        accel = vol5 / max(vol1 / 12, 1)

    whale = False

    if buys >= 25 and ratio >= 2.5 and vol5 >= 10000:
        whale = True

    return {
        "addr": addr,
        "symbol": symbol,
        "liq": liq,
        "vol5": vol5,
        "vol1": vol1,
        "buys": buys,
        "sells": sells,
        "ratio": ratio,
        "age": age,
        "mc": mc,
        "price": float(price) if price else 0,
        "m5": m5,
        "h1": h1,
        "accel": accel,
        "whale": whale
    }

# ============================================================
# VALIDATION
# ============================================================
def valid(pair):

    if pair.get("chainId") != "solana":
        return False, None

    d = extract(pair)

    if not d["addr"]:
        return False, None

    if d["addr"] in seen:
        return False, None

    if d["liq"] < MIN_LIQ:
        return False, None

    if d["liq"] > MAX_LIQ:
        return False, None

    if d["buys"] < MIN_BUYS:
        return False, None

    if d["buys"] > MAX_BUYS:
        return False, None

    if d["ratio"] < MIN_RATIO:
        return False, None

    if d["vol5"] < MIN_VOLUME:
        return False, None

    if d["age"] < MIN_AGE:
        return False, None

    if d["age"] > MAX_AGE:
        return False, None

    if d["mc"] > MAX_MC:
        return False, None

    if d["m5"] > 40:
        return False, None

    if d["h1"] > 250:
        return False, None

    return True, d

# ============================================================
# QUANT SCORE
# ============================================================
def score(d, g):

    score = 50
    reasons = []

    # ========================================================
    # LIQUIDITY
    # ========================================================
    if 15000 <= d["liq"] <= 60000:
        score -= 12
        reasons.append("liq ideal")

    elif d["liq"] > 120000:
        score += 8

    # ========================================================
    # BUY PRESSURE
    # ========================================================
    if d["ratio"] >= 4:
        score -= 15
        reasons.append("forte pressão compradora")

    elif d["ratio"] >= 2.5:
        score -= 8
        reasons.append("fluxo comprador")

    # ========================================================
    # ACCELERATION
    # ========================================================
    if d["accel"] >= 5:
        score -= 18
        reasons.append("volume explodindo")

    elif d["accel"] >= 3:
        score -= 10
        reasons.append("volume acelerando")

    # ========================================================
    # AGE
    # ========================================================
    if d["age"] <= 8:
        score -= 12
        reasons.append("ultra early")

    elif d["age"] >= 25:
        score += 10

    # ========================================================
    # MARKET CAP
    # ========================================================
    if d["mc"] <= 300000:
        score -= 12
        reasons.append("mc baixo")

    elif d["mc"] >= 2000000:
        score += 12

    # ========================================================
    # WHALE
    # ========================================================
    if d["whale"]:
        score -= 18
        reasons.append("🐋 whale flow")

    # ========================================================
    # SMART MONEY
    # ========================================================
    smart = g.get("smart", 0)

    if smart >= 5:
        score -= 15
        reasons.append("smart money forte")

    elif smart >= 2:
        score -= 8
        reasons.append("smart money")

    # ========================================================
    # HOLDERS
    # ========================================================
    holders = g.get("holders", 0)

    if holders >= 80:
        score -= 5

    score = max(0, min(100, score))

    if score <= 30:
        return "🟢", "ENTRADA ELITE", score, reasons

    elif score <= 55:
        return "🟡", "ENTRADA BOA", score, reasons

    else:
        return "🔴", "ARRISCADO", score, reasons

# ============================================================
# SCANNER
# ============================================================
def scanner(worker_id):

    index = worker_id

    while True:

        url = ENDPOINTS[index % len(ENDPOINTS)]
        index += 1

        try:
            r = requests.get(url, timeout=5)

            pairs = r.json().get("pairs", [])

            for pair in pairs:

                ok, d = valid(pair)

                if not ok:
                    continue

                with lock:
                    if d["addr"] in seen:
                        continue

                    seen.add(d["addr"])

                try:
                    scan_queue.put_nowait(d)
                except:
                    pass

        except:
            pass

        time.sleep(SCAN_DELAY)

# ============================================================
# WORKER
# ============================================================
def worker():

    while True:

        try:
            d = scan_queue.get(timeout=5)
        except Empty:
            continue

        try:

            g = gmgn(d["addr"])

            if not safe(g):
                continue

            emoji, label, sc, reasons = score(d, g)

            whale_text = "🐋 *WHALE FLOW DETECTADO*\n" if d["whale"] else ""

            smart = g.get("smart", 0)
            holders = g.get("holders", "?")

            msg = (
                f"{emoji} *{label}*\n\n"
                f"{whale_text}"
                f"💎 *${d['symbol']}*\n"
                f"`{d['addr']}`\n\n"
                f"💲 Preço: `${d['price']:.10f}`\n"
                f"💧 Liquidez: `${d['liq']:,.0f}`\n"
                f"📊 Volume 5m: `${d['vol5']:,.0f}`\n"
                f"🔥 Buys: `{d['buys']}`\n"
                f"📉 Sells: `{d['sells']}`\n"
                f"⚖️ Ratio: `{d['ratio']:.1f}x`\n"
                f"🚀 Aceleração: `{d['accel']:.1f}x`\n"
                f"📈 5m: `{d['m5']:+.1f}%`\n"
                f"📈 1h: `{d['h1']:+.1f}%`\n"
                f"⏰ Idade: `{d['age']:.0f} min`\n"
                f"📦 MC: `${d['mc']:,.0f}`\n"
                f"🧠 Smart wallets: `{smart}`\n"
                f"👥 Holders: `{holders}`\n\n"
                f"🎯 Score: `{sc}/100`\n"
                f"📈 {' | '.join(reasons[:4])}\n\n"
                f"🔗 https://dexscreener.com/solana/{d['addr']}"
            )

            send(msg)

            if emoji == "🟢":
                with lock:
                    positions[d["addr"]] = {
                        "symbol": d["symbol"],
                        "entry": d["price"],
                        "peak": d["price"]
                    }

        except:
            pass

# ============================================================
# POSITION MONITOR
# ============================================================
def monitor():

    while True:

        time.sleep(45)

        with lock:
            active = dict(positions)

        if not active:
            continue

        addrs = list(active.keys())

        try:

            url = f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs[:30])}"

            r = requests.get(url, timeout=8)

            pairs = r.json().get("pairs", [])

            for p in pairs:

                addr = p.get("baseToken", {}).get("address")

                if not addr:
                    continue

                if addr not in active:
                    continue

                price = p.get("priceUsd")

                if not price:
                    continue

                price = float(price)

                entry = active[addr]["entry"]

                pct = ((price - entry) / entry) * 100

                active[addr]["peak"] = max(active[addr]["peak"], price)

                drawdown = ((price - active[addr]["peak"]) / active[addr]["peak"]) * 100

                symbol = active[addr]["symbol"]

                # TAKE PROFIT
                if pct >= TAKE_PROFIT:

                    send(
                        f"🤑 *TAKE PROFIT*\n\n"
                        f"💎 *${symbol}*\n"
                        f"📈 `{pct:+.1f}%`\n\n"
                        f"💰 Realize lucro parcial"
                    )

                    with lock:
                        if addr in positions:
                            del positions[addr]

                # STOP LOSS
                elif pct <= STOP_LOSS:

                    send(
                        f"🚨 *STOP LOSS*\n\n"
                        f"💎 *${symbol}*\n"
                        f"📉 `{pct:.1f}%`\n\n"
                        f"⚠️ Proteja capital"
                    )

                    with lock:
                        if addr in positions:
                            del positions[addr]

                # TRAILING STOP
                elif drawdown <= TRAILING_STOP:

                    send(
                        f"⚠️ *TRAILING STOP*\n\n"
                        f"💎 *${symbol}*\n"
                        f"📉 Pullback forte após alta"
                    )

                    with lock:
                        if addr in positions:
                            del positions[addr]

        except:
            pass

# ============================================================
# REPORT
# ============================================================
def report():

    while True:

        time.sleep(1800)

        with lock:
            total = len(positions)

        send(
            f"📊 *RELATÓRIO*\n\n"
            f"🤖 Scanner Online\n"
            f"📡 Tokens monitorados: `{total}`\n"
            f"⚡ Workers: `{SCAN_WORKERS}`"
        )

# ============================================================
# HEALTH
# ============================================================
@app.route("/")
def health():
    return "WHALE QUANT SNIPER V3 ONLINE"

# ============================================================
# START
# ============================================================
if __name__ == "__main__":

    send(
        "🚀 *WHALE QUANT SNIPER V3 ONLINE*\n\n"
        "🐋 Whale flow detection\n"
        "🧠 Smart money detection\n"
        "📈 Volume acceleration\n"
        "⚡ Ultra early entries\n"
        "🛡️ Risk management enabled"
    )

    threading.Thread(target=sender, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()

    for i in range(SCAN_WORKERS):
        threading.Thread(target=scanner, args=(i,), daemon=True).start()

    for _ in range(8):
        threading.Thread(target=worker, daemon=True).start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
