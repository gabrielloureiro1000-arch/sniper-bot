import os
import time
import random
import threading
import requests
import telebot

from flask import Flask
from queue import Queue, Empty
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# WHALE HUNTER GMGN — INSTITUTIONAL VERSION
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

app = Flask(__name__)

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

retries = Retry(
    total=4,
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
# CONFIG — ULTRA EARLY
# ============================================================

MIN_LIQ        = 3000
MAX_LIQ        = 180000

MIN_VOL5M      = 250
MIN_BUYS       = 4
MAX_BUYS       = 1500

MIN_RATIO      = 1.15

MIN_AGE        = 0.15
MAX_AGE        = 35

MIN_M5         = 0.2
MAX_M5         = 250

MIN_H1         = -30
MAX_H1         = 500

MIN_HOLDERS    = 15

REPORT_INTERVAL = 7200

# ============================================================
# SMART FILTERS
# ============================================================

MIN_WHALE_SCORE = 11

# ============================================================
# ENDPOINTS
# ============================================================

ENDPOINTS = [

    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot",
    "https://api.dexscreener.com/latest/dex/search?q=degen",
    "https://api.dexscreener.com/latest/dex/search?q=memecoin",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+trending",
]

# ============================================================
# STATE
# ============================================================

lock = threading.Lock()

history = {}
seen = {}

stats = {
    "sent": 0,
    "green": 0,
    "yellow": 0,
    "red": 0,
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
# GMGN DATA
# ============================================================

def get_gmgn(addr):

    try:

        r = session.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            timeout=5,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gmgn.ai/"
            }
        )

        if r.status_code != 200:
            return {}

        d = r.json().get("data", {}) or {}

        return {

            "smart": d.get("smart_degen_count", 0) or 0,

            "holders": d.get("holder_count", 0) or 0,

            "top10": d.get("top10_holder_rate", 0) or 0,

            "burn": d.get("burn_ratio", 0) or 0,

            "tax": d.get("sell_tax", 0) or 0,

            "rug": d.get("rug_ratio", 0) or 0,

            "hp": d.get("is_honeypot", False),

            "dev": d.get("developer_holding_rate", 0) or 0
        }

    except:
        return {}

# ============================================================
# ANTI RUG
# ============================================================

def is_lixo(g):

    try:

        if g.get("hp") is True:
            return True, "HONEYPOT"

        if g.get("tax", 0) > 20:
            return True, "SELL TAX"

        if g.get("rug", 0) > 0.80:
            return True, "RUG"

        top10 = g.get("top10", 0)

        if top10:

            t = (
                float(top10) * 100
                if float(top10) <= 1
                else float(top10)
            )

            if t > 80:
                return True, "TOP10"

        dev = g.get("dev", 0)

        if dev:

            d = (
                float(dev) * 100
                if float(dev) <= 1
                else float(dev)
            )

            if d > 15:
                return True, "DEV"

    except:
        pass

    return False, ""

# ============================================================
# SCORE
# ============================================================

