import os
import re
import time
import threading
import requests
import telebot

from flask import Flask
from datetime import datetime
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
# HTTP SESSION + RETRY
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

def escape_md(text):

    if text is None:
        return ""

    return re.sub(
        r'([_*\[\]()~`>#+\-=|{}.!])',
        r'\\\1',
        str(text)
    )

# ============================================================
# FILTROS
# ============================================================

MIN_LIQ = 5_000
MAX_LIQ = 500_000

MIN_BUYS = 4
MAX_BUYS = 1500

MIN_RATIO = 1.2
MIN_SELLS = 1

MIN_VOL = 250

MIN_AGE = 1
MAX_AGE = 90

MIN_M5 = -8.0
MAX_M5 = 80.0

MIN_H1 = -20.0
MAX_H1 = 400.0

# ============================================================
# PERFORMANCE
# ============================================================

SCAN_WORKERS = 6
FETCH_TIMEOUT = 4
REPORT_INTERVAL = 7200
MAX_SEEN = 30000

SCAN_DELAY = 0.7

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
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
]

# ============================================================
# GLOBAL STATE
# ============================================================

seen_tokens = deque(maxlen=MAX_SEEN)
seen_lookup = set()

monitored_tokens = {}

report_stats = {
    "sent": 0,
    "green": 0,
    "yellow": 0,
    "red": 0,
}

lock = threading.Lock()

alert_queue = Queue(maxsize=5000)

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
# TELEGRAM SENDER
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
# HARD RUG FILTER
# ============================================================

def is_hard_rug(g):

    if g.get("honeypot") is True:
        return True, "HONEYPOT"

    if g.get("rug", 0) > 0.9:
        return True, "RUG"

    if g.get("sell_tax", 0) > 20:
        return True, "SELL TAX"

    top10 = g.get("top10", 0)

    if top10 > 0:

        t = float(top10) * 100 if float(top10) <= 1 else float(top10)

        if t > 80:
            return True, "TOP10"

    return False, ""

# ============================================================
# SCORE
# ============================================================

