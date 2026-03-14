import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# CONFIGURAÇÃO — defina via variáveis de ambiente
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# FILTROS — CALIBRADOS PARA PEGAR MAIS SINAIS SEM PERDER QUALIDADE
# ============================================================
MIN_LIQUIDITY        = 3_000   # ↓ era 5.000  — pega tokens em formação
MIN_WHALE_BUYS       = 8       # ↓ era 10     — mantém filtro de baleia
MIN_VOLUME_M5        = 2_500   # ↓ era 5.000  — volume inicial de movimento
MIN_BUY_SELL_RATIO   = 1.8     # ↓ era 2.0    — força compradora clara
MAX_AGE_MINUTES      = 90      # ↑ era 60     — não perde tokens um pouco mais velhos
MIN_PRICE_CHANGE_H1  = 3.0     # ↓ era 5.0    — movimento positivo confirmado

# PROTEÇÃO ANTI-RUÍDO (filtros que PROTEGEM o seu dinheiro)
MAX_LIQUIDITY        = 500_000  # Ignora tokens gigantes já bombados
MIN_SELLS_5M         = 1        # Precisa ter pelo menos alguma venda (evita bots fake)
MAX_PRICE_CHANGE_H1  = 300.0    # Ignora tokens que já subiram 300%+ (tarde demais)

# ============================================================
# VELOCIDADE
# ============================================================
SCAN_WORKERS    = 4    # Threads paralelas de scan
REQUEST_TIMEOUT = 6    # Timeout por request (segundos)
REPORT_INTERVAL = 7_200
MAX_SEEN_TOKENS = 15_000

# Endpoints rotacionados para evitar rate limit e cobrir mais tokens
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "whales": 0, "accumulations": 0}
lock             = threading.Lock()

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# UTILITÁRIOS
# ============================================================

