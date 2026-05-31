# ============================================================
# WHALE HUNTER v8.0 - GMGN + DexScreener
# ============================================================
# - Stealth buy + whale detection (mínimo 8 compras)
# - Smart money flexível (aceita 1+)
# - Holder growth como bônus, não obrigatório
# - Alerta de saída quando whales vendem
# - Relatório 2h completo
# ============================================================

import os
import time
import threading
import requests
import telebot
from flask import Flask
from queue import Queue, Empty
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")
bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)

# ============================================================
# FLASK
# ============================================================
app = Flask(__name__)

# ============================================================
# SESSION
# ============================================================
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.4,
                status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=150, pool_maxsize=150, max_retries=retries)
session.mount("https://", adapter)
session.mount("http://", adapter)

HEADERS = {"User-Agent": "Mozilla/5.0"}

# ============================================================
# CONFIGURAÇÕES (AJUSTADAS PARA MAIS ALERTAS)
# ============================================================
SCAN_DELAY = 0.3           # reduzido para evitar rate limit
REPORT_INTERVAL = 7200     # 2h

# Filtros de entrada (menos agressivos)
MIN_LIQ = 4000
MAX_LIQ = 120000           # aumenta limite superior
MIN_BUYS = 6               # mínimo de compras (antes 8)
MAX_BUYS = 500
MIN_RATIO = 2.0            # buys/sells (antes 2.5)
MIN_VOL5M = 600
MIN_AGE = 0.3
MAX_AGE = 60               # aumenta de 18 para 60 min
MIN_M5 = 1.5               # mínimo de alta em 5 min
MAX_M5 = 150
MAX_TOP10 = 35             # top10 ≤ 35% (antes 25)
MIN_SMART = 1              # aceita smart money = 1
MIN_WHALE_AVG_SIZE = 250   # tamanho médio da compra (USD) – mais baixo
MIN_HOLDER_GROWTH_PCT = 5  # crescimento de holders 5% em 5min (bônus)
ENABLE_HOLDER_REQUIREMENT = False  # holder growth não obrigatório

# ============================================================
# ENDPOINTS
# ============================================================
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
lock = threading.Lock()
history = {}              # tokens enviados (entrada)
exit_alerts = {}          # controle de alerta de saída por token
holder_snapshot = {}
stats = {"sent": 0, "green": 0, "yellow": 0}
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
                    bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                                     disable_web_page_preview=True)
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
# API GMGN (com cache simples)
# ============================================================
gmgn_cache = {}
def get_gmgn(addr):
    now = time.time()
    if addr in gmgn_cache and now - gmgn_cache[addr]["ts"] < 60:
        return gmgn_cache[addr]["data"]

    try:
        r = session.get(f"https://gmgn.ai/api/v1/token/sol/{addr}",
                        headers={"User-Agent": "Mozilla/5.0",
                                 "Referer": "https://gmgn.ai/"},
                        timeout=5)
        if r.status_code != 200:
            return {}
        d = r.json().get("data", {}) or {}
        result = {
            "smart": d.get("smart_degen_count", 0) or 0,
            "holders": d.get("holder_count", 0) or 0,
            "top10": d.get("top10_holder_rate", 0) or 0,
            "burn": d.get("burn_ratio", 0) or 0,
            "rug": d.get("rug_ratio", 0) or 0,
            "tax": d.get("sell_tax", 0) or 0,
            "honeypot": d.get("is_honeypot", False),
            "dev": d.get("creator_hold_percent", 0) or 0,
        }
        gmgn_cache[addr] = {"ts": now, "data": result}
        return result
    except:
        return {}

# ============================================================
# ANTI RUG (mais tolerante)
# ============================================================
def is_lixo(g):
    if g.get("honeypot") is True:
        return True, "HONEYPOT"
    if g.get("tax", 0) > 25:          # taxa de venda até 25% aceitável
        return True, f"SELL TAX {g['tax']}%"
    if g.get("rug", 0) > 0.8:
        return True, "RUG RATIO"
    dev = g.get("dev", 0)
    if dev and float(dev) > 15:       # dev até 15%
        return True, f"DEV HOLD {dev:.1f}%"
    top10 = g.get("top10", 0)
    if top10:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t > MAX_TOP10:
            return True, f"TOP10 {t:.0f}%"
    return False, ""

