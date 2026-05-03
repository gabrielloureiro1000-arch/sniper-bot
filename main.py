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
# FILTROS — MELHOR DOS DOIS CÓDIGOS
# Filosofia: entrar cedo, com smart money, sem lixo
# ============================================================

# ── LIQUIDEZ — zona de MC baixo com segurança ────────────
MIN_LIQ   = 30_000   # mínimo seguro (do código institucional)
MAX_LIQ   = 200_000  # acima = MC alto demais, upside menor

# ── BALEIAS / SMART MONEY ────────────────────────────────
MIN_BUYS  = 18       # 18 compras = entrada institucional confirmada
MIN_RATIO = 2.5      # força compradora real (2.5x compras vs vendas)
MIN_SELLS = 5        # mínimo de vendas = mercado bilateral real

# ── VOLUME ───────────────────────────────────────────────
MIN_VOL   = 2_500    # volume mínimo em 5min = interesse real

# ── IDADE — janela cirúrgica ─────────────────────────────
MIN_AGE   = 4        # mínimo 4 min (evita rug imediato)
MAX_AGE   = 35       # máximo 35 min (depois disso já foi)

# ── VARIAÇÃO DE PREÇO — movimento real sem pump violento ─
MIN_M5    = 4.0      # mínimo +4% em 5min = movimento iniciando
MAX_M5    = 18.0     # máximo 18% em 5min = pump não violento
MIN_H1    = 10.0     # mínimo +10% em 1h = tendência confirmada
MAX_H1    = 120.0    # máximo 120% em 1h = ainda tem espaço

# ── ON-CHAIN — proteção contra rug (nosso diferencial) ───
MIN_SMART    = 2     # mínimo 2 smart money wallets
MIN_HOLDERS  = 80    # mínimo 80 holders reais
MAX_TOP10    = 0.40  # top 10 wallets < 40% do supply

# ── ANTI-FAKE / ANTI-BOT ─────────────────────────────────
MAX_BUYS     = 800   # acima = bot
MIN_SEL_RATE = 0.20  # sells deve ser >= 20% das compras

# ============================================================
# VELOCIDADE
# ============================================================
SCAN_WORKERS    = 10
ONCHAIN_WORKERS = 8
FETCH_TIMEOUT   = 3
GMGN_TIMEOUT    = 5
REPORT_INTERVAL = 7_200
MAX_SEEN        = 30_000

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+hot",
    "https://api.dexscreener.com/latest/dex/search?q=sol+trending",
    "https://api.dexscreener.com/latest/dex/search?q=sol+launch",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "blocked": 0, "green": 0, "yellow": 0, "red": 0}
lock             = threading.Lock()
onchain_queue    = Queue(maxsize=500)
alert_queue      = Queue(maxsize=1000)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# ESTÁGIO 3 — ENVIO TELEGRAM (thread dedicada)
# ============================================================

def telegram_sender():
    while True:
        try:
            msg = alert_queue.get(timeout=5)
            for attempt in range(3):
                try:
                    bot.send_message(CHAT_ID, msg,
                                     parse_mode="Markdown",
                                     disable_web_page_preview=True)
                    break
                except Exception as e:
                    print(f"[TG] {attempt+1}: {e}")
                    time.sleep(0.5)
        except Empty:
            continue


def send(msg: str):
    try:
        alert_queue.put_nowait(msg)
    except Exception:
        pass

# ============================================================
# ESTÁGIO 1 — SCAN DEX (10 workers paralelos)
# Triagem ultra-rápida — joga candidatos na fila on-chain
# ============================================================

