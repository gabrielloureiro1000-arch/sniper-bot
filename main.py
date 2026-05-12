import os
import re
import time
import threading
import requests
import telebot

from flask import Flask
from queue import Queue, Empty
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

retries = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504],
)

adapter = HTTPAdapter(max_retries=retries)

session.mount("https://", adapter)
session.mount("http://", adapter)

# ============================================================
# TELEGRAM
# ============================================================

bot = telebot.TeleBot(
    TELEGRAM_TOKEN,
    threaded=True
)

# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

# ============================================================
# FILTROS (RELAXADOS)
# ============================================================

MIN_LIQ = 1000
MAX_LIQ = 1000000

MIN_BUYS = 1
MAX_BUYS = 5000

MIN_RATIO = 1.0
MIN_SELLS = 0

MIN_VOL = 50

MIN_AGE = 0
MAX_AGE = 300

MIN_M5 = -50
MAX_M5 = 500

MIN_H1 = -80
MAX_H1 = 1000

MAX_FDV = 100000000

# ============================================================
# PERFORMANCE
# ============================================================

SCAN_WORKERS = 6
FETCH_TIMEOUT = 4
SCAN_DELAY = 1
REPORT_INTERVAL = 7200
MAX_SEEN = 30000

# ============================================================
# ENDPOINTS
# ============================================================

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol",
    "https://api.dexscreener.com/latest/dex/search?q=pump",
    "https://api.dexscreener.com/latest/dex/search?q=moon",
    "https://api.dexscreener.com/latest/dex/search?q=gem",
    "https://api.dexscreener.com/latest/dex/search?q=ai",
    "https://api.dexscreener.com/latest/dex/search?q=launch",
    "https://api.dexscreener.com/latest/dex/search?q=trending",
    "https://api.dexscreener.com/latest/dex/search?q=memecoin",
    "https://api.dexscreener.com/latest/dex/search?q=new",
]

# ============================================================
# GLOBAL
# ============================================================

seen_tokens = deque(maxlen=MAX_SEEN)
seen_lookup = set()

monitored_tokens = {}

lock = threading.Lock()

alert_queue = Queue(maxsize=5000)

# ============================================================
# ESCAPE MARKDOWN
# ============================================================

def escape_md(text):

    if text is None:
        return ""

    return re.sub(
        r'([_*\[\]()~`>#+\-=|{}.!])',
        r'\\\1',
        str(text)
    )

# ============================================================
# TELEGRAM SEND
# ============================================================

def telegram_sender():

    while True:

        try:

            msg = alert_queue.get(timeout=5)

            for attempt in range(3):

                try:

                    bot.send_message(
                        CHAT_ID,
                        msg,
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True
                    )

                    print("TOKEN ENVIADO TELEGRAM")

                    break

                except Exception as e:

                    print(f"[TG ERROR] {e}")

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

def fetch_gmgn_bonus(addr):

    try:

        r = session.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gmgn.ai/"
            },
            timeout=4
        )

        if r.status_code != 200:
            return {}

        data = r.json()

        d = data.get("data", {}) or {}

        return {
            "smart": d.get("smart_degen_count", 0) or 0,
            "holders": d.get("holder_count", 0) or 0,
            "top10": d.get("top10_holder_rate", 0) or 0,
            "lp_burn": d.get("burn_ratio", 0) or 0,
            "honeypot": d.get("is_honeypot", False),
            "sell_tax": d.get("sell_tax", 0) or 0,
            "rug": d.get("rug_ratio", 0) or 0,
        }

    except Exception as e:

        print(f"[GMGN ERROR] {e}")

        return {}

# ============================================================
# RUG CHECK
# ============================================================

def is_hard_rug(g):

    try:

        if g.get("honeypot") is True:
            return True

        if g.get("rug", 0) > 0.9:
            return True

        if g.get("sell_tax", 0) > 20:
            return True

        top10 = g.get("top10", 0)

        if top10 > 0:

            t = float(top10) * 100 if float(top10) <= 1 else float(top10)

            if t > 80:
                return True

        return False

    except:
        return False

# ============================================================
# SCORE
# ============================================================

def calcular_score(data, g):

    score = 50

    if data["liq"] >= 30000:
        score -= 10

    if data["ratio"] >= 2:
        score -= 10

    if data["ratio"] >= 5:
        score -= 10

    if data["vol5m"] >= 5000:
        score -= 10

    if data["fdv"] <= 250000:
        score -= 10

    if data["age"] <= 5:
        score -= 10

    smart = g.get("smart", 0)

    if smart >= 5:
        score -= 20

    elif smart >= 2:
        score -= 10

    return max(0, min(100, score))

# ============================================================
# TOKENS
# ============================================================

def already_seen(addr):

    with lock:
        return addr in seen_lookup

def mark_seen(addr):

    with lock:

        if addr in seen_lookup:
            return

        if len(seen_tokens) >= MAX_SEEN:

            old = seen_tokens.popleft()

            seen_lookup.discard(old)

        seen_tokens.append(addr)

        seen_lookup.add(addr)

# ============================================================
# FILTERS
# ============================================================