def send(msg: str):
    for attempt in range(3):
        try:
            bot.send_message(
                CHAT_ID, msg,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            return
        except Exception as e:
            print(f"[TELEGRAM] Tentativa {attempt+1}: {e}")
            time.sleep(0.5)


def pair_age_minutes(pair: dict) -> float:
    created_at = pair.get("pairCreatedAt")
    if not created_at:
        return 9999
    return (time.time() * 1000 - created_at) / 60_000


def classify_signal(buys5m: int, ratio: float, vol5m: float, liq: float) -> tuple:
    """Retorna (emoji, label, prioridade)"""
    if buys5m >= 25 and ratio >= 5 and vol5m >= 15_000:
        return "🚨", "MEGA BALEIA", 1
    if buys5m >= 15 and ratio >= 3 and liq >= 10_000:
        return "🐋", "BALEIA DETECTADA", 1
    if buys5m >= 8 and ratio >= 1.8:
        return "📈", "ACUMULAÇÃO FORTE", 2
    return "👀", "MONITORANDO", 3


def prune_cache():
    global seen_tokens
    if len(seen_tokens) > MAX_SEEN_TOKENS:
        seen_tokens = set(list(seen_tokens)[-(MAX_SEEN_TOKENS // 2):])


def fetch_pairs(url: str) -> list:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("pairs") or []
    except Exception as e:
        print(f"[FETCH] {url[-40:]} → {e}")
    return []


def process_pair(pair: dict):
    """Processa um par e retorna mensagem se passar nos filtros, senão None."""
    if pair.get("chainId") != "solana":
        return None

    base   = pair.get("baseToken", {})
    addr   = base.get("address")
    symbol = base.get("symbol", "???")

    if not addr:
        return None

    with lock:
        if addr in seen_tokens:
            return None

    liq       = pair.get("liquidity", {}).get("usd", 0) or 0
    vol5m     = pair.get("volume", {}).get("m5", 0)     or 0
    vol1h     = pair.get("volume", {}).get("h1", 0)     or 0
    buys5m    = pair.get("txns", {}).get("m5", {}).get("buys",  0)
    sells5m   = pair.get("txns", {}).get("m5", {}).get("sells", 0)
    price_usd = pair.get("priceUsd")
    change_h1 = pair.get("priceChange", {}).get("h1", 0) or 0
    change_m5 = pair.get("priceChange", {}).get("m5", 0) or 0
    age_min   = pair_age_minutes(pair)
    ratio     = buys5m / max(sells5m, 1)

    if not price_usd:
        return None

    price = float(price_usd)

    # ---- FILTROS DE ENTRADA ----
    if liq       < MIN_LIQUIDITY:        return None
    if liq       > MAX_LIQUIDITY:        return None  # já bombou, skip
    if buys5m    < MIN_WHALE_BUYS:       return None
    if vol5m     < MIN_VOLUME_M5:        return None
    if ratio     < MIN_BUY_SELL_RATIO:   return None
    if change_h1 < MIN_PRICE_CHANGE_H1:  return None
    if change_h1 > MAX_PRICE_CHANGE_H1:  return None  # tarde demais
    if age_min   > MAX_AGE_MINUTES:      return None
    if sells5m   < MIN_SELLS_5M:         return None  # suspeito = possível bot

    # ---- PASSOU — registra com lock ----
    with lock:
        if addr in seen_tokens:  # double-check
            return None
        seen_tokens.add(addr)

    emoji, label, priority = classify_signal(buys5m, ratio, vol5m, liq)

    with lock:
        monitored_tokens[addr] = {
            "symbol":      symbol,
            "price_entry": price,
            "time":        datetime.utcnow().strftime("%H:%M UTC"),
            "liq":         liq,
            "vol5m":       vol5m,
            "signal":      f"{emoji} {label}",
            "priority":    priority,
        }
        report_stats["sent"] += 1
        if priority == 1:
            report_stats["whales"] += 1
        else:
            report_stats["accumulations"] += 1

    gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
    dex_url    = f"https://dexscreener.com/solana/{addr}"
    trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
    pump_url   = f"https://pump.fun/{addr}"

    # Barra de força compradora visual
    strength = min(int(ratio), 10)
    bar = "🟢" * strength + "⚪" * (10 - strength)

    msg = (
        f"{emoji} *{label}*\n"
        f"💎 *${symbol}*  —  `{pair.get('dexId','dex').upper()}`\n\n"
        f"📄 *CA:* `{addr}`\n\n"
        f"💲 Preço:    `${price:.10f}`\n"
        f"📈 Var 5m:  `{change_m5:+.1f}%`  |  Var 1h: `{change_h1:+.1f}%`\n"
        f"💧 Liq:      `${liq:,.0f}`\n"
        f"📊 Vol 5m:  `${vol5m:,.0f}`  |  Vol 1h: `${vol1h:,.0f}`\n"
        f"🔥 Compras: `{buys5m}` | Vendas: `{sells5m}` | Ratio: `{ratio:.1f}x`\n"
        f"💪 Força:   {bar}\n"
        f"⏰ Idade:   `{age_min:.0f} min`\n\n"
        f"🔗 [GMGN]({gmgn_url})  |  [DEX]({dex_url})  |  [PUMP]({pump_url})\n"
        f"⚡ [COMPRAR NO TROJAN]({trojan_url})"
    )
    return msg

# ============================================================
# SCANNER PARALELO — 4 workers simultâneos
# ============================================================

def scan_worker(worker_id: int):
    print(f"[WORKER-{worker_id}] Iniciado")
    ep_index = worker_id  # cada worker começa num endpoint diferente
    while True:
        url = ENDPOINTS[ep_index % len(ENDPOINTS)]
        ep_index += 1
        prune_cache()

        pairs = fetch_pairs(url)
        for pair in pairs:
            msg = process_pair(pair)
            if msg:
                send(msg)

        time.sleep(0.5)  # pausa mínima por worker (anti-rate-limit)


def scan():
    print(f"🐋 WHALE SNIPER V5 — {SCAN_WORKERS} WORKERS PARALELOS")
    send(
        "🟢 *WHALE SNIPER V5 ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scanners paralelos\n"
        f"🔄 `{len(ENDPOINTS)}` endpoints rotacionados\n\n"
        f"🔍 *Filtros:*\n"
        f"  • Mínimo `{MIN_WHALE_BUYS}` compras/5min\n"
        f"  • Ratio ≥ `{MIN_BUY_SELL_RATIO:.1f}x` compras/vendas\n"
        f"  • Liq: `${MIN_LIQUIDITY:,}` → `${MAX_LIQUIDITY:,}`\n"
        f"  • Vol 5m ≥ `${MIN_VOLUME_M5:,}`\n"
        f"  • Var 1h: `+{MIN_PRICE_CHANGE_H1:.0f}%` → `+{MAX_PRICE_CHANGE_H1:.0f}%`\n"
        f"  • Idade ≤ `{MAX_AGE_MINUTES} min`\n"
        f"  • Precisa ter vendas reais *(anti-bot)*\n\n"
        "📢 Relatório automático a cada 2h."
    )

    threads = []
    for i in range(SCAN_WORKERS):
        t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.15)  # stagger de inicialização

    for t in threads:
        t.join()

# ============================================================
# RELATÓRIO DE PERFORMANCE (a cada 2 horas)
# ============================================================

def fetch_batch_prices(batch_addrs: list) -> dict:
    batch = ",".join(batch_addrs)
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
            timeout=10
        )
        result = {}
        for p in (r.json().get("pairs") or []):
            a = p.get("baseToken", {}).get("address")
            v = p.get("priceUsd")
            if a and v:
                result[a] = float(v)
        return result
    except:
        return {}


def performance_report():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                snapshot = dict(monitored_tokens)
                stats    = dict(report_stats)
                report_stats["sent"]          = 0
                report_stats["whales"]        = 0
                report_stats["accumulations"] = 0

            if not snapshot:
                send("📊 *RELATÓRIO 2H*\nNenhum token alertado no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs   = list(snapshot.keys())
            batches = [addrs[i:i+30] for i in range(0, len(addrs), 30)]

            current_prices = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                futures = [ex.submit(fetch_batch_prices, b) for b in batches]
                for f in as_completed(futures):
                    current_prices.update(f.result())

            winners, losers, no_data = [], [], []
            for addr, info in snapshot.items():
                entry   = info["price_entry"]
                current = current_prices.get(addr, 0)
                if current > 0 and entry > 0:
                    pct = ((current - entry) / entry) * 100
                    row = (pct, info["symbol"], entry, current, info.get("signal", ""))
                    (winners if pct >= 0 else losers).append(row)
                else:
                    no_data.append(info["symbol"])

            winners.sort(reverse=True)
            losers.sort()

            total_data = len(winners) + len(losers)
            hit_rate   = (len(winners) / total_data * 100) if total_data else 0

            now = datetime.utcnow().strftime("%d/%m %H:%M UTC")
            report = (
                f"📊 *RELATÓRIO — {now}*\n"
                f"{'─' * 28}\n"
                f"📤 Alertas: `{stats['sent']}` | "
                f"🐋 Baleias: `{stats['whales']}` | "
                f"📈 Acum: `{stats['accumulations']}`\n"
                f"🎯 Acerto: `{hit_rate:.0f}%` "
                f"(`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 28}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, entry, cur, sig in winners[:15]:
                    blocks = min(int(abs(pct) / 20), 8)
                    bar    = "█" * blocks
                    report += f"  `{pct:+6.1f}%` {bar} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, entry, cur, sig in losers[:8]:
                    report += f"  `{pct:+6.1f}%` *${sym}*\n"
                report += "\n"

            if no_data:
                syms = ", ".join(f"${s}" for s in no_data[:8])
                report += f"❓ *Sem dados:* {syms}\n"

            if winners:
                b = winners[0]
                report += f"\n🏆 *Melhor:* `${b[1]}` → `{b[0]:+.1f}%`"
            if losers:
                w = losers[0]
                report += f"\n💀 *Pior:*   `${w[1]}` → `{w[0]:+.1f}%`"

            send(report)

            # Limpa histórico antigo (mantém últimos 300)
            with lock:
                if len(monitored_tokens) > 300:
                    for k in list(monitored_tokens.keys())[:-300]:
                        del monitored_tokens[k]

        except Exception as e:
            print(f"[REPORT] Erro: {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/")
def health():
    with lock:
        return (
            f"WHALE SNIPER V5 | "
            f"Monitorados: {len(monitored_tokens)} | "
            f"Cache: {len(seen_tokens)} | "
            f"Workers: {SCAN_WORKERS}"
        )

# ============================================================
# ENTRADA
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
