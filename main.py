import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# CONFIGURAÇÃO
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# FILTROS DE ENTRADA
# ============================================================
MIN_LIQUIDITY       = 3_000
MIN_WHALE_BUYS      = 8
MIN_VOLUME_M5       = 2_500
MIN_BUY_SELL_RATIO  = 1.8
MAX_AGE_MINUTES     = 90
MIN_PRICE_CHANGE_H1 = 3.0
MAX_LIQUIDITY       = 500_000
MAX_PRICE_CHANGE_H1 = 300.0
MIN_SELLS_5M        = 1

# ============================================================
# VELOCIDADE
# ============================================================
SCAN_WORKERS    = 6
REQUEST_TIMEOUT = 5
REPORT_INTERVAL = 7_200
MAX_SEEN_TOKENS = 20_000

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "green": 0, "yellow": 0, "red": 0}
lock             = threading.Lock()

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# SISTEMA DE SCORE DE RISCO
# ============================================================

def calculate_risk_score(pair: dict, buys5m: int, sells5m: int, ratio: float,
                          liq: float, vol5m: float, vol1h: float,
                          change_h1: float, change_m5: float, age_min: float) -> dict:
    """
    Calcula score de risco de 0 a 100.
    Quanto MAIOR o score, MAIOR o risco.
    Retorna dict com score, sinal, pontos positivos e alertas.
    """
    score   = 0
    greens  = []   # pontos positivos
    yellows = []   # alertas moderados
    reds    = []   # alertas críticos

    # ── LIQUIDEZ ──────────────────────────────────────────
    if liq < 5_000:
        score += 25
        reds.append("Liquidez muito baixa — fácil de manipular")
    elif liq < 15_000:
        score += 10
        yellows.append("Liquidez moderada")
    elif liq >= 50_000:
        score -= 10
        greens.append(f"Boa liquidez (${liq:,.0f})")
    else:
        greens.append(f"Liquidez razoável (${liq:,.0f})")

    # ── RATIO COMPRAS/VENDAS ──────────────────────────────
    if ratio > 15:
        score += 20
        reds.append(f"Ratio {ratio:.0f}x suspeito — possível manipulação")
    elif ratio > 8:
        score += 8
        yellows.append(f"Ratio alto ({ratio:.1f}x) — monitorar")
    elif ratio >= 2:
        score -= 5
        greens.append(f"Pressão compradora saudável ({ratio:.1f}x)")
    else:
        greens.append(f"Ratio equilibrado ({ratio:.1f}x)")

    # ── VOLUME ────────────────────────────────────────────
    if vol5m > 0 and vol1h > 0:
        vol_accel = vol5m / (vol1h / 12)  # compara vol5m com média dos últimos 5min da hora
        if vol_accel > 5:
            score -= 10
            greens.append(f"Volume acelerando forte ({vol_accel:.1f}x média)")
        elif vol_accel > 2:
            score -= 5
            greens.append(f"Volume acima da média ({vol_accel:.1f}x)")
        elif vol_accel < 0.5:
            score += 10
            yellows.append("Volume desacelerando")

    # ── IDADE DO PAR ─────────────────────────────────────
    if age_min < 5:
        score += 20
        reds.append(f"Par com apenas {age_min:.0f} min — altíssimo risco de rug")
    elif age_min < 15:
        score += 12
        yellows.append(f"Par muito novo ({age_min:.0f} min)")
    elif age_min < 30:
        score += 5
        yellows.append(f"Par novo ({age_min:.0f} min)")
    else:
        score -= 5
        greens.append(f"Par com algum histórico ({age_min:.0f} min)")

    # ── VARIAÇÃO DE PREÇO ────────────────────────────────
    if change_h1 > 150:
        score += 20
        reds.append(f"Subiu +{change_h1:.0f}% em 1h — topo próximo?")
    elif change_h1 > 80:
        score += 10
        yellows.append(f"Alta intensa +{change_h1:.0f}% em 1h")
    elif change_h1 > 20:
        score -= 5
        greens.append(f"Movimento saudável +{change_h1:.0f}% em 1h")
    else:
        greens.append(f"Início de movimento +{change_h1:.0f}% em 1h")

    if change_m5 > 30:
        score += 15
        reds.append(f"Pump de +{change_m5:.0f}% em 5min — cuidado com dump")
    elif change_m5 > 15:
        score += 5
        yellows.append(f"Alta rápida +{change_m5:.0f}% em 5min")
    elif change_m5 > 0:
        score -= 3
        greens.append(f"Subindo +{change_m5:.0f}% em 5min")

    # ── SELLS SUSPEITOS ──────────────────────────────────
    if sells5m == 0:
        score += 20
        reds.append("Zero vendas — possível bot/manipulação")
    elif sells5m < 3:
        score += 8
        yellows.append(f"Poucas vendas ({sells5m}) — monitorar")
    else:
        greens.append(f"Vendas reais confirmadas ({sells5m})")

    # ── NÚMERO DE COMPRAS ────────────────────────────────
    if buys5m >= 30:
        score -= 10
        greens.append(f"Muitas compras ({buys5m} em 5min)")
    elif buys5m >= 15:
        score -= 5
        greens.append(f"Boas compras ({buys5m} em 5min)")
    elif buys5m >= 8:
        greens.append(f"Compras detectadas ({buys5m} em 5min)")

    # ── NORMALIZA SCORE ──────────────────────────────────
    score = max(0, min(100, score))

    # ── DEFINE SINAL ─────────────────────────────────────
    if score <= 30:
        signal_emoji = "🟢"
        signal_label = "SINAL VERDE"
        signal_desc  = "Bom potencial, risco controlado"
    elif score <= 60:
        signal_emoji = "🟡"
        signal_label = "SINAL AMARELO"
        signal_desc  = "Potencial, mas exige atenção"
    else:
        signal_emoji = "🔴"
        signal_label = "SINAL VERMELHO"
        signal_desc  = "Alto risco — só entre se souber o que faz"

    return {
        "score":        score,
        "signal_emoji": signal_emoji,
        "signal_label": signal_label,
        "signal_desc":  signal_desc,
        "greens":       greens,
        "yellows":      yellows,
        "reds":         reds,
    }


