import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty
from collections import deque
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re

# ============================================================
# CONFIGURAÇÃO
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ============================================================
# SESSION HTTP COM RETRY
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
# MARKDOWN ESCAPE
# ============================================================

MD_SPECIAL = r'_*[]()~`>#+-=|{}.!'

def escape_md(text):
    if text is None:
        return ""
    return re.sub(r'([\\_*[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

# ============================================================
# FILTROS
# ============================================================

MIN_LIQ = 10_000
MAX_LIQ = 300_000

MIN_BUYS = 10
MAX_BUYS = 800

MIN_RATIO = 1.8
MIN_SELLS = 2

MIN_VOL = 1_000

MIN_AGE = 3
MAX_AGE = 45

MIN_M5 = 1.0
MAX_M5 = 35.0

MIN_H1 = 2.0
MAX_H1 = 150.0

# ============================================================
# VELOCIDADE
# ============================================================

SCAN_WORKERS = 8
FETCH_TIMEOUT = 4
REPORT_INTERVAL = 7200
MAX_SEEN = 30000

# RATE LIMIT
SCAN_DELAY = 1.0

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+hot",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================

seen_tokens = deque(maxlen=MAX_SEEN)
seen_lookup = set()

monitored_tokens = {}

report_stats = {
    "sent": 0,
    "green": 0,
    "yellow": 0,
    "red": 0
}

lock = threading.Lock()

alert_queue = Queue(maxsize=5000)

# ============================================================
# BOT
# ============================================================

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True)

app = Flask(__name__)

# ============================================================
# TELEGRAM
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
                    break

                except Exception as e:
                    print(f"[TG] {attempt+1}: {e}")
                    time.sleep(1)

        except Empty:
            continue

def send(msg: str):
    try:
        alert_queue.put_nowait(msg)
    except Exception:
        pass

# ============================================================
# GMGN
# ============================================================

def fetch_gmgn_bonus(addr: str) -> dict:
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

        try:
            data = r.json()
        except:
            return {}

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

    except:
        return {}

# ============================================================
# RUG CHECK
# ============================================================

def is_hard_rug(g: dict):

    if g.get("honeypot") is True:
        return True, "HONEYPOT confirmado"

    if g.get("rug", 0) > 0.9:
        return True, f"Rug ratio {g['rug']:.0%}"

    if g.get("sell_tax", 0) > 20:
        return True, f"Sell tax abusiva"

    top10 = g.get("top10", 0)

    if top10 > 0:

        t = float(top10) * 100 if float(top10) <= 1 else float(top10)

        if t > 80:
            return True, f"Top10 com {t:.0f}%"

    return False, ""

# ============================================================
# SCORE
# ============================================================

def calcular_score_e_saida(data: dict, g: dict):

    score = 65

    greens = []
    yellows = []
    reds = []

    liq = data["liq"]

    if liq >= 80000:
        score -= 5
        greens.append("Liq saudável")

    elif liq >= 30000:
        score -= 10
        greens.append("Liq ideal")

    elif liq >= 10000:
        score += 3
        yellows.append("Liq baixa")

    r = data["ratio"]

    if r >= 6:
        score -= 12
        greens.append("Pressão compradora forte")

    elif r >= 3:
        score -= 7
        greens.append("Pressão compradora boa")

    elif r >= 2:
        score -= 3
        greens.append("Pressão compradora")

    b = data["buys"]

    if b >= 50:
        score -= 10
        greens.append("Muitas compras")

    elif b >= 25:
        score -= 6
        greens.append("Boas compras")

    elif b >= 10:
        score -= 2
        greens.append("Baleias entrando")

    age = data["age"]

    if age <= 5:
        score -= 5

    elif age <= 15:
        score -= 12

    elif age <= 30:
        score -= 6

    else:
        score += 5

    h1 = data["h1"]

    if h1 > 100:
        score += 15

    elif h1 > 50:
        score += 8

    elif h1 > 15:
        score -= 5

    elif h1 > 2:
        score -= 10

    m5 = data["m5"]

    if m5 > 20:
        score += 8

    elif m5 >= 5:
        score -= 8

    elif m5 >= 1:
        score -= 4

    smart = g.get("smart", 0)

    if smart >= 5:
        score -= 15

    elif smart >= 2:
        score -= 8

    elif smart == 1:
        score -= 3

    score = max(0, min(100, score))

    if score <= 35:
        emoji = "🟢"
        label = "SINAL VERDE"
        desc = "Baixo risco"

    elif score <= 65:
        emoji = "🟡"
        label = "SINAL AMARELO"
        desc = "Moderado"

    else:
        emoji = "🔴"
        label = "SINAL VERMELHO"
        desc = "Alto risco"

    preco_entrada = data["price"]

    custo_pct = 3.5

    saida_empate = preco_entrada * (1 + custo_pct / 100)

    if score <= 35:
        alvo1_pct = 30
        alvo2_pct = 80

    elif score <= 65:
        alvo1_pct = 20
        alvo2_pct = 50

    else:
        alvo1_pct = 15
        alvo2_pct = 35

    alvo1 = preco_entrada * (1 + alvo1_pct / 100)
    alvo2 = preco_entrada * (1 + alvo2_pct / 100)

    return {
        "score": score,
        "emoji": emoji,
        "label": label,
        "desc": desc,
        "greens": greens,
        "yellows": yellows,
        "reds": reds,
        "saida_empate": saida_empate,
        "alvo1": alvo1,
        "alvo1_pct": alvo1_pct,
        "alvo2": alvo2,
        "alvo2_pct": alvo2_pct,
        "custo_pct": custo_pct,
    }

