import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue, Empty

# ============================================================
# CONFIGURAÇÃO
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# FILTROS
# ============================================================
MIN_LIQUIDITY         = 3_000
MAX_LIQUIDITY         = 500_000
MIN_WHALE_BUYS        = 8        # ← 8 compras de baleia confirmadas
MIN_VOLUME_M5         = 2_500
MIN_BUY_SELL_RATIO    = 1.8
MAX_AGE_MINUTES       = 90
MIN_PRICE_CHANGE_H1   = 3.0
MAX_PRICE_CHANGE_H1   = 300.0
MIN_SELLS_5M          = 1        # anti-bot

# ============================================================
# VELOCIDADE MÁXIMA
# ============================================================
SCAN_WORKERS      = 8      # 8 threads paralelas varrendo ao mesmo tempo
FETCH_TIMEOUT     = 4      # timeout agressivo — descarta lentos
ALERT_QUEUE_SIZE  = 200    # fila de alertas para envio assíncrono
MAX_SEEN_TOKENS   = 25_000
REPORT_INTERVAL   = 7_200

# 8 endpoints simultâneos — cada worker tem o seu
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
    "https://api.dexscreener.com/latest/dex/search?q=sol+trending",
    "https://api.dexscreener.com/latest/dex/search?q=solana+hot",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "green": 0, "yellow": 0, "red": 0}
lock             = threading.Lock()
alert_queue      = Queue(maxsize=ALERT_QUEUE_SIZE)  # fila assíncrona de envio

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# WORKER DE ENVIO TELEGRAM — thread dedicada exclusivamente
# para envio, não bloqueia o scan
# ============================================================

def telegram_sender():
    """Thread dedicada: consome a fila e envia pro Telegram."""
    while True:
        try:
            msg = alert_queue.get(timeout=5)
            for attempt in range(3):
                try:
                    bot.send_message(
                        CHAT_ID, msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=True
                    )
                    break
                except Exception as e:
                    print(f"[TG] tentativa {attempt+1}: {e}")
                    time.sleep(0.3)
        except Empty:
            continue
        except Exception as e:
            print(f"[TG-SENDER] {e}")


def send(msg: str):
    """Coloca na fila — retorno instantâneo, não bloqueia o scan."""
    try:
        alert_queue.put_nowait(msg)
    except Exception:
        pass  # fila cheia — descarta (preferível a travar o scan)

# ============================================================
# SCORE DE RISCO
# ============================================================