def calcular_score_e_saida(data, g):

    score = 55

    greens = []
    yellows = []
    reds = []

    # ========================================================
    # LIQ
    # ========================================================

    liq = data["liq"]

    if liq >= 100000:
        score -= 10
        greens.append("💧 Liquidez muito forte")

    elif liq >= 30000:
        score -= 6
        greens.append("💧 Liquidez saudável")

    elif liq >= 10000:
        score -= 3

    # ========================================================
    # WHALE ENTRY
    # ========================================================

    if data.get("whale_entry"):

        score -= 18

        greens.append("🐋 Baleias entrando")

    # ========================================================
    # SMART MONEY
    # ========================================================

    smart = g.get("smart", 0)

    if smart >= 5:

        score -= 20

        greens.append(f"🧠 {smart} smart wallets")

    elif smart >= 3:

        score -= 14

        greens.append(f"🧠 {smart} smart wallets")

    elif smart >= 1:

        score -= 6

        greens.append("🧠 Smart money detectado")

    # ========================================================
    # VOLUME ACCELERATION
    # ========================================================

    if data["vol1h"] > 0:

        accel = data["vol5m"] / max(data["vol1h"] / 12, 1)

        if accel > 5:

            score -= 15

            greens.append("🔥 Volume explodindo")

        elif accel > 3:

            score -= 8

            greens.append("📈 Volume acelerando")

        elif accel < 0.5:

            score += 10

            reds.append("📉 Volume morrendo")

    # ========================================================
    # BUY PRESSURE
    # ========================================================

    ratio = data["ratio"]

    if ratio >= 6:

        score -= 15

        greens.append("🚀 Pressão compradora absurda")

    elif ratio >= 3:

        score -= 8

        greens.append("📈 Pressão compradora")

    # ========================================================
    # FDV
    # ========================================================

    fdv = data["fdv"]

    if fdv <= 200000:

        score -= 12

        greens.append("💎 Microcap")

    elif fdv <= 1000000:

        score -= 6

        greens.append("💎 Low cap")

    elif fdv >= 4000000:

        score += 8

        yellows.append("⚠️ MCAP alto")

    # ========================================================
    # AGE
    # ========================================================

    age = data["age"]

    if age <= 5:

        score -= 12

        greens.append("⚡ Ultra early")

    elif age <= 15:

        score -= 8

        greens.append("✨ Early")

    elif age >= 60:

        score += 10

        yellows.append("⌛ Movimento velho")

    # ========================================================
    # PUMP EXTREMO
    # ========================================================

    m5 = data["m5"]

    if m5 > 40:

        score += 18

        reds.append("🚨 Pump vertical")

    elif m5 > 20:

        score += 8

        yellows.append("⚠️ Pump forte")

    # ========================================================
    # HOLDERS
    # ========================================================

    holders = g.get("holders", 0)

    if holders >= 200:

        score -= 8

        greens.append("👥 Boa distribuição")

    elif holders >= 80:

        score -= 4

    # ========================================================
    # TOP10
    # ========================================================

    top10 = g.get("top10", 0)

    if top10 > 0:

        t = float(top10) * 100 if float(top10) <= 1 else float(top10)

        if t > 50:

            score += 15

            reds.append("🚨 Carteiras concentradas")

        elif t <= 25:

            score -= 8

            greens.append("✅ Distribuição saudável")

    # ========================================================
    # FINAL SCORE
    # ========================================================

    score = max(0, min(100, score))

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

    # ========================================================
    # TARGETS
    # ========================================================

    preco = data["price"]

    empate = preco * 1.035

    if score <= 25:

        alvo1 = preco * 1.40
        alvo2 = preco * 2.50

    elif score <= 40:

        alvo1 = preco * 1.30
        alvo2 = preco * 1.80

    elif score <= 65:

        alvo1 = preco * 1.20
        alvo2 = preco * 1.50

    else:

        alvo1 = preco * 1.10
        alvo2 = preco * 1.25

    return {
        "score": score,
        "emoji": emoji,
        "label": label,
        "greens": greens,
        "yellows": yellows,
        "reds": reds,
        "saida_empate": empate,
        "alvo1": alvo1,
        "alvo2": alvo2,
    }

# ============================================================
# SEEN TOKENS
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

    fdv = pair.get("fdv", 0) or 0

    created = pair.get("pairCreatedAt")

    age = ((time.time() * 1000 - created) / 60000) if created else 999

    if not price:
        return False, None

    if fdv > 5000000:
        return False, None

    if liq < MIN_LIQ or liq > MAX_LIQ:
        return False, None

    if buys < MIN_BUYS or buys > MAX_BUYS:
        return False, None

    if ratio < MIN_RATIO:
        return False, None

    if sells < MIN_SELLS:
        return False, None

    if vol5m < MIN_VOL:
        return False, None

    if age < MIN_AGE or age > MAX_AGE:
        return False, None

    if m5 < MIN_M5 or m5 > MAX_M5:
        return False, None

    if h1 < MIN_H1 or h1 > MAX_H1:
        return False, None

    # ========================================================
    # WHALE ENTRY
    # ========================================================

    whale_entry = False

    if (
        buys >= 8 and
        vol5m >= 1500 and
        ratio >= 1.5 and
        liq >= 10000
    ):
        whale_entry = True

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
        "fdv": fdv,
        "whale_entry": whale_entry,
    }

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

        try:
            data = r.json()
        except:
            return []

        return data.get("pairs") or []

    except:
        return []

