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
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

app = Flask(__name__)

# ============================================================
# FILTROS INSTITUCIONAIS
# ============================================================

MIN_LIQ      = 8_000
MAX_LIQ      = 250_000

MIN_BUYS     = 5
MAX_BUYS     = 300

MIN_RATIO    = 1.8
MIN_SELLS    = 1

MIN_VOL      = 250

MIN_AGE      = 0.05
MAX_AGE      = 35

MAX_M5       = 25.0
MAX_H1       = 150.0

REPORT_INTERVAL = 7200

# ============================================================
# ENDPOINTS
# ============================================================

ENDPOINTS = [

    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot",
    "https://api.dexscreener.com/latest/dex/search?q=degen",
]

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
    pool_connections=100,
    pool_maxsize=100,
    max_retries=retries
)

session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ============================================================
# STATE
# ============================================================

lock = threading.Lock()

history = {}

holders_memory = {}

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
            timeout=4,
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

            "dev": d.get("creator_hold_percent", 0) or 0,
        }

    except:
        return {}

# ============================================================
# ANTI LIXO
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

            if t > 40:
                return True, "TOP10"

        dev = g.get("dev", 0)

        if dev:

            d = (
                float(dev) * 100
                if float(dev) <= 1
                else float(dev)
            )

            if d > 12:
                return True, "DEV"

    except:
        pass

    return False, ""

# ============================================================
# SCORE INSTITUCIONAL
# ============================================================

def score_token(data, g, holder_growth):

    pontos = 0

    ratio = data["ratio"]
    buys = data["buys"]
    age = data["age"]
    m5 = data["m5"]
    vol_accel = data["vol_accel"]

    # ========================================================
    # SMART MONEY
    # ========================================================

    smart = g.get("smart", 0)

    if smart >= 8:
        pontos += 12

    elif smart >= 5:
        pontos += 9

    elif smart >= 3:
        pontos += 6

    elif smart >= 1:
        pontos += 3

    # ========================================================
    # HOLDER GROWTH
    # ========================================================

    if holder_growth >= 80:
        pontos += 10

    elif holder_growth >= 40:
        pontos += 7

    elif holder_growth >= 20:
        pontos += 4

    # ========================================================
    # BUY / SELL
    # ========================================================

    if ratio >= 4:
        pontos += 8

    elif ratio >= 2.5:
        pontos += 6

    elif ratio >= 1.8:
        pontos += 3

    # ========================================================
    # BUYS
    # ========================================================

    if buys >= 30:
        pontos += 6

    elif buys >= 15:
        pontos += 4

    elif buys >= 8:
        pontos += 2

    # ========================================================
    # VOLUME BEFORE PRICE
    # ========================================================

    if vol_accel >= 3:
        pontos += 8

    elif vol_accel >= 2:
        pontos += 5

    # ========================================================
    # STEALTH BUY
    # ========================================================

    stealth = (
        buys >= 6 and
        buys <= 25 and
        ratio >= 2.2 and
        age <= 12 and
        vol_accel >= 2 and
        m5 <= 15
    )

    if stealth:
        pontos += 10

    # ========================================================
    # AGE
    # ========================================================

    if age <= 5:
        pontos += 6

    elif age <= 12:
        pontos += 4

    elif age <= 20:
        pontos += 2

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
            pontos += 5

        elif t <= 30:
            pontos += 3

        elif t >= 35:
            pontos -= 6

    # ========================================================
    # BURN
    # ========================================================

    burn = g.get("burn", 0)

    if burn:

        b = (
            float(burn) * 100
            if float(burn) <= 1
            else float(burn)
        )

        if b >= 80:
            pontos += 4

    # ========================================================
    # RESULTADO
    # ========================================================

    if pontos >= 40:
        return "🟢", "VERDE — WHALE ENTRY", "Smart money entrando cedo"

    elif pontos >= 24:
        return "🟡", "AMARELO — MOMENTUM", "Fluxo saudável"

    else:
        return "🔴", "VERMELHO — RISCO", "Possível manipulação"

# ============================================================
# PROCESSAR
# ============================================================

