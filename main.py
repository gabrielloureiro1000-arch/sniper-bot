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
# FILTROS — CALIBRADOS PARA GERAR SINAIS + QUALIDADE
# Testado contra mercado real de memecoins Solana
# ============================================================

MIN_LIQ       = 8_000    # liquidez mínima real
MAX_LIQ       = 500_000  # acima = já foi descoberto

MIN_BUYS      = 10       # 10 compras em 5min = interesse real
MAX_BUYS      = 900      # anti-bot

MIN_RATIO     = 1.8      # compras > vendas = acumulação
MIN_SELLS     = 2        # pelo menos 2 vendas reais
MIN_SEL_RATE  = 0.15     # sells >= 15% das compras

MIN_VOL       = 1_000    # volume mínimo

MIN_AGE       = 3        # mínimo 3 min
MAX_AGE       = 60       # máximo 60 min

MIN_M5        = 2.0      # mínimo +2% em 5min
MAX_M5        = 30.0     # máximo 30% em 5min

MIN_H1        = 3.0      # mínimo +3% em 1h
MAX_H1        = 200.0    # máximo 200% em 1h

MAX_MC        = 5_000_000  # market cap máximo

# ON-CHAIN — só bloqueia o óbvio, não bloqueia por falta de dados
REQUIRE_ONCHAIN = False    # se GMGN falhar, envia mesmo assim com aviso

# ============================================================
# VELOCIDADE
# ============================================================
SCAN_WORKERS    = 8
ONCHAIN_WORKERS = 6
FETCH_TIMEOUT   = 4
GMGN_TIMEOUT    = 5
REPORT_INTERVAL = 7_200
MAX_SEEN        = 30_000

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
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "blocked": 0, "green": 0, "yellow": 0, "red": 0}
lock             = threading.Lock()
onchain_queue    = Queue(maxsize=500)
alert_queue      = Queue(maxsize=1000)
gmgn_cache       = {}
gmgn_cache_lock  = threading.Lock()

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# ENVIO TELEGRAM
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
# GMGN — com cache + fallback generoso
# ============================================================

def fetch_gmgn(addr: str) -> dict:
    with gmgn_cache_lock:
        cached = gmgn_cache.get(addr)
        if cached and (time.time() - cached["ts"]) < 300:
            return cached["data"]
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
            "Referer": "https://gmgn.ai/",
        }
        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers=headers, timeout=GMGN_TIMEOUT
        )
        if r.status_code != 200:
            return {}
        d = r.json().get("data", {}) or {}
        result = {
            "smart":    d.get("smart_degen_count",  0) or 0,
            "holders":  d.get("holder_count",        0) or 0,
            "top10":    d.get("top10_holder_rate",   1) or 1,
            "lp_burn":  d.get("burn_ratio",          0) or 0,
            "honeypot": d.get("is_honeypot",     False),
            "mintable": d.get("is_mintable",     False),
            "sell_tax": d.get("sell_tax",            0) or 0,
            "rug":      d.get("rug_ratio",           0) or 0,
            "dev":      d.get("dev_token_burn_ratio",0) or 0,
        }
        with gmgn_cache_lock:
            gmgn_cache[addr] = {"data": result, "ts": time.time()}
        return result
    except Exception as e:
        print(f"[GMGN] {addr[:8]}: {e}")
        return {}


