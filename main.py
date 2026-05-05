import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from queue import Queue, Empty

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT  = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# ================= PARÂMETROS QUANT =================
MIN_LIQ = 6000
MAX_LIQ = 250000

MIN_BUYS = 8
MIN_RATIO = 1.3
MIN_VOL = 400

MIN_AGE = 1
MAX_AGE = 35

MAX_MC = 2500000

MAX_OPEN_POSITIONS = 5

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20new",
    "https://api.dexscreener.com/latest/dex/search?q=solana%20trending",
]

# ================= ESTADO =================
seen = set()
queue_scan = Queue()
queue_alert = Queue()

positions = {}  # addr -> {entry, time, peak}

lock = threading.Lock()

# ================= TELEGRAM =================
def sender():
    while True:
        try:
            msg = queue_alert.get()
            bot.send_message(CHAT, msg, parse_mode="Markdown", disable_web_page_preview=True)
        except:
            pass

def send(msg):
    try:
        queue_alert.put_nowait(msg)
    except:
        pass

# ================= GMGN =================
def gmgn(addr):
    try:
        r = requests.get(f"https://gmgn.ai/api/v1/token/sol/{addr}", timeout=4)
        if r.status_code != 200:
            return {}
        d = r.json().get("data", {})
        return {
            "honeypot": d.get("is_honeypot", False),
            "tax": d.get("sell_tax", 0),
            "holders": d.get("holder_count", 0),
            "top10": d.get("top10_holder_rate", 1),
        }
    except:
        return {}

def safe(g):
    if not g:
        return True
    if g["honeypot"]:
        return False
    if g["tax"] > 12:
        return False
    if g["holders"] < 25:
        return False
    if g["top10"] > 0.7:
        return False
    return True

# ================= FEATURES =================
def extract(p):
    addr = p["baseToken"]["address"]

    liq = p.get("liquidity", {}).get("usd", 0) or 0
    vol5 = p.get("volume", {}).get("m5", 0) or 0
    vol1 = p.get("volume", {}).get("h1", 0) or 0

    tx = p.get("txns", {}).get("m5", {})
    buys = tx.get("buys", 0)
    sells = tx.get("sells", 0)

    ratio = buys / max(sells, 1)

    created = p.get("pairCreatedAt")
    age = ((time.time()*1000 - created)/60000) if created else 999

    mc = p.get("fdv") or 0

    accel = vol5 / max(vol1/12, 1) if vol1 else 1

    return {
        "addr": addr,
        "symbol": p["baseToken"]["symbol"],
        "price": float(p["priceUsd"]),
        "liq": liq,
        "vol5": vol5,
        "vol1": vol1,
        "buys": buys,
        "sells": sells,
        "ratio": ratio,
        "age": age,
        "mc": mc,
        "accel": accel
    }

# ================= SCORE QUANT =================
def score(d):
    s = 50
    signals = []

    # Liquidez ideal
    if 10000 <= d["liq"] <= 50000:
        s -= 10; signals.append("liq ideal")

    # fluxo
    if d["ratio"] > 3:
        s -= 12; signals.append("fluxo forte")
    elif d["ratio"] > 2:
        s -= 6

    # aceleração
    if d["accel"] > 4:
        s -= 15; signals.append("volume explodindo")
    elif d["accel"] > 2:
        s -= 8

    # idade
    if d["age"] < 10:
        s -= 10
    elif d["age"] > 25:
        s += 10

    # mc
    if d["mc"] < 300000:
        s -= 10
    elif d["mc"] > 1500000:
        s += 10

    # whale proxy
    if d["buys"] >= 20 and d["ratio"] > 2.5:
        s -= 15
        signals.append("🐋 possível whale")

    s = max(0, min(100, s))

    if s < 35:
        return "🟢", "FORTE", s, signals
    elif s < 65:
        return "🟡", "MÉDIO", s, signals
    else:
        return "🔴", "FRACO", s, signals

# ================= FILTRO =================
def valid(p):
    if p.get("chainId") != "solana":
        return False, None

    d = extract(p)

    if d["addr"] in seen:
        return False, None

    if d["liq"] < MIN_LIQ or d["liq"] > MAX_LIQ: return False, None
    if d["buys"] < MIN_BUYS: return False, None
    if d["ratio"] < MIN_RATIO: return False, None
    if d["vol5"] < MIN_VOL: return False, None
    if d["age"] < MIN_AGE or d["age"] > MAX_AGE: return False, None
    if d["mc"] > MAX_MC: return False, None

    return True, d

# ================= SCANNER =================
def scanner():
    while True:
        for url in ENDPOINTS:
            try:
                r = requests.get(url, timeout=4)
                for p in r.json().get("pairs", []):
                    ok, d = valid(p)
                    if not ok:
                        continue

                    seen.add(d["addr"])
                    queue_scan.put(d)

            except:
                pass
        time.sleep(0.3)

# ================= WORKER =================
def worker():
    while True:
        try:
            d = queue_scan.get()

            g = gmgn(d["addr"])
            if not safe(g):
                continue

            emoji, label, sc, sig = score(d)

            with lock:
                if len(positions) >= MAX_OPEN_POSITIONS:
                    continue

            msg = (
                f"{emoji} *{label}*\n"
                f"💎 ${d['symbol']}\n"
                f"`{d['addr']}`\n\n"
                f"💲 {d['price']:.10f}\n"
                f"💧 ${d['liq']:,.0f}\n"
                f"📊 Vol: ${d['vol5']:,.0f}\n"
                f"⚖️ {d['ratio']:.1f}x\n"
                f"⏰ {d['age']:.0f}m\n"
                f"📦 ${d['mc']:,.0f}\n\n"
                f"🎯 {sc}/100\n"
                f"📈 {' | '.join(sig)}\n\n"
                f"https://dexscreener.com/solana/{d['addr']}"
            )

            send(msg)

            if emoji == "🟢":
                with lock:
                    positions[d["addr"]] = {
                        "entry": d["price"],
                        "peak": d["price"],
                        "time": time.time()
                    }

        except:
            pass

# ================= MONITOR =================
def monitor():
    while True:
        time.sleep(45)

        for addr, pos in list(positions.items()):
            try:
                r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}", timeout=5)
                pairs = r.json().get("pairs", [])
                if not pairs:
                    continue

                price = float(pairs[0]["priceUsd"])
                pct = (price - pos["entry"]) / pos["entry"] * 100

                pos["peak"] = max(pos["peak"], price)
                drawdown = (price - pos["peak"]) / pos["peak"] * 100

                # STOP LOSS
                if pct <= -15:
                    send(f"🚨 STOP LOSS {addr} {pct:.1f}%")
                    del positions[addr]

                # TAKE PARCIAL
                elif pct >= 25:
                    send(f"💰 TAKE PROFIT {addr} +{pct:.1f}%")
                    del positions[addr]

                # TRAILING STOP
                elif drawdown <= -20:
                    send(f"⚠️ TRAILING STOP {addr}")
                    del positions[addr]

            except:
                pass

# ================= START =================
if __name__ == "__main__":
    send("🏦 QUANT BOT ONLINE")

    threading.Thread(target=sender, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()

    for _ in range(6):
        threading.Thread(target=worker, daemon=True).start()

    threading.Thread(target=monitor, daemon=True).start()

    app.run(host="0.0.0.0", port=10000)