def classify_whale(buys5m: int, ratio: float, vol5m: float, liq: float) -> tuple:
    if buys5m >= 25 and ratio >= 5 and vol5m >= 15_000:
        return "🚨", "MEGA BALEIA"
    if buys5m >= 15 and ratio >= 3 and liq >= 10_000:
        return "🐋", "BALEIA DETECTADA"
    return "📈", "ACUMULAÇÃO FORTE"

# ============================================================
# UTILITÁRIOS
# ============================================================

def send(msg: str):
    for attempt in range(3):
        try:
            bot.send_message(CHAT_ID, msg,
                             parse_mode="Markdown",
                             disable_web_page_preview=True)
            return
        except Exception as e:
            print(f"[TG] {attempt+1}: {e}")
            time.sleep(0.4)


def pair_age_minutes(pair: dict) -> float:
    created_at = pair.get("pairCreatedAt")
    if not created_at:
        return 9999
    return (time.time() * 1000 - created_at) / 60_000


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
        print(f"[FETCH] {e}")
    return []

# ============================================================
# PROCESSAMENTO DE PAR
# ============================================================

def process_pair(pair: dict):
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

    # ── FILTROS DE ENTRADA ────────────────────────────────
    if liq        < MIN_LIQUIDITY:       return None
    if liq        > MAX_LIQUIDITY:       return None
    if buys5m     < MIN_WHALE_BUYS:      return None
    if vol5m      < MIN_VOLUME_M5:       return None
    if ratio      < MIN_BUY_SELL_RATIO:  return None
    if change_h1  < MIN_PRICE_CHANGE_H1: return None
    if change_h1  > MAX_PRICE_CHANGE_H1: return None
    if age_min    > MAX_AGE_MINUTES:     return None
    if sells5m    < MIN_SELLS_5M:        return None

    # ── DOUBLE-CHECK COM LOCK ─────────────────────────────
    with lock:
        if addr in seen_tokens:
            return None
        seen_tokens.add(addr)

    # ── SCORE DE RISCO ────────────────────────────────────
    risk = calculate_risk_score(
        pair, buys5m, sells5m, ratio,
        liq, vol5m, vol1h,
        change_h1, change_m5, age_min
    )

    whale_emoji, whale_label = classify_whale(buys5m, ratio, vol5m, liq)

    with lock:
        monitored_tokens[addr] = {
            "symbol":      symbol,
            "price_entry": price,
            "time":        datetime.utcnow().strftime("%H:%M UTC"),
            "liq":         liq,
            "vol5m":       vol5m,
            "signal":      risk["signal_label"],
            "score":       risk["score"],
        }
        report_stats["sent"] += 1
        sl = risk["signal_label"]
        if "VERDE"   in sl: report_stats["green"]  += 1
        elif "AMAR"  in sl: report_stats["yellow"] += 1
        else:               report_stats["red"]    += 1

    # ── LINKS ─────────────────────────────────────────────
    gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
    dex_url    = f"https://dexscreener.com/solana/{addr}"
    trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
    pump_url   = f"https://pump.fun/{addr}"

    # ── BARRA DE FORÇA ────────────────────────────────────
    strength = min(int(ratio), 10)
    bar = "🟢" * strength + "⚪" * (10 - strength)

    # ── BARRA DE RISCO ────────────────────────────────────
    risk_filled = min(int(risk["score"] / 10), 10)
    if risk["score"] <= 30:
        risk_bar = "🟩" * risk_filled + "⬜" * (10 - risk_filled)
    elif risk["score"] <= 60:
        risk_bar = "🟨" * risk_filled + "⬜" * (10 - risk_filled)
    else:
        risk_bar = "🟥" * risk_filled + "⬜" * (10 - risk_filled)

    # ── PONTOS DE ANÁLISE ─────────────────────────────────
    analysis = ""
    if risk["greens"]:
        analysis += "\n✅ " + "\n✅ ".join(risk["greens"][:3])
    if risk["yellows"]:
        analysis += "\n⚠️ " + "\n⚠️ ".join(risk["yellows"][:2])
    if risk["reds"]:
        analysis += "\n🚫 " + "\n🚫 ".join(risk["reds"][:2])

    msg = (
        f"{risk['signal_emoji']} *{risk['signal_label']}* — {risk['signal_desc']}\n"
        f"{whale_emoji} *{whale_label}* detectada!\n\n"
        f"💎 *${symbol}*  —  `{pair.get('dexId','dex').upper()}`\n"
        f"📄 *CA:* `{addr}`\n\n"
        f"💲 Preço:    `${price:.10f}`\n"
        f"📈 Var 5m:  `{change_m5:+.1f}%`  |  Var 1h: `{change_h1:+.1f}%`\n"
        f"💧 Liq:      `${liq:,.0f}`\n"
        f"📊 Vol 5m:  `${vol5m:,.0f}`  |  Vol 1h: `${vol1h:,.0f}`\n"
        f"🔥 Compras: `{buys5m}` | Vendas: `{sells5m}` | Ratio: `{ratio:.1f}x`\n"
        f"⏰ Idade:   `{age_min:.0f} min`\n\n"
        f"💪 Força compradora:\n{bar}\n\n"
        f"🎯 Score de risco: `{risk['score']}/100`\n"
        f"{risk_bar}\n"
        f"{analysis}\n\n"
        f"🔗 [GMGN]({gmgn_url})  |  [DEX]({dex_url})  |  [PUMP]({pump_url})\n"
        f"⚡ [ABRIR NO TROJAN — 0.01 SOL]({trojan_url})"
    )
    return msg