# ============================================================
# HOLDER GROWTH (opcional)
# ============================================================
def check_holder_growth(addr, current_holders, now_ts):
    if not ENABLE_HOLDER_REQUIREMENT:
        return True   # não bloqueia, só pontua depois
    with lock:
        snap = holder_snapshot.get(addr)
        if not snap:
            holder_snapshot[addr] = {"holders": current_holders, "ts": now_ts}
            return True
        age_min = (now_ts - snap["ts"]) / 60.0
        if age_min < 1:
            return True
        growth_pct = (current_holders - snap["holders"]) / max(snap["holders"], 1) * 100
        if age_min >= 5:
            holder_snapshot[addr] = {"holders": current_holders, "ts": now_ts}
        return growth_pct >= MIN_HOLDER_GROWTH_PCT

# ============================================================
# WHALE DETECTION (com tamanho médio ajustável)
# ============================================================
def has_whale_buys(vol5m, buys, liq):
    if buys < MIN_BUYS:
        return False
    avg_buy = vol5m / max(buys, 1)
    # Tamanho médio deve ser > 0.5% da liquidez ou > MIN_WHALE_AVG_SIZE
    min_relative = liq * 0.005
    return avg_buy >= max(MIN_WHALE_AVG_SIZE, min_relative)

# ============================================================
# SCORE (mais sensível)
# ============================================================
def score_token(data, g, avg_buy_size, holder_growth_ok):
    pontos = 0
    ratio = data["ratio"]
    buys = data["buys"]
    age = data["age"]
    m5 = data["m5"]
    accel = data["accel"]

    # Baleias
    if avg_buy_size >= 800: pontos += 6
    elif avg_buy_size >= 400: pontos += 4
    elif avg_buy_size >= 200: pontos += 2

    # Ratio
    if ratio >= 4: pontos += 5
    elif ratio >= 2.5: pontos += 4
    elif ratio >= 1.8: pontos += 2

    # Idade (quanto mais novo, melhor)
    if age <= 5: pontos += 5
    elif age <= 15: pontos += 3
    elif age <= 30: pontos += 1

    # Momentum
    if m5 >= 20: pontos += 4
    elif m5 >= 8: pontos += 2

    # Aceleração
    if accel >= 2.5: pontos += 4
    elif accel >= 1.5: pontos += 2

    # Smart money (agora pontua mesmo se =1)
    smart = g.get("smart", 0)
    if smart >= 4: pontos += 7
    elif smart >= 2: pontos += 4
    elif smart >= 1: pontos += 2

    # Holders (absoluto)
    holders = g.get("holders", 0)
    if holders >= 200: pontos += 4
    elif holders >= 80: pontos += 2
    elif holders >= 30: pontos += 1

    # Holder growth (bônus)
    if holder_growth_ok:
        pontos += 5

    # LP Burn
    burn = g.get("burn", 0)
    if burn:
        b = float(burn) * 100 if float(burn) <= 1 else float(burn)
        if b >= 70: pontos += 3
        elif b >= 50: pontos += 1

    # Top10 baixo
    top10 = g.get("top10", 0)
    if top10:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t <= 20: pontos += 5
        elif t <= 30: pontos += 2

    if pontos >= 22:
        return "🟢", "ELITE ENTRY", "Alta confiança - whales e smart money"
    elif pontos >= 15:
        return "🟡", "WHALE MOMENTUM", "Bom setup - monitorar saída"
    else:
        return "🔴", "RISCO", "Poucos sinais"

# ============================================================
# MONITORAMENTO DE SAÍDA (venda de whales)
# ============================================================
def check_exit(pair, addr, symbol, price_val):
    # Obtém dados atuais
    tx = pair.get("txns", {}).get("m5", {})
    buys = tx.get("buys", 0)
    sells = tx.get("sells", 0)
    if sells == 0:
        return False
    sell_ratio = sells / max(buys, 1)
    # Se sells ultrapassam 60% dos buys, sinal de venda forte
    if sell_ratio > 0.6:
        with lock:
            last_alert = exit_alerts.get(addr)
            now = time.time()
            if last_alert and now - last_alert < 1800:  # 30 min
                return False
            exit_alerts[addr] = now
        msg = (
            f"🔻 *SAÍDA DETECTADA* 🔻\n\n"
            f"Token: *${symbol}*\n"
            f"`{addr}`\n\n"
            f"⚠️ Vendas nos últimos 5min = {sells}\n"
            f"📊 Compras = {buys}\n"
            f"⚖️ Sell/Buy ratio = {sell_ratio:.2f}\n\n"
            f"🟢 Preço atual: `${price_val:.8f}`\n"
            f"📉 Sugestão: *realizar lucro* ou ajustar stop\n\n"
            f"🔍 GMGN: https://gmgn.ai/sol/token/{addr}"
        )
        send(msg)
        return True
    return False