def check_safety(g: dict) -> tuple:
    """
    Bloqueios apenas para riscos CRÍTICOS e confirmados.
    Se GMGN não retornar dados, passa com aviso.
    """
    if not g:
        return True, "", ["⚠️ On-chain indisponível — verifique no GMGN antes de entrar"]

    flags = []

    # Bloqueios absolutos — só o óbvio
    if g.get("honeypot") is True:
        return False, "🚨 HONEYPOT", []
    if g.get("rug", 0) > 0.8:
        return False, f"🚨 Rug ratio {g['rug']:.0%}", []
    if g.get("mintable") is True:
        return False, "🚨 Mintable", []
    if g.get("sell_tax", 0) > 15:
        return False, f"🚨 Sell tax {g['sell_tax']:.0f}%", []

    # LP — aviso mas não bloqueia se dado ausente
    lp = g.get("lp_burn")
    if lp is not None:
        lp_pct = float(lp) * 100 if float(lp) <= 1 else float(lp)
        if lp_pct < 30:
            return False, f"🚨 LP não travada ({lp_pct:.0f}%)", []
        elif lp_pct >= 80:
            flags.append(f"✅ LP queimada ({lp_pct:.0f}%)")
        else:
            flags.append(f"⚠️ LP parcial ({lp_pct:.0f}%)")

    # Top 10 — só bloqueia se muito concentrado
    top10 = g.get("top10")
    if top10 is not None:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t > 70:
            return False, f"🚨 Top10 com {t:.0f}%", []
        elif t > 45:
            flags.append(f"⚠️ Top10 com {t:.0f}%")
        else:
            flags.append(f"✅ Distribuição ok ({t:.0f}%)")

    # Dev holding
    dev = g.get("dev")
    if dev is not None:
        d = float(dev) * 100 if float(dev) <= 1 else float(dev)
        if d > 25:
            return False, f"🚨 Dev com {d:.0f}%", []
        elif d > 8:
            flags.append(f"⚠️ Dev com {d:.0f}%")
        else:
            flags.append(f"✅ Dev baixo ({d:.0f}%)")

    # Holders — aviso suave
    holders = g.get("holders", 0)
    if holders > 0:
        if holders < 30:
            return False, f"🚨 Só {holders} holders", []
        elif holders < 80:
            flags.append(f"⚠️ {holders} holders — crescendo")
        else:
            flags.append(f"✅ {holders} holders")

    # Smart money — informativo, não bloqueia
    smart = g.get("smart", 0)
    if smart >= 5:
        flags.append(f"✅ {smart} smart money wallets — FORTE")
    elif smart >= 2:
        flags.append(f"✅ {smart} smart money wallets")
    elif smart == 1:
        flags.append(f"⚠️ {smart} smart money wallet")
    else:
        flags.append("⚠️ Nenhuma smart money detectada ainda")

    # Sell tax suave
    st = g.get("sell_tax", 0)
    if 0 < st <= 10:
        flags.append(f"⚠️ Sell tax: {st:.0f}%")
    elif st == 0:
        flags.append("✅ Sem sell tax")

    return True, "", flags

# ============================================================
# SCORE DE RISCO
# ============================================================