def calculate_risk_score(buys5m, sells5m, ratio, liq, vol5m,
                          vol1h, change_h1, change_m5, age_min) -> dict:
    score   = 0
    greens  = []
    yellows = []
    reds    = []

    # Liquidez
    if liq < 5_000:
        score += 25; reds.append("Liquidez muito baixa — fácil de manipular")
    elif liq < 15_000:
        score += 10; yellows.append("Liquidez moderada")
    elif liq >= 50_000:
        score -= 10; greens.append(f"Boa liquidez (${liq:,.0f})")
    else:
        greens.append(f"Liquidez razoável (${liq:,.0f})")

    # Ratio
    if ratio > 15:
        score += 20; reds.append(f"Ratio {ratio:.0f}x suspeito — possível pump artificial")
    elif ratio > 8:
        score += 8;  yellows.append(f"Ratio alto ({ratio:.1f}x) — monitorar")
    elif ratio >= 2:
        score -= 5;  greens.append(f"Pressão compradora saudável ({ratio:.1f}x)")
    else:
        greens.append(f"Ratio equilibrado ({ratio:.1f}x)")

    # Aceleração de volume
    if vol5m > 0 and vol1h > 0:
        accel = vol5m / max(vol1h / 12, 1)
        if accel > 5:
            score -= 10; greens.append(f"Volume acelerando forte ({accel:.1f}x média)")
        elif accel > 2:
            score -= 5;  greens.append(f"Volume acima da média ({accel:.1f}x)")
        elif accel < 0.5:
            score += 10; yellows.append("Volume desacelerando")

    # Idade do par
    if age_min < 5:
        score += 25; reds.append(f"Par com {age_min:.0f} min — risco máximo de rug")
    elif age_min < 15:
        score += 15; yellows.append(f"Par muito novo ({age_min:.0f} min)")
    elif age_min < 30:
        score += 5;  yellows.append(f"Par novo ({age_min:.0f} min)")
    else:
        score -= 5;  greens.append(f"Par com histórico ({age_min:.0f} min)")

    # Variação 1h
    if change_h1 > 150:
        score += 20; reds.append(f"Subiu +{change_h1:.0f}% em 1h — topo próximo?")
    elif change_h1 > 80:
        score += 10; yellows.append(f"Alta intensa +{change_h1:.0f}% em 1h")
    elif change_h1 > 20:
        score -= 5;  greens.append(f"Movimento saudável +{change_h1:.0f}% em 1h")
    else:
        greens.append(f"Início de movimento +{change_h1:.0f}% em 1h")

    # Pump 5min
    if change_m5 > 30:
        score += 15; reds.append(f"Pump de +{change_m5:.0f}% em 5min — dump pode vir")
    elif change_m5 > 15:
        score += 5;  yellows.append(f"Alta rápida +{change_m5:.0f}% em 5min")
    elif change_m5 > 0:
        score -= 3;  greens.append(f"Subindo +{change_m5:.0f}% em 5min")

    # Vendas reais
    if sells5m == 0:
        score += 20; reds.append("Zero vendas — possível bot/manipulação")
    elif sells5m < 3:
        score += 8;  yellows.append(f"Poucas vendas ({sells5m}) — monitorar")
    else:
        greens.append(f"Vendas reais confirmadas ({sells5m})")

    # Compras (reforço positivo)
    if buys5m >= 30:
        score -= 10; greens.append(f"Muitas compras ({buys5m} em 5min)")
    elif buys5m >= 15:
        score -= 5;  greens.append(f"Boas compras ({buys5m} em 5min)")
    elif buys5m >= 8:
        greens.append(f"8+ compras de baleia confirmadas ({buys5m} em 5min)")

    score = max(0, min(100, score))

    if score <= 30:
        return dict(score=score, emoji="🟢", label="SINAL VERDE",
                    desc="Bom potencial, risco controlado",
                    greens=greens, yellows=yellows, reds=reds)
    elif score <= 60:
        return dict(score=score, emoji="🟡", label="SINAL AMARELO",
                    desc="Potencial, mas exige atenção",
                    greens=greens, yellows=yellows, reds=reds)
    else:
        return dict(score=score, emoji="🔴", label="SINAL VERMELHO",
                    desc="Alto risco — só entre se souber o que faz",
                    greens=greens, yellows=yellows, reds=reds)


def classify_whale(buys5m, ratio, vol5m, liq):
    if buys5m >= 25 and ratio >= 5 and vol5m >= 15_000:
        return "🚨", "MEGA BALEIA"
    if buys5m >= 15 and ratio >= 3 and liq >= 10_000:
        return "🐋", "BALEIA DETECTADA"
    return "📈", "ACUMULAÇÃO FORTE"

# ============================================================
# UTILITÁRIOS
# ============================================================

def pair_age_minutes(pair: dict) -> float:
    c = pair.get("pairCreatedAt")
    if not c:
        return 9999
    return (time.time() * 1000 - c) / 60_000