# ============================================================
# SCAN WORKER
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
                    "time": time.time(),
                    "signal": resultado["label"],
                    "score": resultado["score"],
                }

                report_stats["sent"] += 1

                if "VERDE" in resultado["label"]:
                    report_stats["green"] += 1

                elif "AMARELO" in resultado["label"]:
                    report_stats["yellow"] += 1

                else:
                    report_stats["red"] += 1

            # ====================================================
            # LINKS
            # ====================================================

            gmgn_url = f"https://gmgn.ai/sol/token/{addr}"
            dex_url = f"https://dexscreener.com/solana/{addr}"
            pump_url = f"https://pump.fun/{addr}"
            photon_url = f"https://photon-sol.tinyastro.io/en/lp/{addr}"
            trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
            bullx_url = f"https://bullx.io/terminal?chainId=1399811149&address={addr}"

            # ====================================================
            # ANALYSIS
            # ====================================================

            analysis = ""

            for item in resultado["greens"][:5]:
                analysis += f"\n✅ {escape_md(item)}"

            for item in resultado["yellows"][:3]:
                analysis += f"\n⚠️ {escape_md(item)}"

            for item in resultado["reds"][:3]:
                analysis += f"\n🚨 {escape_md(item)}"

            # ====================================================
            # GMGN INFO
            # ====================================================

            gmgn_info = ""

            if g.get("smart", 0) > 0:
                gmgn_info += f"🧠 Smart Money: `{g['smart']}`\n"

            if g.get("holders", 0) > 0:
                gmgn_info += f"👥 Holders: `{g['holders']}`\n"

            if g.get("lp_burn", 0) > 0:

                lp = g["lp_burn"]

                lp_pct = float(lp) * 100 if float(lp) <= 1 else float(lp)

                gmgn_info += f"🔥 LP Burn: `{lp_pct:.0f}%`\n"

            # ====================================================
            # MESSAGE
            # ====================================================

            symbol = escape_md(data["symbol"])

            msg = (
                f"{resultado['emoji']} *{escape_md(resultado['label'])}*\n\n"

                f"💎 *\\${symbol}*\n"
                f"📄 `{escape_md(addr)}`\n\n"

                f"💲 Price: `${data['price']:.10f}`\n"
                f"💧 Liquidity: `${data['liq']:,.0f}`\n"
                f"💰 FDV: `${data['fdv']:,.0f}`\n"

                f"📈 5m: `{data['m5']:+.1f}%`\n"
                f"📈 1h: `{data['h1']:+.1f}%`\n"

                f"📊 Vol 5m: `${data['vol5m']:,.0f}`\n"

                f"🔥 Buys: `{data['buys']}`\n"
                f"🔻 Sells: `{data['sells']}`\n"

                f"⚖️ Ratio: `{data['ratio']:.1f}x`\n"

                f"⏰ Age: `{data['age']:.0f} min`\n"

                f"{'🐋 Whale Entry: `SIM`\n' if data.get('whale_entry') else ''}"

                f"{gmgn_info}\n"

                f"🎯 Score: `{resultado['score']}/100`\n"

                f"{analysis}\n\n"

                f"━━━━━━━━━━━━━━━\n"
                f"💰 *TARGETS*\n"
                f"━━━━━━━━━━━━━━━\n"

                f"⚖️ Breakeven: `${resultado['saida_empate']:.10f}`\n"
                f"🎯 Target 1: `${resultado['alvo1']:.10f}`\n"
                f"🚀 Target 2: `${resultado['alvo2']:.10f}`\n"

                f"🛑 Stop Loss: `-12%`\n\n"

                f"🔗 [GMGN]({gmgn_url})"
                f" | [DEX]({dex_url})"
                f" | [PHOTON]({photon_url})"
                f" | [BULLX]({bullx_url})"
                f" | [PUMP]({pump_url})\n"

                f"⚡ [TROJAN]({trojan_url})"
            )

            send(msg)

        time.sleep(SCAN_DELAY)

# ============================================================
# EXIT MONITOR
# ============================================================