def risk_score(data: dict, flags: list, fail: str) -> dict:
    score   = 0
    greens  = []
    yellows = []
    reds    = []

    if fail and "⚠️" in fail:
        score += 10; reds.append(fail)

    for f in flags:
        if   f.startswith("✅"): score -= 4;  greens.append(f)
        elif f.startswith("⚠️"): score += 8;  yellows.append(f)
        elif f.startswith("🚫"): score += 18; reds.append(f)

    # Market cap
    mc = data.get("mc", 0)
    if mc > 0:
        if mc < 200_000:
            score -= 15; greens.append(f"✨ MC baixíssimo (${mc:,.0f}) — upside máximo")
        elif mc < 700_000:
            score -= 10; greens.append(f"MC baixo (${mc:,.0f}) — bom upside")
        elif mc < 2_000_000:
            score -= 3;  greens.append(f"MC moderado (${mc:,.0f})")
        else:
            score += 8;  yellows.append(f"MC alto (${mc:,.0f})")

    # Liquidez
    liq = data["liq"]
    if   liq >= 100_000: score += 5;  yellows.append(f"Liq alta (${liq:,.0f})")
    elif liq >= 40_000:  score -= 5;  greens.append(f"Liq ótima (${liq:,.0f})")
    elif liq >= 15_000:  score -= 10; greens.append(f"✨ Liq ideal early (${liq:,.0f})")
    elif liq >= 8_000:   score += 2;  yellows.append(f"Liq baixa (${liq:,.0f})")

    # Ratio
    r = data["ratio"]
    if   r > 12: score += 10; yellows.append(f"Ratio muito alto ({r:.1f}x)")
    elif r >= 5: score -= 10; greens.append(f"Força compradora forte ({r:.1f}x)")
    elif r >= 3: score -= 6;  greens.append(f"Força compradora boa ({r:.1f}x)")
    elif r >= 2: score -= 3;  greens.append(f"Força compradora ({r:.1f}x)")

    # Compras
    b = data["buys"]
    if   b > 300: score += 8;  yellows.append(f"{b} compras/5min — monitorar")
    elif b >= 50: score -= 10; greens.append(f"Muitas compras ({b}/5min)")
    elif b >= 20: score -= 5;  greens.append(f"Boas compras ({b}/5min)")
    elif b >= 10: score -= 2;  greens.append(f"Compras de baleia ({b}/5min)")

    # Aceleração de volume
    if data["vol1h"] > 0:
        accel = data["vol5m"] / max(data["vol1h"] / 12, 1)
        if   accel > 5: score -= 12; greens.append(f"Volume acelerando forte ({accel:.1f}x)")
        elif accel > 3: score -= 7;  greens.append(f"Volume acima da média ({accel:.1f}x)")
        elif accel > 1: score -= 3;  greens.append(f"Volume crescendo ({accel:.1f}x)")
        elif accel < 0.5: score += 8; yellows.append("Volume desacelerando")

    # Idade
    age = data["age"]
    if   age <= 8:  score -= 8;  greens.append(f"✨ Ultra early ({age:.0f} min)")
    elif age <= 20: score -= 12; greens.append(f"✨ Janela ideal ({age:.0f} min)")
    elif age <= 35: score -= 5;  greens.append(f"Ainda cedo ({age:.0f} min)")
    elif age <= 60: score += 5;  yellows.append(f"Janela fechando ({age:.0f} min)")

    # Variação 1h
    h1 = data["h1"]
    if   h1 > 100: score += 15; reds.append(f"+{h1:.0f}% em 1h — pump avançado")
    elif h1 > 50:  score += 8;  yellows.append(f"+{h1:.0f}% em 1h — forte")
    elif h1 > 10:  score -= 5;  greens.append(f"Movimento saudável +{h1:.0f}% em 1h")
    elif h1 > 3:   score -= 8;  greens.append(f"✨ Início de movimento +{h1:.0f}% em 1h")

    # Variação 5min
    m5 = data["m5"]
    if   m5 > 20: score += 8;  yellows.append(f"+{m5:.0f}% em 5min — acelerando")
    elif m5 >= 5: score -= 8;  greens.append(f"Subindo +{m5:.0f}% em 5min")
    elif m5 >= 2: score -= 4;  greens.append(f"Alta suave +{m5:.0f}% em 5min")

    score = max(0, min(100, score))

    if score <= 35:
        return dict(score=score, emoji="🟢", label="SINAL VERDE",
                    desc="Alta probabilidade — boa janela de entrada",
                    greens=greens, yellows=yellows, reds=reds)
    elif score <= 65:
        return dict(score=score, emoji="🟡", label="SINAL AMARELO",
                    desc="Potencial — defina stop loss antes de entrar",
                    greens=greens, yellows=yellows, reds=reds)
    else:
        return dict(score=score, emoji="🔴", label="SINAL VERMELHO",
                    desc="Risco elevado — evite ou aguarde confirmação",
                    greens=greens, yellows=yellows, reds=reds)

# ============================================================
# SCAN DEX — triagem rápida
# ============================================================

def passes_filters(pair: dict):
    if pair.get("chainId") != "solana":
        return False, None

    base  = pair.get("baseToken", {})
    addr  = base.get("address")
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
    mc    = pair.get("fdv") or pair.get("marketCap") or 0

    created = pair.get("pairCreatedAt")
    age     = ((time.time() * 1000 - created) / 60_000) if created else 999

    if not price:                              return False, None
    if liq   < MIN_LIQ or liq > MAX_LIQ:      return False, None
    if mc > 0 and mc > MAX_MC:                return False, None
    if buys  < MIN_BUYS or buys > MAX_BUYS:   return False, None
    if ratio < MIN_RATIO:                      return False, None
    if sells < MIN_SELLS:                      return False, None
    if sells > 0 and sells/buys < MIN_SEL_RATE: return False, None
    if vol5m < MIN_VOL:                        return False, None
    if age   < MIN_AGE or age > MAX_AGE:       return False, None
    if m5    < MIN_M5  or m5 > MAX_M5:         return False, None
    if h1    < MIN_H1  or h1 > MAX_H1:         return False, None

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
        "mc":     mc,
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
# ON-CHAIN WORKERS
# ============================================================

