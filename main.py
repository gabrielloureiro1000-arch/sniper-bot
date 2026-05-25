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
# FILTROS QUANT
# ============================================================

MIN_LIQ      = 4_000
MAX_LIQ      = 350_000

MIN_BUYS     = 6
MAX_BUYS     = 1200

MIN_RATIO    = 1.25
MIN_SELLS    = 1

MIN_VOL      = 400

MIN_AGE      = 0.2
MAX_AGE      = 45

MIN_M5       = 0.5
MAX_M5       = 120.0

MIN_H1       = -15.0
MAX_H1       = 400.0

REPORT_INTERVAL = 7200

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
]

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

retries = Retry(
    total=3,
    backoff_factor=0.5,
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
# GMGN DATA
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

        if g.get("tax", 0) > 25:
            return True, "SELL TAX"

        if g.get("rug", 0) > 0.85:
            return True, "RUG"

        top10 = g.get("top10", 0)

        if top10:

            t = (
                float(top10) * 100
                if float(top10) <= 1
                else float(top10)
            )

            if t > 85:
                return True, "TOP10"

    except:
        pass

    return False, ""

# ============================================================
# SCORE
# ============================================================

def sinal(data, g):

    pontos = 0

    ratio = data["ratio"]
    buys  = data["buys"]
    age   = data["age"]
    h1    = data["h1"]

    if ratio >= 4:
        pontos += 4
    elif ratio >= 2:
        pontos += 3
    else:
        pontos += 1

    if buys >= 40:
        pontos += 4
    elif buys >= 20:
        pontos += 3
    elif buys >= 10:
        pontos += 2

    if age <= 5:
        pontos += 4
    elif age <= 15:
        pontos += 3
    elif age <= 30:
        pontos += 2

    if h1 <= 30:
        pontos += 3
    elif h1 <= 80:
        pontos += 2

    smart = g.get("smart", 0)

    if smart >= 5:
        pontos += 5
    elif smart >= 2:
        pontos += 3
    elif smart >= 1:
        pontos += 1

    burn = g.get("burn", 0)

    if burn:

        b = (
            float(burn) * 100
            if float(burn) <= 1
            else float(burn)
        )

        if b >= 80:
            pontos += 3
        elif b >= 50:
            pontos += 1

    top10 = g.get("top10", 0)

    if top10:

        t = (
            float(top10) * 100
            if float(top10) <= 1
            else float(top10)
        )

        if t <= 25:
            pontos += 2
        elif t >= 50:
            pontos -= 3

    if pontos >= 18:
        return "🟢", "VERDE — ELITE", "Smart money entrando"

    elif pontos >= 12:
        return "🟡", "AMARELO — BOM", "Momentum saudável"

    else:
        return "🔴", "VERMELHO — RISCO", "Possível manipulação"

# ============================================================
# PROCESSAR TOKEN
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

        if m5 < MIN_M5 or m5 > MAX_M5:
            return

        if h1 < MIN_H1 or h1 > MAX_H1:
            return

        # ====================================================
        # ACELERAÇÃO
        # ====================================================

        vol_accel = 0

        if vol1h > 0:
            vol_accel = vol5m / max(vol1h / 12, 1)

        whale_mode = (
            buys >= 12 and
            ratio >= 2 and
            vol_accel >= 1.8
        )

        ultra_early = (
            age <= 5 and
            buys >= 8 and
            m5 >= 2
        )

        if not whale_mode and not ultra_early:
            return

        # ====================================================
        # ANTI BOT
        # ====================================================

        if sells > 0:

            sell_ratio = sells / max(buys, 1)

            if sell_ratio < 0.03:
                return

            if sell_ratio > 0.95:
                return

        # ====================================================
        # REANÁLISE
        # ====================================================

        now = time.time()

        old = history.get(addr)

        if old:

            last = old.get("last_alert", 0)

            if now - last < 900:
                return

        # ====================================================
        # GMGN
        # ====================================================

        g = get_gmgn(addr)

        lixo, motivo = is_lixo(g)

        if lixo:
            return

        # ====================================================
        # SCORE
        # ====================================================

        emoji, label, desc = sinal({

            "ratio": ratio,
            "buys": buys,
            "age": age,
            "h1": h1

        }, g)

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

        empate = price * 1.03
        alvo1  = price * 1.25
        alvo2  = price * 1.60
        alvo3  = price * 2.50
        stop   = price * 0.87

        # ====================================================
        # FORÇA
        # ====================================================

        forca = min(int(ratio * 1.5), 10)

        barra = "🟢" * forca + "⚪" * (10 - forca)

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
        # ALERTA
        # ====================================================

        msg = (

            f"{emoji} *{label}*\n"
            f"_{desc}_\n\n"

            f"💎 *${symbol}*\n"
            f"`{addr}`\n\n"

            f"💲 Entrada: `${price:.10f}`\n\n"

            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n\n"

            f"🔥 Buys: `{buys}`\n"
            f"📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"

            f"📈 5m: `{m5:+.1f}%`\n"
            f"🚀 1h: `{h1:+.1f}%`\n\n"

            f"⏰ Idade: `{age:.1f} min`\n\n"

            f"🧠 Smart Money: `{smart}`\n"
            f"👥 Holders: `{holders}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`\n"
            f"🔒 LP Burn: `{burn_pct:.0f}%`\n\n"

            f"💪 Força:\n{barra}\n\n"

            f"━━━ 💰 SAÍDAS ━━━\n"

            f"⚖️ Breakeven: `${empate:.10f}`\n"
            f"🎯 TP1: `${alvo1:.10f}` (+25%)\n"
            f"🚀 TP2: `${alvo2:.10f}` (+60%)\n"
            f"🌕 TP3: `${alvo3:.10f}` (+150%)\n"
            f"🛑 Stop: `${stop:.10f}` (-13%)\n\n"

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
# SCANNER 24H
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

                    threading.Thread(
                        target=processar,
                        args=(pair,),
                        daemon=True
                    ).start()

        except Exception as e:

            print(f"[SCAN] {e}")

        time.sleep(0.25)

# ============================================================
# MONITOR SAÍDA
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

            precos = {}

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

                            precos[a] = {
                                "price": float(v),
                                "sells": s
                            }

                except:
                    pass

            for addr, info in check.items():

                d = precos.get(addr)

                if not d:
                    continue

                pct = (
                    (d["price"] - info["price"])
                    / info["price"]
                ) * 100

                sells = d["sells"]

                msg = None

                if pct <= -13:

                    msg = (

                        f"🚨 *STOP LOSS*\n\n"

                        f"💎 *${info['symbol']}*\n"

                        f"📉 `{pct:.1f}%`\n\n"

                        f"⚠️ Proteja o capital"
                    )

                elif pct >= 60:

                    msg = (

                        f"🤑 *TAKE PROFIT*\n\n"

                        f"💎 *${info['symbol']}*\n"

                        f"🚀 `+{pct:.1f}%`\n\n"

                        f"💰 Realize parcial"
                    )

                elif sells > 40 and pct < -5:

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

            print(f"[SAIDA] {e}")

        time.sleep(120)

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

                f"🧠 Scanner ativo 24h\n"
                f"🐋 Whale detection online\n"
                f"⚡ Ultra early monitor ativo"
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
        f"WHALE QUANT ONLINE | "
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

        "🟢 *WHALE QUANT — ONLINE*\n\n"

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
    # 12 THREADS
    # ========================================================

    for i in range(12):

        threading.Thread(
            target=scan,
            daemon=True
        ).start()

        time.sleep(0.1)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