def passes_filters(pair: dict):
    """
    Triagem rápida nos dados do DEX.
    Retorna (True, dados) ou (False, None).
    """
    if pair.get("chainId") != "solana":
        return False, None

    base = pair.get("baseToken", {})
    addr = base.get("address")
    if not addr or addr in seen_tokens:
        return False, None

    liq   = pair.get("liquidity", {}).get("usd", 0) or 0
    vol5m = pair.get("volume",    {}).get("m5",  0) or 0
    vol1h = pair.get("volume",    {}).get("h1",  0) or 0
    tx    = pair.get("txns",      {}).get("m5",  {})
    buys  = tx.get("buys",  0)
    sells = tx.get("sells", 0)
    ratio = buys / max(sells, 1)
    pc    = pair.get("priceChange", {})
    m5    = pc.get("m5", 0) or 0
    h1    = pc.get("h1", 0) or 0
    price = pair.get("priceUsd")

    created = pair.get("pairCreatedAt")
    age     = ((time.time() * 1000 - created) / 60_000) if created else 999

    if not price:                         return False, None

    # ── FILTROS EM CASCATA ────────────────────────────────
    if liq   < MIN_LIQ   or liq > MAX_LIQ: return False, None
    if buys  < MIN_BUYS:                   return False, None
    if buys  > MAX_BUYS:                   return False, None  # anti-bot
    if ratio < MIN_RATIO:                  return False, None
    if sells < MIN_SELLS:                  return False, None
    if vol5m < MIN_VOL:                    return False, None
    if age   < MIN_AGE   or age > MAX_AGE: return False, None
    if m5    < MIN_M5    or m5 > MAX_M5:   return False, None
    if h1    < MIN_H1    or h1 > MAX_H1:   return False, None

    # ── ANTI-FAKE ─────────────────────────────────────────
    if sells / buys < MIN_SEL_RATE:        return False, None  # só compras = bot

    # ── ACELERAÇÃO DE VOLUME (do código institucional) ───
    if vol1h > 0:
        accel = vol5m / max(vol1h / 12, 1)
        if accel < 1.0:                    return False, None  # volume caindo = fraco

    return True, {
        "addr":   addr,
        "symbol": base.get("symbol", "???"),
        "price":  float(price),
        "liq":    liq,
        "vol5m":  vol5m,
        "vol1h":  vol1h,
        "buys":   buys,
        "sells":  sells,
        "ratio":  ratio,
        "m5":     m5,
        "h1":     h1,
        "age":    age,
        "dex_id": pair.get("dexId", "dex"),
    }


def fetch_pairs(url: str) -> list:
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("pairs") or []
    except:
        pass
    return []