def prune_cache():
    global seen_tokens
    if len(seen_tokens) > MAX_SEEN_TOKENS:
        seen_tokens = set(list(seen_tokens)[-(MAX_SEEN_TOKENS // 2):])


def fetch_pairs(url: str) -> list:
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("pairs") or []
    except:
        pass
    return []

# ============================================================
# PROCESSAMENTO DE PAR — ultra rápido
# ============================================================

def process_pair(pair: dict):
    if pair.get("chainId") != "solana":
        return

    base   = pair.get("baseToken", {})
    addr   = base.get("address")
    symbol = base.get("symbol", "???")
    if not addr:
        return

    # Check rápido sem lock (primeira barreira)
    if addr in seen_tokens:
        return

    # Extração de métricas em uma passagem
    liq       = pair.get("liquidity",   {}).get("usd", 0) or 0
    vol5m     = pair.get("volume",      {}).get("m5",  0) or 0
    vol1h     = pair.get("volume",      {}).get("h1",  0) or 0
    txns_m5   = pair.get("txns",        {}).get("m5",  {})
    buys5m    = txns_m5.get("buys",  0)
    sells5m   = txns_m5.get("sells", 0)
    price_usd = pair.get("priceUsd")
    pc        = pair.get("priceChange", {})
    change_h1 = pc.get("h1", 0) or 0
    change_m5 = pc.get("m5", 0) or 0
    age_min   = pair_age_minutes(pair)
    ratio     = buys5m / max(sells5m, 1)

    if not price_usd:
        return

    # ── FILTROS — ordem do mais rápido ao mais custoso ──
    if buys5m    < MIN_WHALE_BUYS:       return   # ← filtro baleia: 8 compras
    if liq        < MIN_LIQUIDITY:       return
    if liq        > MAX_LIQUIDITY:       return
    if vol5m      < MIN_VOLUME_M5:       return
    if ratio      < MIN_BUY_SELL_RATIO:  return
    if change_h1  < MIN_PRICE_CHANGE_H1: return
    if change_h1  > MAX_PRICE_CHANGE_H1: return
    if age_min    > MAX_AGE_MINUTES:     return
    if sells5m    < MIN_SELLS_5M:        return

    price = float(price_usd)

    # ── LOCK só aqui, depois de todos os filtros ──────────
    with lock:
        if addr in seen_tokens:
            return
        seen_tokens.add(addr)

    # ── SCORE E CLASSIFICAÇÃO ─────────────────────────────
    risk = calculate_risk_score(
        buys5m, sells5m, ratio, liq, vol5m,
        vol1h, change_h1, change_m5, age_min
    )
    whale_emoji, whale_label = classify_whale(buys5m, ratio, vol5m, liq)

    with lock:
        monitored_tokens[addr] = {
            "symbol":      symbol,
            "price_entry": price,
            "time":        datetime.utcnow().strftime("%H:%M UTC"),
            "liq":         liq,
            "vol5m":       vol5m,
            "signal":      risk["label"],
            "score":       risk["score"],
        }
        report_stats["sent"] += 1
        if "VERDE"  in risk["label"]: report_stats["green"]  += 1
        elif "AMAR" in risk["label"]: report_stats["yellow"] += 1
        else:                         report_stats["red"]    += 1

    # ── MONTA MENSAGEM ────────────────────────────────────
    gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
    dex_url    = f"https://dexscreener.com/solana/{addr}"
    trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
    pump_url   = f"https://pump.fun/{addr}"

    strength    = min(int(ratio), 10)
    bar_force   = "🟢" * strength + "⚪" * (10 - strength)

    risk_filled = min(int(risk["score"] / 10), 10)
    risk_icon   = {"🟢": "🟩", "🟡": "🟨", "🔴": "🟥"}[risk["emoji"]]
    bar_risk    = risk_icon * risk_filled + "⬜" * (10 - risk_filled)

    analysis = ""
    for g in risk["greens"][:2]:   analysis += f"\n✅ {g}"
    for y in risk["yellows"][:2]:  analysis += f"\n⚠️ {y}"
    for r in risk["reds"][:2]:     analysis += f"\n🚫 {r}"

    msg = (
        f"{risk['emoji']} *{risk['label']}* — {risk['desc']}\n"
        f"{whale_emoji} *{whale_label}* — `{buys5m}` compras confirmadas!\n\n"
        f"💎 *${symbol}*  —  `{pair.get('dexId','dex').upper()}`\n"
        f"📄 *CA:* `{addr}`\n\n"
        f"💲 Preço:    `${price:.10f}`\n"
        f"📈 Var 5m:  `{change_m5:+.1f}%`  |  Var 1h: `{change_h1:+.1f}%`\n"
        f"💧 Liq:      `${liq:,.0f}`\n"
        f"📊 Vol 5m:  `${vol5m:,.0f}`  |  Vol 1h: `${vol1h:,.0f}`\n"
        f"🔥 Compras: `{buys5m}` | Vendas: `{sells5m}` | Ratio: `{ratio:.1f}x`\n"
        f"⏰ Idade:   `{age_min:.0f} min`\n\n"
        f"💪 Força compradora:\n{bar_force}\n\n"
        f"🎯 Risco: `{risk['score']}/100`\n"
        f"{bar_risk}\n"
        f"{analysis}\n\n"
        f"🔗 [GMGN]({gmgn_url})  |  [DEX]({dex_url})  |  [PUMP]({pump_url})\n"
        f"⚡ [TROJAN — 0.01 SOL]({trojan_url})"
    )

    # ── ENVIA NA FILA — não bloqueia o scan ───────────────
    send(msg)

# ============================================================
# SCAN WORKERS — 8 threads, cada uma no seu endpoint
# ============================================================

def scan_worker(worker_id: int):
    ep_index = worker_id
    while True:
        url = ENDPOINTS[ep_index % len(ENDPOINTS)]
        ep_index += 1

        if worker_id == 0:
            prune_cache()  # só um worker limpa cache

        pairs = fetch_pairs(url)
        for pair in pairs:
            process_pair(pair)

        time.sleep(0.2)  # mínimo para não bater rate limit


def scan():
    print(f"🐋 WHALE SNIPER PRO — {SCAN_WORKERS} WORKERS | QUEUE ASSÍNCRONA")
    send(
        "🟢 *WHALE SNIPER PRO — ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scanners paralelos\n"
        f"🔄 `{len(ENDPOINTS)}` endpoints simultâneos\n"
        f"📨 Envio assíncrono — alerta em < 1 segundo\n\n"
        "🎯 *Sistema de Sinal de Risco:*\n"
        "  🟢 Verde  → Baixo risco, bom potencial\n"
        "  🟡 Amarelo → Risco moderado, atenção\n"
        "  🔴 Vermelho → Alto risco, só experts\n\n"
        f"🐋 *Filtro de baleia:* mínimo `{MIN_WHALE_BUYS}` compras/5min\n"
        f"📊 Ratio ≥ `{MIN_BUY_SELL_RATIO}x` | "
        f"Liq `${MIN_LIQUIDITY:,}` | "
        f"Vol5m `${MIN_VOLUME_M5:,}`\n\n"
        "🚨 Monitor de saída ativo (stop/take profit)\n"
        "📢 Relatório automático a cada 2h."
    )
    threads = []
    for i in range(SCAN_WORKERS):
        t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.05)
    for t in threads:
        t.join()

# ============================================================
# MONITOR DE SAÍDA — checa a cada 3 min
# ============================================================

def monitor_exit():
    time.sleep(180)
    while True:
        try:
            with lock:
                to_check = {
                    k: v for k, v in monitored_tokens.items()
                    if not v.get("exit_alerted")
                }
            if not to_check:
                time.sleep(180)
                continue

            addrs = list(to_check.keys())
            current = {}

            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                try:
                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=8
                    )
                    for p in (r.json().get("pairs") or []):
                        a = p.get("baseToken", {}).get("address")
                        v = p.get("priceUsd")
                        s = p.get("txns", {}).get("m5", {}).get("sells", 0)
                        if a and v:
                            current[a] = {"price": float(v), "sells": s}
                except:
                    pass

            for addr, info in to_check.items():
                d = current.get(addr)
                if not d:
                    continue
                entry = info["price_entry"]
                if entry <= 0:
                    continue
                pct   = ((d["price"] - entry) / entry) * 100
                sells = d["sells"]

                exit_msg = None
                if pct <= -20:
                    exit_msg = (
                        f"🚨 *STOP LOSS — SAIR AGORA*\n\n"
                        f"💎 *${info['symbol']}* caiu `{pct:.1f}%`\n"
                        f"📉 Entrada: `${entry:.10f}`\n"
                        f"📉 Atual:   `${d['price']:.10f}`\n"
                        f"⚠️ *Proteja seu capital — considere sair!*\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif pct >= 60:
                    exit_msg = (
                        f"🤑 *TAKE PROFIT — REALIZE LUCRO*\n\n"
                        f"💎 *${info['symbol']}* subiu `+{pct:.1f}%`\n"
                        f"📈 Entrada: `${entry:.10f}`\n"
                        f"📈 Atual:   `${d['price']:.10f}`\n"
                        f"💡 *Considere realizar lucro agora!*\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif sells > 50 and pct < 0:
                    exit_msg = (
                        f"⚠️ *DUMP DETECTADO*\n\n"
                        f"💎 *${info['symbol']}* — `{sells}` vendas em 5min\n"
                        f"📉 Variação: `{pct:+.1f}%` desde o alerta\n"
                        f"🔍 Baleias saindo? Monitore de perto!\n\n"
                        f"🔗 [VER NO DEX](https://dexscreener.com/solana/{addr})"
                    )

                if exit_msg:
                    send(exit_msg)
                    with lock:
                        if addr in monitored_tokens:
                            monitored_tokens[addr]["exit_alerted"] = True

        except Exception as e:
            print(f"[EXIT] {e}")

        time.sleep(180)

# ============================================================
# RELATÓRIO 2H
# ============================================================

def fetch_batch_prices(batch_addrs):
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{','.join(batch_addrs)}",
            timeout=10
        )
        return {
            p["baseToken"]["address"]: float(p["priceUsd"])
            for p in (r.json().get("pairs") or [])
            if p.get("baseToken", {}).get("address") and p.get("priceUsd")
        }
    except:
        return {}


def performance_report():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                snapshot = dict(monitored_tokens)
                stats    = dict(report_stats)
                report_stats.update({"sent": 0, "green": 0, "yellow": 0, "red": 0})

            if not snapshot:
                send("📊 *RELATÓRIO 2H*\nNenhum token alertado no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs   = list(snapshot.keys())
            batches = [addrs[i:i+30] for i in range(0, len(addrs), 30)]

            current_prices = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                for result in as_completed([ex.submit(fetch_batch_prices, b) for b in batches]):
                    current_prices.update(result.result())

            winners, losers, no_data = [], [], []
            for addr, info in snapshot.items():
                entry   = info["price_entry"]
                current = current_prices.get(addr, 0)
                if current > 0 and entry > 0:
                    pct = ((current - entry) / entry) * 100
                    row = (pct, info["symbol"], entry, current,
                           info.get("signal", ""), info.get("score", 50))
                    (winners if pct >= 0 else losers).append(row)
                else:
                    no_data.append(info["symbol"])

            winners.sort(reverse=True)
            losers.sort()

            total     = len(winners) + len(losers)
            hit_rate  = (len(winners) / total * 100) if total else 0
            now       = datetime.utcnow().strftime("%d/%m %H:%M UTC")

            report = (
                f"📊 *RELATÓRIO — {now}*\n"
                f"{'─' * 30}\n"
                f"📤 Alertas: `{stats['sent']}` | "
                f"🟢`{stats['green']}` 🟡`{stats['yellow']}` 🔴`{stats['red']}`\n"
                f"🎯 Acerto: `{hit_rate:.0f}%` "
                f"(`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 30}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, _, __, sig, score in winners[:15]:
                    icon   = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    blocks = "█" * min(int(abs(pct) / 20), 8)
                    report += f"  {icon} `{pct:+6.1f}%` {blocks} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, _, __, sig, score in losers[:8]:
                    icon = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    report += f"  {icon} `{pct:+6.1f}%` *${sym}*\n"
                report += "\n"

            # Acerto por sinal
            for label, key in [("🟢 Verdes", "VERDE"), ("🟡 Amarelos", "AMAR")]:
                w = sum(1 for x in winners if key in x[4])
                t = sum(1 for x in winners + losers if key in x[4])
                if t:
                    report += f"{label}: `{w}/{t}` (`{w/t*100:.0f}%` acerto)\n"

            if no_data:
                report += f"\n❓ Sem dados: {', '.join('$'+s for s in no_data[:6])}\n"
            if winners:
                b = winners[0]
                report += f"\n🏆 *Melhor:* `${b[1]}` → `{b[0]:+.1f}%`"
            if losers:
                w = losers[0]
                report += f"\n💀 *Pior:*   `${w[1]}` → `{w[0]:+.1f}%`"

            send(report)

            with lock:
                if len(monitored_tokens) > 300:
                    for k in list(monitored_tokens.keys())[:-300]:
                        del monitored_tokens[k]

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
            f"Tokens: {len(monitored_tokens)} | "
            f"Cache: {len(seen_tokens)} | "
            f"Fila: {alert_queue.qsize()} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # Thread dedicada de envio Telegram (não bloqueia scan)
    threading.Thread(target=telegram_sender,    daemon=True).start()
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