def onchain_worker():
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

        gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
        dex_url    = f"https://dexscreener.com/solana/{addr}"
        trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
        pump_url   = f"https://pump.fun/{addr}"

        strength    = min(int(data["ratio"]), 10)
        bar_force   = "🟢" * strength + "⚪" * (10 - strength)
        risk_filled = min(int(risk["score"] / 10), 10)
        risk_icon   = {"🟢": "🟩", "🟡": "🟨", "🔴": "🟥"}[risk["emoji"]]
        bar_risk    = risk_icon * risk_filled + "⬜" * (10 - risk_filled)

        analysis = ""
        for f in risk["greens"][:3]:  analysis += f"\n✅ {f}"
        for f in risk["yellows"][:2]: analysis += f"\n⚠️ {f}"
        for f in risk["reds"][:2]:    analysis += f"\n🚫 {f}"

        smart  = g.get("smart", 0)
        hlds   = g.get("holders", "?")
        lp     = g.get("lp_burn", 0)
        lp_pct = (float(lp)*100 if float(lp)<=1 else float(lp)) if lp else 0
        mc     = data.get("mc", 0)

        sm_line = f"🧠 Smart Money: `{smart} wallets`\n" if smart > 0 else "🧠 Smart Money: `aguardando dados`\n"
        h_line  = f"👥 Holders: `{hlds}`\n"
        lp_line = f"🔒 LP queimada: `{lp_pct:.0f}%`\n" if lp_pct > 0 else ""
        mc_line = f"📦 Market Cap: `${mc:,.0f}`\n" if mc > 0 else ""

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
            f"{mc_line}{sm_line}{h_line}{lp_line}\n"
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
# MONITOR DE SAÍDA
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
                        f"📉 Desde alerta: `{pct:+.1f}%`\n"
                        f"🔍 Possível saída de baleias!\n\n"
                        f"🔗 [DEX](https://dexscreener.com/solana/{addr})"
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
                    row = (pct, info["symbol"], info.get("signal",""), info.get("score",50))
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
                f"📤 Alertas: `{stats['sent']}` | 🚫 Bloq: `{stats['blocked']}`\n"
                f"🟢`{stats['green']}` 🟡`{stats['yellow']}` 🔴`{stats['red']}`\n"
                f"🎯 Acerto: `{hit_rate:.0f}%` (`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 30}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, sig, sc in winners[:15]:
                    icon   = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    blocks = "█" * min(int(abs(pct)/20), 8)
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
                t = sum(1 for x in winners+losers if key in x[2])
                if t:
                    report += f"{label}: `{w}/{t}` (`{w/t*100:.0f}%`)\n"

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
            f"Fila: {onchain_queue.qsize()} | "
            f"TG: {alert_queue.qsize()} | "
            f"Bloq: {report_stats['blocked']} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🏦 WHALE SNIPER PRO — ONLINE")
    send(
        "🟢 *WHALE SNIPER PRO — ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scan workers | `{ONCHAIN_WORKERS}` on-chain workers\n"
        f"🔄 `{len(ENDPOINTS)}` endpoints simultâneos\n\n"
        "🛡️ *Filtros ativos:*\n"
        f"  🐋 Compras: `{MIN_BUYS}–{MAX_BUYS}` /5min\n"
        f"  📊 Ratio: `{MIN_RATIO}x` mínimo\n"
        f"  💧 Liq: `${MIN_LIQ:,}–${MAX_LIQ:,}`\n"
        f"  📈 Var 5m: `{MIN_M5:.0f}%–{MAX_M5:.0f}%`\n"
        f"  📈 Var 1h: `{MIN_H1:.0f}%–{MAX_H1:.0f}%`\n"
        f"  ⏰ Idade: `{MIN_AGE}–{MAX_AGE} min`\n"
        f"  📦 MC máx: `${MAX_MC:,}`\n\n"
        "🔬 On-chain: honeypot, LP, holders, dev, smart money\n"
        "🚨 Monitor de saída: stop -20% | take profit +60%\n"
        "📢 Relatório a cada 2h"
    )

    threading.Thread(target=telegram_sender,    daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()

    for i in range(SCAN_WORKERS):
        threading.Thread(target=scan_worker, args=(i,), daemon=True).start()
        time.sleep(0.05)

    for _ in range(ONCHAIN_WORKERS):
        threading.Thread(target=onchain_worker, daemon=True).start()
        time.sleep(0.05)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