def processar(pair):

    try:

        if pair.get("chainId") != "solana":
            return

        base = pair.get("baseToken", {})

        addr = base.get("address")

        if not addr:
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
        # FILTROS
        # ====================================================

        if liq < MIN_LIQ or liq > MAX_LIQ:
            return

        if buys < MIN_BUYS or buys > MAX_BUYS:
            return

        if ratio < MIN_RATIO:
            return

        if sells < MIN_SELLS:
            return

        if vol5m < MIN_VOL:
            return

        if age < MIN_AGE or age > MAX_AGE:
            return

        if abs(m5) > MAX_M5:
            return

        if abs(h1) > MAX_H1:
            return

        # ====================================================
        # ANTI WASH
        # ====================================================

        if buys > 80 and sells <= 2:
            return

        sell_ratio = sells / max(buys, 1)

        if sell_ratio < 0.03:
            return

        if sell_ratio > 0.95:
            return

        # ====================================================
        # VOLUME ACCEL
        # ====================================================

        vol_accel = 0

        if vol1h > 0:
            vol_accel = vol5m / max(vol1h / 12, 1)

        # ====================================================
        # CONSOLIDAÇÃO
        # ====================================================

        consolidacao = (
            m5 >= -5 and
            m5 <= 12 and
            ratio >= 2.5 and
            buys >= 10
        )

        stealth = (
            buys >= 6 and
            buys <= 25 and
            ratio >= 2.2 and
            age <= 12 and
            vol_accel >= 2 and
            m5 <= 15
        )

        whale_entry = (
            buys >= 12 and
            ratio >= 2 and
            vol_accel >= 1.8
        )

        if not stealth and not whale_entry and not consolidacao:
            return

        # ====================================================
        # COOLDOWN
        # ====================================================

        now = time.time()

        old = history.get(addr)

        if old:

            last = old.get("last_alert", 0)

            if now - last < 1200:
                return

        # ====================================================
        # GMGN
        # ====================================================

        g = get_gmgn(addr)

        lixo, motivo = is_lixo(g)

        if lixo:
            return

        # ====================================================
        # HOLDERS
        # ====================================================

        holders = g.get("holders", 0)

        old_holders = holders_memory.get(addr, holders)

        holder_growth = holders - old_holders

        holders_memory[addr] = holders

        # ====================================================
        # SCORE
        # ====================================================

        emoji, label, desc = score_token({

            "ratio": ratio,
            "buys": buys,
            "age": age,
            "m5": m5,
            "vol_accel": vol_accel

        }, g, holder_growth)

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
        # SAÍDAS
        # ====================================================

        breakeven = price * 1.03
        tp1 = price * 1.30
        tp2 = price * 1.80
        tp3 = price * 3.00
        stop = price * 0.85

        # ====================================================
        # FORÇA
        # ====================================================

        força = min(int(ratio * 2), 10)

        barra = "🟢" * força + "⚪" * (10 - força)

        # ====================================================
        # DADOS
        # ====================================================

        smart = g.get("smart", 0)

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
            f"⚡ Volume accel: `{vol_accel:.1f}x`\n\n"

            f"🔥 Buys: `{buys}`\n"
            f"📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"

            f"📈 5m: `{m5:+.1f}%`\n"
            f"🚀 1h: `{h1:+.1f}%`\n\n"

            f"⏰ Idade: `{age:.1f} min`\n\n"

            f"🧠 Smart Money: `{smart}`\n"
            f"👥 Holders: `{holders}`\n"
            f"📈 Holder Growth: `+{holder_growth}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`\n"
            f"🔒 LP Burn: `{burn_pct:.0f}%`\n\n"

            f"💪 Força:\n{barra}\n\n"

            f"━━━ 💰 SAÍDAS ━━━\n"

            f"⚖️ Breakeven: `${breakeven:.10f}`\n"
            f"🎯 TP1: `${tp1:.10f}` (+30%)\n"
            f"🚀 TP2: `${tp2:.10f}` (+80%)\n"
            f"🌕 TP3: `${tp3:.10f}` (+200%)\n"
            f"🛑 Stop: `${stop:.10f}` (-15%)\n\n"

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

        url = ENDPOINTS[idx % len(ENDPOINTS)]

        idx += 1

        try:

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

        time.sleep(0.20)

# ============================================================
# RELATÓRIO
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

                f"📤 Alertas: `{st['sent']}`\n"

                f"🟢 Verdes: `{st['green']}`\n"
                f"🟡 Amarelos: `{st['yellow']}`\n"
                f"🔴 Vermelhos: `{st['red']}`\n\n"

                f"🐋 Whale monitor ativo\n"
                f"🧠 Smart money scanner\n"
                f"⚡ Stealth buy detector\n"
                f"📈 Holder growth tracker\n"
                f"🚀 Ultra early monitor\n"
                f"🛡️ Anti rug system"
            )

            send(txt)

        except Exception as e:

            print(f"[RELATORIO] {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# LIMPEZA
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

        except:
            pass

        time.sleep(1800)

# ============================================================
# HEALTH
# ============================================================

@app.route("/")

def health():

    return (
        f"WHALE ENTRY ONLINE | "
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

        "🟢 *WHALE ENTRY — ONLINE*\n\n"

        "🐋 Whale tracking 24h\n"
        "🧠 Smart money detector\n"
        "⚡ Stealth buy monitor\n"
        "📈 Holder growth scanner\n"
        "🚀 Ultra early sniper\n"
        "🛡️ Anti rug system\n"
        "💰 Institutional strategy\n"
        "📢 Relatório a cada 2h"
    )

    threading.Thread(
        target=tg_worker,
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
    # 8 SCANNERS
    # ========================================================

    for i in range(8):

        threading.Thread(
            target=scan,
            daemon=True
        ).start()

        time.sleep(0.1)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