def monitor_exit():

    time.sleep(120)

    while True:

        try:

            with lock:

                to_check = {
                    k: v for k, v in monitored_tokens.items()
                    if not v.get("exit_alerted")
                }

            if not to_check:

                time.sleep(120)

                continue

            addrs = list(to_check.keys())

            current = {}

            for i in range(0, len(addrs), 30):

                batch = ",".join(addrs[i:i+30])

                try:

                    r = session.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=8
                    )

                    try:
                        data = r.json()
                    except:
                        continue

                    for p in (data.get("pairs") or []):

                        a = p.get("baseToken", {}).get("address")

                        v = p.get("priceUsd")

                        s = p.get("txns", {}).get("m5", {}).get("sells", 0)

                        if a and v:

                            current[a] = {
                                "price": float(v),
                                "sells": s
                            }

                except:
                    pass

            for addr, info in to_check.items():

                d = current.get(addr)

                if not d:
                    continue

                pct = (
                    (
                        d["price"] - info["price_entry"]
                    ) / info["price_entry"]
                ) * 100

                sells = d["sells"]

                exit_msg = None

                # ====================================================
                # STOP LOSS
                # ====================================================

                if pct <= -12:

                    exit_msg = (
                        f"🚨 *STOP LOSS*\n\n"
                        f"💎 *\\${escape_md(info['symbol'])}*\n"
                        f"📉 `{pct:.1f}%`\n\n"
                        f"⚠️ Saída recomendada"
                    )

                # ====================================================
                # TAKE PROFIT
                # ====================================================

                elif pct >= 25:

                    exit_msg = (
                        f"🤑 *TAKE PROFIT*\n\n"
                        f"💎 *\\${escape_md(info['symbol'])}*\n"
                        f"📈 `+{pct:.1f}%`\n\n"
                        f"💰 Realize parcial"
                    )

                # ====================================================
                # DUMP DETECT
                # ====================================================

                elif sells > 40 and pct < -5:

                    exit_msg = (
                        f"⚠️ *DUMP DETECTADO*\n\n"
                        f"💎 *\\${escape_md(info['symbol'])}*\n"
                        f"📉 `{pct:.1f}%`\n"
                        f"🔻 `{sells}` sells"
                    )

                if exit_msg:

                    send(exit_msg)

                    with lock:

                        monitored_tokens[addr]["exit_alerted"] = True

        except Exception as e:

            print(f"[EXIT] {e}")

        time.sleep(120)

# ============================================================
# CLEANUP
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
            if p.get("baseToken", {}).get("address")
            and p.get("priceUsd")
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
                    "red": 0,
                })

            if not snap:

                send("📊 *RELATÓRIO*\nNenhum token encontrado")

                time.sleep(REPORT_INTERVAL)

                continue

            addrs = list(snap.keys())

            batches = [
                addrs[i:i+30]
                for i in range(0, len(addrs), 30)
            ]

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

                current = prices.get(addr)

                if not current:
                    continue

                entry = info["price_entry"]

                pct = ((current - entry) / entry) * 100

                row = (pct, info["symbol"])

                if pct >= 0:
                    winners.append(row)
                else:
                    losers.append(row)

            winners.sort(reverse=True)
            losers.sort()

            total = len(winners) + len(losers)

            hit_rate = (
                (len(winners) / total) * 100
            ) if total else 0

            report = (
                f"📊 *RELATÓRIO*\n\n"

                f"📤 Alertas: `{stats['sent']}`\n"

                f"🟢 `{len(winners)}` winners\n"
                f"🔴 `{len(losers)}` losers\n"

                f"🎯 Win Rate: `{hit_rate:.0f}%`\n"
            )

            if winners:

                report += "\n🚀 *TOP WINNERS*\n"

                for pct, sym in winners[:10]:

                    report += (
                        f"`{pct:+.1f}%` "
                        f"\\${escape_md(sym)}\n"
                    )

            send(report)

        except Exception as e:

            print(f"[REPORT] {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH CHECK
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
        "🚀 *WHALE SNIPER PRO ONLINE*\n\n"
        "🐋 Whale Entry Detection\n"
        "🧠 Smart Money Detection\n"
        "💎 Gem Scanner\n"
        "⚡ Solana Early Scanner"
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