def scan_worker(worker_id: int):
    global seen_tokens
    ep_index = worker_id
    while True:
        url = ENDPOINTS[ep_index % len(ENDPOINTS)]
        ep_index += 1

        if worker_id == 0 and len(seen_tokens) > MAX_SEEN:
            seen_tokens = set(list(seen_tokens)[-(MAX_SEEN // 2):])

        for pair in fetch_pairs(url):
            ok, data = passes_filters(pair)
            if not ok:
                continue
            with lock:
                if data["addr"] in seen_tokens:
                    continue
                seen_tokens.add(data["addr"])
            try:
                onchain_queue.put_nowait(data)
            except Exception:
                pass

        time.sleep(0.2)

# ============================================================
# ESTÁGIO 2 — VERIFICAÇÃO ON-CHAIN GMGN (8 workers paralelos)
# Verifica smart money, holders, LP, honeypot, taxas, dev
# ============================================================

def fetch_gmgn(addr: str) -> dict:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "application/json",
            "Referer":    "https://gmgn.ai/",
        }
        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers=headers, timeout=GMGN_TIMEOUT
        )
        if r.status_code != 200:
            return {}
        d = r.json().get("data", {}) or {}
        return {
            "smart":    d.get("smart_degen_count", 0) or 0,
            "holders":  d.get("holder_count",       0) or 0,
            "top10":    d.get("top10_holder_rate",   1) or 1,
            "lp_burn":  d.get("burn_ratio",          0) or 0,
            "honeypot": d.get("is_honeypot",         False),
            "mintable": d.get("is_mintable",         False),
            "sell_tax": d.get("sell_tax",            0) or 0,
            "buy_tax":  d.get("buy_tax",             0) or 0,
            "rug":      d.get("rug_ratio",           0) or 0,
            "dev":      d.get("dev_token_burn_ratio",0) or 0,
        }
    except Exception as e:
        print(f"[GMGN] {addr[:8]}: {e}")
        return {}


def check_safety(g: dict) -> tuple:
    """
    Retorna (passou, motivo_bloqueio, flags_display).
    Bloqueios imediatos: honeypot, mintable, sell_tax>10%, rug>70%,
    LP<50%, top10>60%, dev>20%, holders<50.
    """
    if not g:
        return True, "", ["⚠️ On-chain indisponível — analise manualmente"]

    flags = []

    # Bloqueios imediatos
    if g.get("honeypot"):
        return False, "🚨 HONEYPOT", []
    if g.get("rug", 0) > 0.7:
        return False, f"🚨 Rug ratio {g['rug']:.0%}", []
    if g.get("mintable"):
        return False, "🚨 Contrato mintable", []
    if g.get("sell_tax", 0) > 10:
        return False, f"🚨 Sell tax {g['sell_tax']:.0f}%", []

    # LP
    lp = float(g.get("lp_burn", 0))
    lp_pct = lp * 100 if lp <= 1 else lp
    if lp_pct < 50:
        return False, f"🚨 LP não travada ({lp_pct:.0f}%)", []
    elif lp_pct >= 90:
        flags.append(f"✅ LP queimada ({lp_pct:.0f}%)")
    else:
        flags.append(f"⚠️ LP parcialmente queimada ({lp_pct:.0f}%)")

    # Top 10 holders
    top10 = float(g.get("top10", 1))
    top10_pct = top10 * 100 if top10 <= 1 else top10
    if top10_pct > 60:
        return False, f"🚨 Top10 com {top10_pct:.0f}%", []
    elif top10_pct > MAX_TOP10 * 100:
        flags.append(f"⚠️ Top10 com {top10_pct:.0f}%")
    else:
        flags.append(f"✅ Distribuição ok — top10 com {top10_pct:.0f}%")

    # Dev holding
    dev = float(g.get("dev", 0))
    dev_pct = dev * 100 if dev <= 1 else dev
    if dev_pct > 20:
        return False, f"🚨 Dev com {dev_pct:.0f}%", []
    elif dev_pct > 5:
        flags.append(f"⚠️ Dev com {dev_pct:.0f}%")
    else:
        flags.append(f"✅ Dev holding baixo ({dev_pct:.0f}%)")

    # Holders
    holders = g.get("holders", 0)
    if holders < 50:
        return False, f"🚨 Apenas {holders} holders", []
    elif holders < MIN_HOLDERS:
        flags.append(f"⚠️ {holders} holders — crescendo")
    else:
        flags.append(f"✅ {holders} holders")

    # Smart money
    smart = g.get("smart", 0)
    if smart >= 5:
        flags.append(f"✅ {smart} smart money wallets — sinal FORTE")
    elif smart >= MIN_SMART:
        flags.append(f"✅ {smart} smart money wallets")
    else:
        return False, f"Smart money insuficiente ({smart})", []

    # Sell tax ok
    st = g.get("sell_tax", 0)
    if st > 5:
        flags.append(f"⚠️ Sell tax: {st:.0f}%")
    elif st > 0:
        flags.append(f"✅ Sell tax: {st:.0f}%")

    return True, "", flags


def risk_score(data: dict, flags: list, fail: str) -> dict:
    """
    Score 0-100. Quanto menor, melhor.
    Verde ≤ 30 | Amarelo 31-60 | Vermelho ≥ 61
    """
    score  = 0
    greens = []
    yellows= []
    reds   = []

    if fail and "⚠️" in fail:
        score += 15; reds.append(fail)

    for f in flags:
        if   f.startswith("✅"): score -= 5;  greens.append(f)
        elif f.startswith("⚠️"): score += 10; yellows.append(f)
        elif f.startswith("🚫"): score += 20; reds.append(f)

    # Liquidez
    liq = data["liq"]
    if   liq >= 80_000: score += 5;  yellows.append(f"Liq alta (${liq:,.0f}) — MC elevado")
    elif liq >= 40_000: score -= 5;  greens.append(f"Liq ótima (${liq:,.0f})")
    elif liq >= 20_000: score -= 10; greens.append(f"✨ Liq ideal early (${liq:,.0f})")
    else:               score += 5;  yellows.append(f"Liq baixa (${liq:,.0f})")

    # Ratio
    r = data["ratio"]
    if   r > 10: score += 10; yellows.append(f"Ratio muito alto ({r:.1f}x) — monitorar")
    elif r >= 4: score -= 10; greens.append(f"Força compradora forte ({r:.1f}x)")
    elif r >= 2: score -= 5;  greens.append(f"Força compradora boa ({r:.1f}x)")

    # Compras
    b = data["buys"]
    if   b > 200: score += 10; yellows.append(f"{b} compras/5min — volume alto")
    elif b >= 40: score -= 10; greens.append(f"Muitas compras ({b}/5min)")
    elif b >= 18: score -= 5;  greens.append(f"Compras institucionais ({b}/5min)")

    # Aceleração de volume
    if data["vol1h"] > 0:
        accel = data["vol5m"] / max(data["vol1h"] / 12, 1)
        if   accel > 4: score -= 12; greens.append(f"Volume acelerando forte ({accel:.1f}x)")
        elif accel > 2: score -= 6;  greens.append(f"Volume acima da média ({accel:.1f}x)")
        elif accel > 1: score -= 2;  greens.append(f"Volume crescendo ({accel:.1f}x)")

    # Idade
    age = data["age"]
    if   age <= 10: score -= 8;  greens.append(f"✨ Ultra early ({age:.0f} min)")
    elif age <= 20: score -= 12; greens.append(f"✨ Janela ideal ({age:.0f} min)")
    elif age <= 30: score -= 5;  greens.append(f"Ainda cedo ({age:.0f} min)")
    else:           score += 5;  yellows.append(f"Janela fechando ({age:.0f} min)")

    # Variação 1h
    h1 = data["h1"]
    if   h1 > 80:  score += 15; reds.append(f"+{h1:.0f}% em 1h — pump avançado")
    elif h1 > 40:  score += 5;  yellows.append(f"+{h1:.0f}% em 1h — movimento forte")
    elif h1 > 10:  score -= 8;  greens.append(f"✨ Início de movimento +{h1:.0f}% em 1h")

    # Variação 5min
    m5 = data["m5"]
    if   m5 > 14:  score += 5;  yellows.append(f"+{m5:.0f}% em 5min — acelerando")
    elif m5 >= 4:  score -= 8;  greens.append(f"Subindo +{m5:.0f}% em 5min")

    score = max(0, min(100, score))

    if score <= 30:
        return dict(score=score, emoji="🟢", label="SINAL VERDE",
                    desc="Alta probabilidade — entre com confiança",
                    greens=greens, yellows=yellows, reds=reds)
    elif score <= 60:
        return dict(score=score, emoji="🟡", label="SINAL AMARELO",
                    desc="Potencial — defina stop loss antes de entrar",
                    greens=greens, yellows=yellows, reds=reds)
    else:
        return dict(score=score, emoji="🔴", label="SINAL VERMELHO",
                    desc="Risco elevado — evite ou aguarde confirmação",
                    greens=greens, yellows=yellows, reds=reds)


def onchain_worker():
    """
    Consome fila do scan, verifica on-chain GMGN,
    e envia alerta se passar em tudo.
    """
    while True:
        try:
            data = onchain_queue.get(timeout=5)
        except Empty:
            continue

        addr   = data["addr"]
        symbol = data["symbol"]

        g = fetch_gmgn(addr)
        passed, fail_reason, flags = check_safety(g)

        if not passed:
            print(f"[BLOCK] ${symbol} — {fail_reason}")
            with lock:
                report_stats["blocked"] += 1
            continue

        risk = risk_score(data, flags, fail_reason)

        with lock:
            monitored_tokens[addr] = {
                "symbol":      symbol,
                "price_entry": data["price"],
                "time":        datetime.utcnow().strftime("%H:%M UTC"),
                "signal":      risk["label"],
                "score":       risk["score"],
                "liq":         data["liq"],
            }
            report_stats["sent"] += 1
            if "VERDE"  in risk["label"]: report_stats["green"]  += 1
            elif "AMAR" in risk["label"]: report_stats["yellow"] += 1
            else:                         report_stats["red"]    += 1

        # Links
        gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
        dex_url    = f"https://dexscreener.com/solana/{addr}"
        trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
        pump_url   = f"https://pump.fun/{addr}"

        # Barras visuais
        strength    = min(int(data["ratio"]), 10)
        bar_force   = "🟢" * strength + "⚪" * (10 - strength)
        risk_filled = min(int(risk["score"] / 10), 10)
        risk_icon   = {"🟢": "🟩", "🟡": "🟨", "🔴": "🟥"}[risk["emoji"]]
        bar_risk    = risk_icon * risk_filled + "⬜" * (10 - risk_filled)

        # Análise resumida
        analysis = ""
        for f in risk["greens"][:3]:  analysis += f"\n✅ {f}"
        for f in risk["yellows"][:2]: analysis += f"\n⚠️ {f}"
        for f in risk["reds"][:2]:    analysis += f"\n🚫 {f}"

        # Smart money destaque
        smart = g.get("smart", 0)
        sm_line = f"🧠 Smart Money: `{smart} wallets`\n" if smart > 0 else ""
        h_line  = f"👥 Holders: `{g.get('holders', '?')}`\n"

        lp = float(g.get("lp_burn", 0))
        lp_pct = lp * 100 if lp <= 1 else lp
        lp_line = f"🔒 LP queimada: `{lp_pct:.0f}%`\n" if lp_pct > 0 else ""

        tips = {
            "🟢": "💡 Sinal limpo — boa janela de entrada",
            "🟡": "💡 Entre com cautela — defina stop loss antes",
            "🔴": "💡 Risco alto — evite ou aguarde confirmação",
        }

        msg = (
            f"{risk['emoji']} *{risk['label']}* — {risk['desc']}\n"
            f"🏦 *SMART MONEY ENTRY*\n\n"
            f"💎 *${symbol}*  —  `{data['dex_id'].upper()}`\n"
            f"📄 *CA:* `{addr}`\n\n"
            f"💲 Preço:    `${data['price']:.10f}`\n"
            f"📈 Var 5m:  `{data['m5']:+.1f}%`  |  Var 1h: `{data['h1']:+.1f}%`\n"
            f"💧 Liq:      `${data['liq']:,.0f}`\n"
            f"📊 Vol 5m:  `${data['vol5m']:,.0f}`\n"
            f"🔥 Compras: `{data['buys']}` | Vendas: `{data['sells']}` | Ratio: `{data['ratio']:.1f}x`\n"
            f"⏰ Idade:   `{data['age']:.0f} min`\n"
            f"{sm_line}{h_line}{lp_line}\n"
            f"💪 Força compradora:\n{bar_force}\n\n"
            f"🎯 Score de risco: `{risk['score']}/100`\n"
            f"{bar_risk}"
            f"{analysis}\n\n"
            f"{tips[risk['emoji']]}\n\n"
            f"🔗 [GMGN]({gmgn_url})  |  [DEX]({dex_url})  |  [PUMP]({pump_url})\n"
            f"⚡ [TROJAN — 0.01 SOL]({trojan_url})"
        )
        send(msg)

# ============================================================
# MONITOR DE SAÍDA — a cada 3 min
# Avisa stop loss, take profit e dump
# ============================================================

def monitor_exit():
    time.sleep(180)
    while True:
        try:
            with lock:
                to_check = {k: v for k, v in monitored_tokens.items()
                            if not v.get("exit_alerted")}
            if not to_check:
                time.sleep(180)
                continue

            addrs   = list(to_check.keys())
            current = {}
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                try:
                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=8)
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
                if not d or info["price_entry"] <= 0:
                    continue
                pct   = ((d["price"] - info["price_entry"]) / info["price_entry"]) * 100
                sells = d["sells"]
                exit_msg = None

                if pct <= -20:
                    exit_msg = (
                        f"🚨 *STOP LOSS — SAIR AGORA*\n\n"
                        f"💎 *${info['symbol']}* caiu `{pct:.1f}%`\n"
                        f"📉 Entrada: `${info['price_entry']:.10f}`\n"
                        f"📉 Atual:   `${d['price']:.10f}`\n"
                        f"⚠️ *Proteja seu capital!*\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif pct >= 60:
                    exit_msg = (
                        f"🤑 *TAKE PROFIT — REALIZE LUCRO*\n\n"
                        f"💎 *${info['symbol']}* subiu `+{pct:.1f}%`\n"
                        f"📈 Entrada: `${info['price_entry']:.10f}`\n"
                        f"📈 Atual:   `${d['price']:.10f}`\n"
                        f"💡 *Considere realizar agora!*\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif sells > 50 and pct < -5:
                    exit_msg = (
                        f"⚠️ *DUMP DETECTADO*\n\n"
                        f"💎 *${info['symbol']}* — `{sells}` vendas/5min\n"
                        f"📉 Var desde alerta: `{pct:+.1f}%`\n"
                        f"🔍 Possível saída de baleias!\n\n"
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

def fetch_prices_batch(addrs):
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs)}",
            timeout=10)
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
                snap  = dict(monitored_tokens)
                stats = dict(report_stats)
                report_stats.update({"sent": 0, "blocked": 0,
                                     "green": 0, "yellow": 0, "red": 0})

            if not snap:
                send("📊 *RELATÓRIO 2H*\nNenhum token alertado no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs   = list(snap.keys())
            batches = [addrs[i:i+30] for i in range(0, len(addrs), 30)]
            prices  = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                for f in as_completed([ex.submit(fetch_prices_batch, b) for b in batches]):
                    prices.update(f.result())

            winners, losers, no_data = [], [], []
            for addr, info in snap.items():
                entry   = info["price_entry"]
                current = prices.get(addr, 0)
                if current > 0 and entry > 0:
                    pct = ((current - entry) / entry) * 100
                    row = (pct, info["symbol"], info.get("signal",""), info.get("score", 50))
                    (winners if pct >= 0 else losers).append(row)
                else:
                    no_data.append(info["symbol"])

            winners.sort(reverse=True)
            losers.sort()
            total    = len(winners) + len(losers)
            hit_rate = (len(winners) / total * 100) if total else 0
            now      = datetime.utcnow().strftime("%d/%m %H:%M UTC")

            report = (
                f"📊 *RELATÓRIO — {now}*\n"
                f"{'─' * 30}\n"
                f"📤 Alertas: `{stats['sent']}` | "
                f"🚫 Bloqueados: `{stats['blocked']}`\n"
                f"🟢`{stats['green']}` 🟡`{stats['yellow']}` 🔴`{stats['red']}`\n"
                f"🎯 Acerto: `{hit_rate:.0f}%` "
                f"(`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 30}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, sig, sc in winners[:15]:
                    icon   = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    blocks = "█" * min(int(abs(pct) / 20), 8)
                    report += f"  {icon} `{pct:+6.1f}%` {blocks} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, sig, sc in losers[:8]:
                    icon = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    report += f"  {icon} `{pct:+6.1f}%` *${sym}*\n"
                report += "\n"

            for label, key in [("🟢 Verdes", "VERDE"), ("🟡 Amarelos", "AMAR")]:
                w = sum(1 for x in winners if key in x[2])
                t = sum(1 for x in winners + losers if key in x[2])
                if t:
                    report += f"{label}: `{w}/{t}` (`{w/t*100:.0f}%` acerto)\n"

            if no_data:
                report += f"\n❓ Sem dados: {', '.join('$'+s for s in no_data[:6])}\n"
            if winners:
                report += f"\n🏆 *Melhor:* `${winners[0][1]}` → `{winners[0][0]:+.1f}%`"
            if losers:
                report += f"\n💀 *Pior:*   `${losers[0][1]}` → `{losers[0][0]:+.1f}%`"

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
            f"Alertas: {len(monitored_tokens)} | "
            f"Fila onchain: {onchain_queue.qsize()} | "
            f"Fila TG: {alert_queue.qsize()} | "
            f"Bloq: {report_stats['blocked']} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🏦 WHALE SNIPER PRO — INSTITUTIONAL + ON-CHAIN")

    threading.Thread(target=telegram_sender,    daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()

    # Scan workers
    for i in range(SCAN_WORKERS):
        threading.Thread(target=scan_worker, args=(i,), daemon=True).start()
        time.sleep(0.05)

    # On-chain workers
    for _ in range(ONCHAIN_WORKERS):
        threading.Thread(target=onchain_worker, daemon=True).start()
        time.sleep(0.05)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