# ============================================================
# PROCESSAMENTO PRINCIPAL
# ============================================================
def processar(pair):
    try:
        if pair.get("chainId") != "solana":
            return

        base = pair.get("baseToken", {})
        addr = base.get("address")
        if not addr:
            return

        price = pair.get("priceUsd")
        if not price:
            return
        price_val = float(price)

        liq = pair.get("liquidity", {}).get("usd", 0) or 0
        if liq < MIN_LIQ or liq > MAX_LIQ:
            return

        vol = pair.get("volume", {})
        vol5m = vol.get("m5", 0) or 0
        vol1h = vol.get("h1", 0) or 0
        if vol5m < MIN_VOL5M:
            return

        tx = pair.get("txns", {}).get("m5", {})
        buys = tx.get("buys", 0)
        sells = tx.get("sells", 0)

        # Se já temos alerta de entrada, verificar saída
        with lock:
            if addr in history:
                check_exit(pair, addr, base.get("symbol", "???"), price_val)
                return   # não reenvia entrada

        if buys < MIN_BUYS or buys > MAX_BUYS:
            return

        ratio = buys / max(sells, 1)
        if ratio < MIN_RATIO:
            return

        pc = pair.get("priceChange", {})
        m5 = pc.get("m5", 0) or 0
        h1 = pc.get("h1", 0) or 0
        if m5 < MIN_M5 or m5 > MAX_M5:
            return

        created = pair.get("pairCreatedAt")
        age = (time.time() * 1000 - created) / 60000 if created else 999
        if age < MIN_AGE or age > MAX_AGE:
            return

        accel = vol5m / max(vol1h / 12, 1) if vol1h > 0 else 0

        # Stealth buy (mais leve)
        if not (buys >= 6 and ratio >= 1.8 and accel >= 1.2 and age <= 25):
            return

        # Anti bot simples
        if sells > 0:
            sell_ratio = sells / max(buys, 1)
            if sell_ratio < 0.03 or sell_ratio > 0.75:
                return

        # Evita repetição
        with lock:
            old = history.get(addr)
            if old and time.time() - old["ts"] < 3600:
                return

        # GMGN + anti-rug
        g = get_gmgn(addr)
        lixo, motivo = is_lixo(g)
        if lixo:
            return

        # Smart money não bloqueia, mas se for zero, só passa se outros sinais forem fortes
        if g.get("smart", 0) < MIN_SMART and ratio < 3.0 and vol5m < 3000:
            return

        # Whale detection (baseado em liquidez)
        if not has_whale_buys(vol5m, buys, liq):
            return

        # Holder growth (opcional, não bloqueia)
        now_ts = time.time()
        holder_growth_ok = check_holder_growth(addr, g.get("holders", 0), now_ts)

        avg_buy_size = vol5m / max(buys, 1)
        emoji, label, desc = score_token({
            "ratio": ratio, "buys": buys, "age": age,
            "m5": m5, "h1": h1, "accel": accel
        }, g, avg_buy_size, holder_growth_ok)

        if "RISCO" in label:
            return

        symbol = base.get("symbol", "???")

        with lock:
            history[addr] = {"symbol": symbol, "price": price_val, "ts": now_ts}
            stats["sent"] += 1
            if "ELITE" in label:
                stats["green"] += 1
            else:
                stats["yellow"] += 1

        holders = g.get("holders", 0)
        top10 = g.get("top10", 0)
        top10_pct = (float(top10) * 100 if float(top10) <= 1 else float(top10)) if top10 else 0
        burn = g.get("burn", 0)
        burn_pct = (float(burn) * 100 if float(burn) <= 1 else float(burn)) if burn else 0

        tp1 = price_val * 1.8
        tp2 = price_val * 3.5
        tp3 = price_val * 7
        stop = price_val * 0.85

        forca = min(int(ratio * 1.8), 10)
        barra = "🟢" * forca + "⚪" * (10 - forca)

        msg = (
            f"{emoji} *{label}*\n"
            f"_{desc}_\n\n"
            f"💎 *${symbol}*\n"
            f"`{addr}`\n\n"
            f"💲 Entrada: `${price_val:.10f}`\n\n"
            f"💧 Liquidez: `${liq:,.0f}`\n"
            f"📊 Volume 5m: `${vol5m:,.0f}`\n"
            f"🐋 Tamanho médio: `${avg_buy_size:,.0f}`\n"
            f"🚀 Aceleração: `{accel:.1f}x`\n\n"
            f"🔥 Buys: `{buys}`  |  📉 Sells: `{sells}`\n"
            f"⚖️ Ratio: `{ratio:.2f}x`\n\n"
            f"📈 5m: `{m5:+.1f}%`  |  🚀 1h: `{h1:+.1f}%`\n"
            f"⏰ Age: `{age:.1f} min`\n\n"
            f"🧠 Smart: `{g.get('smart',0)}`  |  👥 Holders: `{holders}`\n"
            f"📈 Holder growth: `{'✅' if holder_growth_ok else '❌'}`\n"
            f"🏦 Top10: `{top10_pct:.0f}%`  |  🔒 LP Burn: `{burn_pct:.0f}%`\n\n"
            f"💪 FORÇA:\n{barra}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎯 TP1: `1.8x` (${tp1:.8f})\n"
            f"🚀 TP2: `3.5x` (${tp2:.8f})\n"
            f"🌕 TP3: `7x` (${tp3:.8f})\n"
            f"🛑 STOP: `-15%` (${stop:.8f})\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"🟢 GMGN: https://gmgn.ai/sol/token/{addr}\n"
            f"📊 DEX: https://dexscreener.com/solana/{addr}\n"
            f"⚡ TROJAN: https://t.me/solana_trojan_bot?start=r-user_{addr}"
        )
        send(msg)

    except Exception as e:
        print(f"[PROCESS] {e}")