def whale_score(data, g):

    pontos = 0

    buys   = data["buys"]
    sells  = data["sells"]
    ratio  = data["ratio"]
    age    = data["age"]
    m5     = data["m5"]
    h1     = data["h1"]
    accel  = data["accel"]

    smart  = g.get("smart", 0)
    holders = g.get("holders", 0)

    # ========================================================
    # BUY PRESSURE
    # ========================================================

    if ratio >= 4:
        pontos += 5
    elif ratio >= 2:
        pontos += 4
    elif ratio >= 1.5:
        pontos += 2

    # ========================================================
    # WHALES
    # ========================================================

    if buys >= 40:
        pontos += 5
    elif buys >= 20:
        pontos += 4
    elif buys >= 10:
        pontos += 3
    elif buys >= 5:
        pontos += 2

    # ========================================================
    # ULTRA EARLY
    # ========================================================

    if age <= 3:
        pontos += 5
    elif age <= 8:
        pontos += 4
    elif age <= 15:
        pontos += 3

    # ========================================================
    # MOMENTUM
    # ========================================================

    if m5 >= 20:
        pontos += 4
    elif m5 >= 10:
        pontos += 3
    elif m5 >= 3:
        pontos += 2

    # ========================================================
    # ACCELERATION
    # ========================================================

    if accel >= 4:
        pontos += 5
    elif accel >= 2:
        pontos += 3
    elif accel >= 1.3:
        pontos += 2

    # ========================================================
    # SMART MONEY
    # ========================================================

    if smart >= 8:
        pontos += 7
    elif smart >= 5:
        pontos += 5
    elif smart >= 3:
        pontos += 4
    elif smart >= 1:
        pontos += 2

    # ========================================================
    # HOLDERS
    # ========================================================

    if holders >= 300:
        pontos += 4
    elif holders >= 120:
        pontos += 3
    elif holders >= 40:
        pontos += 2

    # ========================================================
    # SELL PRESSURE
    # ========================================================

    if sells >= buys:
        pontos -= 4

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    if pontos >= 28:
        return "🟢", "VERDE — ELITE", pontos

    elif pontos >= 18:
        return "🟡", "AMARELO — BOM", pontos

    else:
        return "🔴", "VERMELHO — RISCO", pontos

# ============================================================
# PROCESS TOKEN
# ============================================================