# ============================================================
# SCANNER PARALELO — 6 WORKERS
# ============================================================

def scan_worker(worker_id: int):
    print(f"[W{worker_id}] Iniciado")
    ep_index = worker_id
    while True:
        url = ENDPOINTS[ep_index % len(ENDPOINTS)]
        ep_index += 1
        prune_cache()
        for pair in fetch_pairs(url):
            msg = process_pair(pair)
            if msg:
                send(msg)
        time.sleep(0.3)


def scan():
    print(f"🐋 WHALE SNIPER PRO — {SCAN_WORKERS} WORKERS")
    send(
        "🟢 *WHALE SNIPER PRO ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scanners paralelos\n"
        f"🔄 `{len(ENDPOINTS)}` endpoints simultâneos\n\n"
        "🎯 *Sistema de Sinal de Risco ativo:*\n"
        "  🟢 Verde  → Baixo risco, bom potencial\n"
        "  🟡 Amarelo → Risco moderado, atenção\n"
        "  🔴 Vermelho → Alto risco, cuidado\n\n"
        f"🔍 *Filtros:* min `{MIN_WHALE_BUYS}` compras | "
        f"ratio `{MIN_BUY_SELL_RATIO}x` | liq `${MIN_LIQUIDITY:,}` | "
        f"vol5m `${MIN_VOLUME_M5:,}` | var1h `+{MIN_PRICE_CHANGE_H1:.0f}%`\n\n"
        "📢 Relatório automático a cada 2h.\n"
        "💡 *Dica:* Prefira tokens 🟢 ou 🟡 com baleias confirmadas!"
    )
    threads = []
    for i in range(SCAN_WORKERS):
        t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.1)
    for t in threads:
        t.join()