def passes_filters(pair):

    try:

        if pair.get("chainId") != "solana":
            return False, None

        base = pair.get("baseToken", {})

        addr = base.get("address")

        if not addr:
            return False, None

        if already_seen(addr):
            return False, None

        liq = pair.get("liquidity", {}).get("usd", 0) or 0

        vol5m = pair.get("volume", {}).get("m5", 0) or 0

        tx = pair.get("txns", {}).get("m5", {})

        buys = tx.get("buys", 0)
        sells = tx.get("sells", 0)

        ratio = buys / max(sells, 1)

        pc = pair.get("priceChange", {})

        m5 = pc.get("m5", 0) or 0
        h1 = pc.get("h1", 0) or 0

        price = pair.get("priceUsd")

        fdv = pair.get("fdv", 0) or 0

        created = pair.get("pairCreatedAt")

        age = ((time.time() * 1000 - created) / 60000) if created else 999

        if not price:
            print("REJEITADO: SEM PREÇO")
            return False, None

        if liq < MIN_LIQ or liq > MAX_LIQ:
            print(f"REJEITADO LIQ: {liq}")
            return False, None

        if buys < MIN_BUYS or buys > MAX_BUYS:
            print(f"REJEITADO BUYS: {buys}")
            return False, None

        if ratio < MIN_RATIO:
            print(f"REJEITADO RATIO: {ratio}")
            return False, None

        if vol5m < MIN_VOL:
            print(f"REJEITADO VOL: {vol5m}")
            return False, None

        if age < MIN_AGE or age > MAX_AGE:
            print(f"REJEITADO AGE: {age}")
            return False, None

        if fdv > MAX_FDV:
            print(f"REJEITADO FDV: {fdv}")
            return False, None

        return True, {
            "addr": addr,
            "symbol": base.get("symbol", "???"),
            "price": float(price),
            "liq": liq,
            "vol5m": vol5m,
            "buys": buys,
            "sells": sells,
            "ratio": ratio,
            "m5": m5,
            "h1": h1,
            "age": age,
            "fdv": fdv,
        }

    except Exception as e:

        print(f"[FILTER ERROR] {e}")

        return False, None

# ============================================================
# FETCH
# ============================================================

def fetch_pairs(url):

    try:

        r = session.get(
            url,
            timeout=FETCH_TIMEOUT
        )

        if r.status_code != 200:
            return []

        data = r.json()

        return data.get("pairs") or []

    except Exception as e:

        print(f"[FETCH ERROR] {e}")

        return []

# ============================================================
# WORKER
# ============================================================

def scan_worker(worker_id):

    ep_index = worker_id

    while True:

        try:

            url = ENDPOINTS[ep_index % len(ENDPOINTS)]

            ep_index += 1

            print(f"ESCANEANDO: {url}")

            pairs = fetch_pairs(url)

            print(f"PAIRS ENCONTRADOS: {len(pairs)}")

            for pair in pairs:

                ok, data = passes_filters(pair)

                if not ok:
                    continue

                addr = data["addr"]

                g = fetch_gmgn_bonus(addr)

                if is_hard_rug(g):
                    print("RUG DETECTADO")
                    continue

                mark_seen(addr)

                score = calcular_score(data, g)

                if score <= 25:
                    emoji = "🚨"
                    label = "GEM DETECTADA"

                elif score <= 40:
                    emoji = "🟢"
                    label = "SINAL VERDE"

                elif score <= 65:
                    emoji = "🟡"
                    label = "SINAL AMARELO"

                else:
                    emoji = "🔴"
                    label = "SINAL VERMELHO"

                gmgn_url = f"https://gmgn.ai/sol/token/{addr}"

                msg = (
                    f"{emoji} *{escape_md(label)}*\n\n"

                    f"💎 *{escape_md(data['symbol'])}*\n"
                    f"`{escape_md(addr)}`\n\n"

                    f"💲 Price: `${data['price']:.10f}`\n"
                    f"💧 Liquidity: `${data['liq']:,.0f}`\n"
                    f"📊 Vol 5m: `${data['vol5m']:,.0f}`\n"

                    f"🔥 Buys: `{data['buys']}`\n"
                    f"🔻 Sells: `{data['sells']}`\n"

                    f"⚖️ Ratio: `{data['ratio']:.1f}x`\n"

                    f"⏰ Age: `{data['age']:.0f} min`\n"

                    f"🎯 Score: `{score}/100`\n\n"

                    f"🔗 [GMGN]({gmgn_url})"
                )

                print(f"TOKEN APROVADO: {data['symbol']}")

                send(msg)

            time.sleep(SCAN_DELAY)

        except Exception as e:

            print(f"[WORKER ERROR] {e}")

            time.sleep(2)

# ============================================================
# REPORT
# ============================================================

def performance_report():

    while True:

        try:

            report = (
                f"📊 *RELATÓRIO*\n\n"
                f"🤖 Scanner Online\n"
                f"📡 Tokens Monitorados: `{len(monitored_tokens)}`"
            )

            send(report)

        except Exception as e:

            print(f"[REPORT ERROR] {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTHCHECK
# ============================================================

@app.route("/")
def health():

    return "BOT ONLINE"

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("BOT ONLINE")

    send(
        "🚀 *BOT ONLINE*\n\n"
        "Scanner iniciado com sucesso"
    )

    threading.Thread(
        target=telegram_sender,
        daemon=True
    ).start()

    threading.Thread(
        target=performance_report,
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
        port=int(os.environ.get("PORT", 10000))
    )