def processar(pair):

    try:

        if pair.get("chainId") != "solana":
            return

        base = pair.get("baseToken", {})

        addr = base.get("address")

        if not addr:
            return

        now = time.time()

        old = seen.get(addr)

        if old and now - old < 900:
            return

        liq = pair.get("liquidity", {}).get("usd", 0) or 0

        vol5m = pair.get("volume", {}).get("m5", 0) or 0
        vol1h = pair.get("volume", {}).get("h1", 0) or 0

        tx = pair.get("txns", {}).get("m5", {})

        buys = tx.get("buys", 0)
        sells = tx.get("sells", 0)

        ratio = buys / max(sells, 1)

        pc = pair.get("priceChange", {})

        m5 = pc.get("m5", 0) or 0
        h1 = pc.get("h1", 0) or 0

        price = pair.get("priceUsd")

        if not price:
            return

        created = pair.get("pairCreatedAt")

        age = (
            (time.time() * 1000 - created) / 60000
            if created else 999
        )

        # ====================================================
        # FILTERS
        # ====================================================

        if liq < MIN_LIQ or liq > MAX_LIQ:
            return

        if buys < MIN_BUYS or buys > MAX_BUYS:
            return

        if ratio < MIN_RATIO:
            return

        if vol5m < MIN_VOL5M:
            return

        if age < MIN_AGE or age > MAX_AGE:
            return

        if m5 < MIN_M5 or m5 > MAX_M5:
            return

        if h1 < MIN_H1 or h1 > MAX_H1:
            return

        # ====================================================
        # ANTI FAKE VOLUME
        # ====================================================

        if sells > 0:

            sell_ratio = sells / max(buys, 1)

            if sell_ratio < 0.02:
                return

            if sell_ratio > 1.2:
                return

        # ====================================================
        # ACCELERATION
        # ====================================================

        accel = 0

        if vol1h > 0:

            accel = vol5m / max((vol1h / 12), 1)

        whale_mode = (

            buys >= 8 and
            ratio >= 1.5 and
            accel >= 1.4

        )

        ultra_early = (

            age <= 5 and
            buys >= 5 and
            m5 >= 1.5

        )

        if not whale_mode and not ultra_early:
            return

        # ====================================================
        # GMGN
        # ====================================================

        g = get_gmgn(addr)

        lixo, motivo = is_lixo(g)

        if lixo:
            return

        holders = g.get("holders", 0)

        if holders > 0 and holders < MIN_HOLDERS:
            return

        # ====================================================
        # SCORE
        # ====================================================

        emoji, label, pontos = whale_score({

            "buys": buys,
            "sells": sells,
            "ratio": ratio,
            "age": age,
            "m5": m5,
            "h1": h1,
            "accel": accel

        }, g)

        if pontos < MIN_WHALE_SCORE:
            return

        # ====================================================
        # SAVE
        # ====================================================

        seen[addr] = now

        symbol = base.get("symbol", "???")

        price = float(price)

        with lock:

            history[addr] = {

                "symbol": symbol,
                "price": price,
                "time": datetime.utcnow().strftime("%H:%M UTC"),
                "signal": label,
                "last_alert": now
            }

            stats["sent"] += 1

            if "VERDE" in label:
                stats["green"] += 1

            elif "AMARELO" in label:
                stats["yellow"] += 1

            else:
                stats["red"] += 1

        # ====================================================
        # TARGETS
        # ====================================================

        breakeven = price * 1.03
        tp1 = price * 1.30
        tp2 = price * 1.70
        tp3 = price * 3.00
        stop = price * 0.86

        # ====================================================
        # FORCE BAR
        # ====================================================

        strength = min(int(pontos / 3), 10)

        bar = "🟢" * strength + "⚪" * (10 - strength)

        # ====================================================
        # GMGN INFO
        # ====================================================

        smart = g.get("smart", 0)

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
        # COMMENT
        # ====================================================

        comments = []

        if smart >= 5:
            comments.append("🐋 whales entrando")

        if accel >= 2:
            comments.append("⚡ volume acelerando")

        if age <= 5:
            comments.append("🧨 ultra early")

        if holders >= 150:
            comments.append("👥 holders crescendo")

        if ratio >= 3:
            comments.append("📈 pressão compradora")

        comment = " | ".join(comments)

        # ====================================================
        # ALERT
        # ====================================================

        msg = (

            f"{emoji} *{label}*\n"
            f"`Score: {pontos}/40`\n\n"

            f"💎 *${symbol}*\n"
            f"`{addr}`\n\n"

            f"💲 Entrada: `${price:.10f}`\n\n"

            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n\n"

            f"🔥 Buys: `{buys}`\n"
            f"📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"

            f"📈 5m: `{m5:+.1f}%`\n"
            f"🚀 1h: `{h1:+.1f}%`\n"
            f"⚡ Aceleração: `{accel:.2f}x`\n\n"

            f"⏰ Idade: `{age:.1f} min`\n\n"

            f"🧠 Smart Money: `{smart}`\n"
            f"👥 Holders: `{holders}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`\n"
            f"🔒 LP Burn: `{burn_pct:.0f}%`\n\n"

            f"💪 Força:\n{bar}\n\n"

            f"📝 {comment}\n\n"

            f"━━━ 💰 SAÍDAS ━━━\n"

            f"⚖️ Breakeven: `${breakeven:.10f}`\n"
            f"🎯 TP1: `${tp1:.10f}` (+30%)\n"
            f"🚀 TP2: `${tp2:.10f}` (+70%)\n"
            f"🌕 TP3: `${tp3:.10f}` (+200%)\n"
            f"🛑 Stop: `${stop:.10f}` (-14%)\n\n"

            f"🟢 GMGN\n"
            f"https://gmgn.ai/sol/token/{addr}\n\n"

            f"📊 DEX\n"
            f"https://dexscreener.com/solana/{addr}\n\n"

            f"⚡ TROJAN\n"
            f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
        )

        send(msg)

    except Exception as e:

        print(f"[PROCESS] {e}")

# ============================================================
# SCANNER 24H
# ============================================================

def scan():

    idx = random.randint(0, len(ENDPOINTS)-1)

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

                data = r.json().get("pairs") or []

                for pair in data:

                    processar(pair)

        except Exception as e:

            print(f"[SCAN] {e}")

        time.sleep(0.15)

# ============================================================
# MONITOR
# ============================================================