# ============================================================
# MONITORAMENTO PÓS-ALERTA (detecção de dump)
# ============================================================

def monitor_exit():
    """
    A cada 3 minutos verifica os tokens alertados.
    Se cair -15% do preço de entrada → avisa pra sair.
    Se subir +40% → avisa pra realizar lucro.
    """
    time.sleep(180)
    while True:
        try:
            with lock:
                tokens_to_check = {
                    k: v for k, v in monitored_tokens.items()
                    if not v.get("exit_alerted")
                }

            if not tokens_to_check:
                time.sleep(180)
                continue

            addrs = list(tokens_to_check.keys())
            current_prices = {}

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
                        bv = p.get("txns", {}).get("m5", {}).get("sells", 0)
                        if a and v:
                            current_prices[a] = {
                                "price": float(v),
                                "sells": bv,
                            }
                except:
                    pass

            for addr, info in tokens_to_check.items():
                data  = current_prices.get(addr)
                if not data:
                    continue

                entry   = info["price_entry"]
                current = data["price"]
                sells   = data["sells"]
                if entry <= 0:
                    continue

                pct = ((current - entry) / entry) * 100

                # ── ALERTA DE SAÍDA ────────────────────────
                exit_msg = None

                if pct <= -20:
                    exit_msg = (
                        f"🚨 *ALERTA DE SAÍDA — STOP LOSS*\n\n"
                        f"💎 *${info['symbol']}* caiu `{pct:.1f}%` desde o alerta\n"
                        f"📉 Entrada: `${entry:.10f}` → Atual: `${current:.10f}`\n"
                        f"⚠️ *Considere sair agora para proteger capital!*\n\n"
                        f"🔗 [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif pct >= 60:
                    exit_msg = (
                        f"🤑 *ALERTA DE LUCRO — TAKE PROFIT*\n\n"
                        f"💎 *${info['symbol']}* subiu `+{pct:.1f}%` desde o alerta\n"
                        f"📈 Entrada: `${entry:.10f}` → Atual: `${current:.10f}`\n"
                        f"💡 *Considere realizar parte do lucro agora!*\n\n"
                        f"🔗 [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif sells > 50 and pct < 0:
                    exit_msg = (
                        f"⚠️ *ATENÇÃO — DUMP DETECTADO*\n\n"
                        f"💎 *${info['symbol']}* com `{sells}` vendas em 5min\n"
                        f"📉 Variação atual: `{pct:+.1f}%` desde o alerta\n"
                        f"🔍 Monitore de perto — possível saída de baleias\n\n"
                        f"🔗 [VERIFICAR NO DEX](https://dexscreener.com/solana/{addr})"
                    )

                if exit_msg:
                    send(exit_msg)
                    with lock:
                        if addr in monitored_tokens:
                            monitored_tokens[addr]["exit_alerted"] = True

        except Exception as e:
            print(f"[EXIT] Erro: {e}")

        time.sleep(180)  # checa a cada 3 minutos

# ============================================================
# RELATÓRIO DE PERFORMANCE (2 HORAS)
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
                report_stats["sent"]   = 0
                report_stats["green"]  = 0
                report_stats["yellow"] = 0
                report_stats["red"]    = 0

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
                    row = (pct, info["symbol"], entry, current,
                           info.get("signal",""), info.get("score", 50))
                    (winners if pct >= 0 else losers).append(row)
                else:
                    no_data.append(info["symbol"])

            winners.sort(reverse=True)
            losers.sort()

            total_data = len(winners) + len(losers)
            hit_rate   = (len(winners) / total_data * 100) if total_data else 0

            now = datetime.utcnow().strftime("%d/%m %H:%M UTC")
            report = (
                f"📊 *RELATÓRIO DE PERFORMANCE — {now}*\n"
                f"{'─' * 30}\n"
                f"📤 Alertas: `{stats['sent']}`\n"
                f"🟢 Verdes: `{stats['green']}` | "
                f"🟡 Amarelos: `{stats['yellow']}` | "
                f"🔴 Vermelhos: `{stats['red']}`\n"
                f"🎯 Taxa de acerto: `{hit_rate:.0f}%` "
                f"(`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 30}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, entry, cur, sig, score in winners[:15]:
                    s_icon = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    blocks = min(int(abs(pct) / 20), 8)
                    bar    = "█" * blocks
                    report += f"  {s_icon} `{pct:+6.1f}%` {bar} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, entry, cur, sig, score in losers[:8]:
                    s_icon = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    report += f"  {s_icon} `{pct:+6.1f}%` *${sym}*\n"
                report += "\n"

            # Aprendizado: acerto por cor de sinal
            green_wins  = sum(1 for w in winners if "VERDE" in w[4])
            green_total = sum(1 for x in winners+losers if "VERDE" in x[4])
            if green_total:
                report += f"🟢 Acerto dos VERDES: `{green_wins}/{green_total}` (`{green_wins/green_total*100:.0f}%`)\n"

            yellow_wins  = sum(1 for w in winners if "AMAR" in w[4])
            yellow_total = sum(1 for x in winners+losers if "AMAR" in x[4])
            if yellow_total:
                report += f"🟡 Acerto dos AMARELOS: `{yellow_wins}/{yellow_total}` (`{yellow_wins/yellow_total*100:.0f}%`)\n"

            if no_data:
                syms = ", ".join(f"${s}" for s in no_data[:6])
                report += f"\n❓ *Sem dados:* {syms}\n"

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
            print(f"[REPORT] Erro: {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/")
def health():
    with lock:
        g = report_stats["green"]
        y = report_stats["yellow"]
        r = report_stats["red"]
        return (
            f"WHALE SNIPER PRO | "
            f"Tokens: {len(monitored_tokens)} | "
            f"Cache: {len(seen_tokens)} | "
            f"🟢{g} 🟡{y} 🔴{r}"
        )

# ============================================================
# ENTRADA
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