# ============================================================
# SCANNER (menos threads)
# ============================================================
def scan():
    idx = 0
    while True:
        try:
            url = ENDPOINTS[idx % len(ENDPOINTS)]
            idx += 1
            r = session.get(url, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                for pair in pairs:
                    processar(pair)
        except Exception as e:
            print(f"[SCAN] {e}")
        time.sleep(SCAN_DELAY)

# ============================================================
# RELATÓRIO 2H
# ============================================================
def relatorio():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                st = dict(stats)
            txt = (
                f"📊 *RELATÓRIO 2H*\n\n"
                f"📤 Alertas enviados: `{st['sent']}`\n"
                f"🟢 Elite: `{st['green']}`  |  🟡 Whale: `{st['yellow']}`\n\n"
                f"🐋 Whale monitor (compras médias >0.5% liq)\n"
                f"🧠 Smart money >=1\n"
                f"⚡ Stealth buy detector\n"
                f"📈 Holder growth (bônus)\n"
                f"🚀 Ultra early (60 min)\n"
                f"🛡️ Anti rug ativo\n"
                f"🔻 Alerta de saída ativo"
            )
            send(txt)
        except Exception as e:
            print(f"[REL] {e}")
        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH
# ============================================================
@app.route("/")
def health():
    return (f"WHALE HUNTER v8.0 | tokens={len(history)} | "
            f"fila={tg_queue.qsize()} | 🟢{stats['green']} 🟡{stats['yellow']}")

# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    send("🟢 *WHALE HUNTER v8.0 ONLINE*\n\n"
         "🐋 Whale tracking (compras médias ajustáveis)\n"
         "🧠 Smart money flexível\n"
         "⚡ Stealth buy detector\n"
         "📈 Holder growth como bônus\n"
         "🚀 Ultra early até 60 min\n"
         "🛡️ Anti rug ativo\n"
         "🔻 Alerta de saída automático\n"
         "💰 Foco em lucro com entrada e saída")

    threading.Thread(target=tg_worker, daemon=True).start()
    threading.Thread(target=relatorio, daemon=True).start()

    # 10 threads para evitar rate limit
    for _ in range(10):
        threading.Thread(target=scan, daemon=True).start()
        time.sleep(0.1)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