def monitor_saida():

    time.sleep(120)

    while True:

        try:

            with lock:

                check = {
                    k: v for k, v in history.items()
                    if not v.get("saiu")
                }

            if not check:

                time.sleep(120)

                continue

            addrs = list(check.keys())

            prices = {}

            for i in range(0, len(addrs), 30):

                batch = ",".join(addrs[i:i+30])

                try:

                    r = session.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=8
                    )

                    pairs = r.json().get("pairs") or []

                    for p in pairs:

                        a = p.get("baseToken", {}).get("address")

                        v = p.get("priceUsd")

                        s = p.get("txns", {}).get("m5", {}).get("sells", 0)

                        if a and v:

                            prices[a] = {
                                "price": float(v),
                                "sells": s
                            }

                except:
                    pass

            for addr, info in check.items():

                d = prices.get(addr)

                if not d:
                    continue

                pct = (
                    (d["price"] - info["price"])
                    / info["price"]
                ) * 100

                sells = d["sells"]

                msg = None

                if pct <= -14:

                    msg = (

                        f"🚨 *STOP LOSS*\n\n"

                        f"💎 *${info['symbol']}*\n"

                        f"📉 `{pct:.1f}%`\n\n"

                        f"⚠️ Capital protegido"
                    )

                elif pct >= 70:

                    msg = (

                        f"🤑 *TAKE PROFIT*\n\n"

                        f"💎 *${info['symbol']}*\n"

                        f"🚀 `+{pct:.1f}%`\n\n"

                        f"💰 Realize parcial"
                    )

                elif sells >= 50 and pct < -5:

                    msg = (

                        f"⚠️ *DUMP DETECTADO*\n\n"

                        f"💎 *${info['symbol']}*\n"

                        f"📉 `{pct:+.1f}%`\n"

                        f"🔥 `{sells}` sells/5m"
                    )

                if msg:

                    send(msg)

                    with lock:

                        if addr in history:
                            history[addr]["saiu"] = True

        except Exception as e:

            print(f"[MONITOR] {e}")

        time.sleep(120)

# ============================================================
# REPORT
# ============================================================

def relatorio():

    time.sleep(REPORT_INTERVAL)

    while True:

        try:

            with lock:

                st = dict(stats)

                stats.update({
                    "sent": 0,
                    "green": 0,
                    "yellow": 0,
                    "red": 0
                })

            txt = (

                f"📊 *RELATÓRIO 2H*\n\n"

                f"📤 Alertas: `{st['sent']}`\n\n"

                f"🟢 Elite: `{st['green']}`\n"
                f"🟡 Bons: `{st['yellow']}`\n"
                f"🔴 Risco: `{st['red']}`\n\n"

                f"🐋 Whale monitor ativo\n"
                f"⚡ Ultra early sniper ativo\n"
                f"🧠 GMGN smart money online\n"
                f"📈 Entrada antes do varejo\n"
                f"🛡️ Anti rug ativo"
            )

            send(txt)

        except Exception as e:

            print(f"[REPORT] {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# CLEANER
# ============================================================

def limpeza():

    while True:

        try:

            now = time.time()

            remover = []

            with lock:

                for addr, data in history.items():

                    ts = data.get("last_alert", now)

                    if now - ts > 21600:
                        remover.append(addr)

                for r in remover:
                    del history[r]

            remover_seen = []

            for k, v in seen.items():

                if now - v > 14400:
                    remover_seen.append(k)

            for r in remover_seen:
                del seen[r]

        except:
            pass

        time.sleep(1800)

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
        f"🟡{stats['yellow']} "
        f"🔴{stats['red']}"
    )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    send(

        "🟢 *WHALE HUNTER — ONLINE*\n\n"

        "🐋 Monitorando baleias 24h\n"
        "⚡ Ultra early sniper ativo\n"
        "🧠 Smart money detection\n"
        "📊 GMGN + DexScreener\n"
        "🚀 Entrada antes do varejo\n"
        "🛡️ Anti rug system\n"
        "💰 TP/SL automático\n"
        "📢 Relatório a cada 2h"
    )

    threading.Thread(
        target=tg_worker,
        daemon=True
    ).start()

    threading.Thread(
        target=monitor_saida,
        daemon=True
    ).start()

    threading.Thread(
        target=relatorio,
        daemon=True
    ).start()

    threading.Thread(
        target=limpeza,
        daemon=True
    ).start()

    # ========================================================
    # 20 SCANNERS PARA FICAR 24H
    # ========================================================

    for i in range(20):

        threading.Thread(
            target=scan,
            daemon=True
        ).start()

        time.sleep(0.05)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