# ============================================================
# FILTERS
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

def passes_filters(pair: dict):

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
    vol1h = pair.get("volume", {}).get("h1", 0) or 0

    tx = pair.get("txns", {}).get("m5", {})

    buys = tx.get("buys", 0)
    sells = tx.get("sells", 0)

    ratio = buys / max(sells, 1)

    pc = pair.get("priceChange", {})

    m5 = pc.get("m5", 0) or 0
    h1 = pc.get("h1", 0) or 0

    price = pair.get("priceUsd")

    created = pair.get("pairCreatedAt")

    age = ((time.time() * 1000 - created) / 60000) if created else 999

    if not price:
        return False, None

    if liq < MIN_LIQ or liq > MAX_LIQ:
        return False, None

    if buys < MIN_BUYS or buys > MAX_BUYS:
        return False, None

    if ratio < MIN_RATIO:
        return False, None

    if sells < MIN_SELLS:
        return False, None

    if buys >= 30 and sells > 0 and sells / buys < 0.05:
        return False, None

    if vol5m < MIN_VOL:
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
        "price": float(price),
        "liq": liq,
        "vol5m": vol5m,
        "vol1h": vol1h,
        "buys": buys,
        "sells": sells,
        "ratio": ratio,
        "m5": m5,
        "h1": h1,
        "age": age,
        "dex_id": pair.get("dexId", "dex"),
    }

# ============================================================
# FETCH
# ============================================================

def fetch_pairs(url):

    try:

        r = session.get(url, timeout=FETCH_TIMEOUT)

        if r.status_code != 200:
            return []

        try:
            data = r.json()
        except:
            return []

        return data.get("pairs") or []

    except:
        return []

# ============================================================
# SCANNER
# ============================================================

def scan_worker(worker_id):

    ep_index = worker_id

    while True:

        url = ENDPOINTS[ep_index % len(ENDPOINTS)]

        ep_index += 1

        for pair in fetch_pairs(url):

            ok, data = passes_filters(pair)

            if not ok:
                continue

            addr = data["addr"]

            g = fetch_gmgn_bonus(addr)

            is_rug, motivo = is_hard_rug(g)

            if is_rug:
                print(f"[RUG] {data['symbol']} {motivo}")
                continue

            mark_seen(addr)

            resultado = calcular_score_e_saida(data, g)

            with lock:

                monitored_tokens[addr] = {
                    "symbol": data["symbol"],
                    "price_entry": data["price"],
                    "time": datetime.utcnow().timestamp(),
                    "signal": resultado["label"],
                    "score": resultado["score"],
                }

                report_stats["sent"] += 1

                if "VERDE" in resultado["label"]:
                    report_stats["green"] += 1

                elif "AMAR" in resultado["label"]:
                    report_stats["yellow"] += 1

                else:
                    report_stats["red"] += 1

            symbol = escape_md(data["symbol"])

            gmgn_url = f"https://gmgn.ai/sol/token/{addr}"
            dex_url = f"https://dexscreener.com/solana/{addr}"

            msg = (
                f"{resultado['emoji']} *{escape_md(resultado['label'])}*\n\n"
                f"💎 *\\${symbol}*\n"
                f"`{escape_md(addr)}`\n\n"
                f"💲 `${data['price']:.10f}`\n"
                f"📈 `{data['m5']:+.1f}%` 5m\n"
                f"📈 `{data['h1']:+.1f}%` 1h\n"
                f"💧 `${data['liq']:,.0f}`\n"
                f"🔥 `{data['buys']}` buys\n"
                f"📊 Ratio `{data['ratio']:.1f}x`\n"
                f"⏰ `{data['age']:.0f} min`\n\n"
                f"🎯 Score `{resultado['score']}/100`\n\n"
                f"⚖️ `${resultado['saida_empate']:.10f}`\n"
                f"🎯 `${resultado['alvo1']:.10f}`\n"
                f"🚀 `${resultado['alvo2']:.10f}`\n\n"
                f"[GMGN]({gmgn_url}) | [DEX]({dex_url})"
            )

            send(msg)

        time.sleep(SCAN_DELAY)

# ============================================================
# CLEANUP TOKENS
# ============================================================

def cleanup_tokens():

    while True:

        try:

            now = time.time()

            with lock:

                remove = []

                for addr, info in monitored_tokens.items():

                    if now - info["time"] > 86400:
                        remove.append(addr)

                for addr in remove:
                    del monitored_tokens[addr]

        except Exception as e:
            print(f"[CLEANUP] {e}")

        time.sleep(3600)

# ============================================================
# REPORT
# ============================================================

def fetch_prices_batch(addrs):

    try:

        r = session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs)}",
            timeout=10
        )

        try:
            data = r.json()
        except:
            return {}

        return {
            p["baseToken"]["address"]: float(p["priceUsd"])
            for p in (data.get("pairs") or [])
            if p.get("baseToken", {}).get("address") and p.get("priceUsd")
        }

    except:
        return {}

def performance_report():

    time.sleep(REPORT_INTERVAL)

    while True:

        try:

            with lock:

                snap = dict(monitored_tokens)

                stats = dict(report_stats)

                report_stats.update({
                    "sent": 0,
                    "green": 0,
                    "yellow": 0,
                    "red": 0
                })

            if not snap:

                send("📊 *RELATÓRIO*\nNenhum token")

                time.sleep(REPORT_INTERVAL)

                continue

            addrs = list(snap.keys())

            batches = [addrs[i:i+30] for i in range(0, len(addrs), 30)]

            prices = {}

            with ThreadPoolExecutor(max_workers=4) as ex:

                futures = [
                    ex.submit(fetch_prices_batch, b)
                    for b in batches
                ]

                for f in as_completed(futures):
                    prices.update(f.result())

            winners = []
            losers = []

            for addr, info in snap.items():

                entry = info["price_entry"]

                current = prices.get(addr, 0)

                if current > 0 and entry > 0:

                    pct = ((current - entry) / entry) * 100

                    row = (pct, info["symbol"])

                    if pct >= 0:
                        winners.append(row)
                    else:
                        losers.append(row)

            winners.sort(reverse=True)

            losers.sort()

            total = len(winners) + len(losers)

            hit_rate = (len(winners) / total * 100) if total else 0

            report = (
                f"📊 *RELATÓRIO*\n\n"
                f"📤 `{stats['sent']}` alertas\n"
                f"🎯 `{hit_rate:.0f}%` acerto\n"
                f"🟢 `{len(winners)}`\n"
                f"🔴 `{len(losers)}`\n"
            )

            if winners:

                report += "\n🚀 *TOP WINNERS*\n"

                for pct, sym in winners[:10]:
                    report += f"`{pct:+.1f}%` \\${escape_md(sym)}\n"

            send(report)

        except Exception as e:
            print(f"[REPORT] {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH
# ============================================================

@app.route("/")
def health():

    with lock:

        return (
            f"WHALE SNIPER PRO | "
            f"Alertas: {len(monitored_tokens)} | "
            f"Fila: {alert_queue.qsize()} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("WHALE SNIPER PRO ONLINE")

    send(
        "🟢 *WHALE SNIPER PRO ONLINE*"
    )

    threading.Thread(
        target=telegram_sender,
        daemon=True
    ).start()

    threading.Thread(
        target=performance_report,
        daemon=True
    ).start()

    threading.Thread(
        target=cleanup_tokens,
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
