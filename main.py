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
# FILTROS — CAPTURA PRECOCE + EQUILIBRADO
# Objetivo: pegar cedo SEM cortar todos os sinais
# ============================================================

# ── LIQUIDEZ ─────────────────────────────────────────────
MIN_LIQUIDITY        = 2_000    # baixo = token jovem e barato
MAX_LIQUIDITY        = 300_000  # acima = já bombou

# ── FILTRO DE BALEIA ─────────────────────────────────────
MIN_WHALE_BUYS       = 8        # mínimo 8 compras = baleias entrando
MAX_WHALE_BUYS       = 800      # anti-bot

# ── VOLUME ───────────────────────────────────────────────
MIN_VOLUME_M5        = 500      # bem baixo = token ainda no início

# ── FORÇA COMPRADORA ─────────────────────────────────────
MIN_BUY_SELL_RATIO   = 1.3      # levemente comprador já é sinal
MAX_BUY_SELL_RATIO   = 15.0     # anti-manipulação

# ── IDADE DO PAR ─────────────────────────────────────────
MIN_AGE_MINUTES      = 3        # pega tokens com 3 min de vida
MAX_AGE_MINUTES      = 90       # janela generosa mas fecha antes de 2h

# ── VARIAÇÃO DE PREÇO ────────────────────────────────────
MIN_PRICE_CHANGE_H1  = -5.0     # aceita até -5% (token flat ou acumulando)
MAX_PRICE_CHANGE_H1  = 120.0    # até 120% — ainda pode ter espaço

# ── VARIAÇÃO 5MIN ────────────────────────────────────────
MIN_PRICE_CHANGE_M5  = -5.0     # aceita leve queda (acumulação)
MAX_PRICE_CHANGE_M5  = 30.0     # pump violento = chegamos tarde

# ── VENDAS REAIS ─────────────────────────────────────────
MIN_SELLS_5M         = 1        # pelo menos 1 venda real

# ============================================================
# VELOCIDADE MÁXIMA
# ============================================================
SCAN_WORKERS        = 12   # threads de scan DEX
ONCHAIN_WORKERS     = 8    # threads de verificação GMGN paralela
FETCH_TIMEOUT       = 3    # timeout agressivo DEX
GMGN_TIMEOUT        = 5    # timeout GMGN
ALERT_QUEUE_SIZE    = 1000
ONCHAIN_QUEUE_SIZE  = 500  # fila entre scan e verificação on-chain
MAX_SEEN_TOKENS     = 30_000
REPORT_INTERVAL     = 7_200

# 12 endpoints — cada worker tem o seu, zero sobreposição
ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+moon",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+token",
    "https://api.dexscreener.com/latest/dex/search?q=sol+trending",
    "https://api.dexscreener.com/latest/dex/search?q=solana+hot",
    "https://api.dexscreener.com/latest/dex/search?q=sol+fire",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=sol+launch",
    "https://api.dexscreener.com/latest/dex/search?q=solana+whale",
]

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}
report_stats     = {"sent": 0, "green": 0, "yellow": 0, "red": 0, "blocked": 0}
lock             = threading.Lock()

# Pipeline assíncrono em 3 estágios:
# [scan] → onchain_queue → [verificação GMGN] → alert_queue → [envio TG]
onchain_queue = Queue(maxsize=ONCHAIN_QUEUE_SIZE)
alert_queue   = Queue(maxsize=ALERT_QUEUE_SIZE)

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
                    time.sleep(0.3)
        except Empty:
            continue
        except Exception as e:
            print(f"[TG-SENDER] {e}")


def send(msg: str):
    try:
        alert_queue.put_nowait(msg)
    except Exception:
        pass

# ============================================================
# ESTÁGIO 1 — SCAN DEX (12 workers, sem espera)
# Apenas triagem rápida — joga na fila on-chain imediatamente
# ============================================================

def passes_dex_filters(pair: dict) -> tuple:
    """
    Triagem ultra-rápida nos dados do DEX.
    Retorna (passou, dados_extraídos) em microssegundos.
    """
    if pair.get("chainId") != "solana":
        return False, {}

    base   = pair.get("baseToken", {})
    addr   = base.get("address")
    if not addr:
        return False, {}

    # Check sem lock primeiro (barreira mais rápida)
    if addr in seen_tokens:
        return False, {}

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

    created_at = pair.get("pairCreatedAt")
    age_min    = ((time.time() * 1000 - created_at) / 60_000) if created_at else 9999

    ratio = buys5m / max(sells5m, 1)

    if not price_usd:                        return False, {}
    if buys5m    < MIN_WHALE_BUYS:           return False, {}  # filtro baleia: mín 8 compras
    if buys5m    > MAX_WHALE_BUYS:           return False, {}  # anti-bot
    if liq       < MIN_LIQUIDITY:            return False, {}
    if liq       > MAX_LIQUIDITY:            return False, {}
    if vol5m     < MIN_VOLUME_M5:            return False, {}
    if ratio     < MIN_BUY_SELL_RATIO:       return False, {}
    if ratio     > MAX_BUY_SELL_RATIO:       return False, {}
    if change_h1 < MIN_PRICE_CHANGE_H1:      return False, {}  # aceita 0% = token ainda barato
    if change_h1 > MAX_PRICE_CHANGE_H1:      return False, {}  # já bombou demais
    if change_m5 < MIN_PRICE_CHANGE_M5:      return False, {}  # aceita leve queda = acumulação
    if change_m5 > MAX_PRICE_CHANGE_M5:      return False, {}  # pump violento = chegamos tarde
    if age_min   < MIN_AGE_MINUTES:          return False, {}  # muito novo = rug iminente
    if age_min   > MAX_AGE_MINUTES:          return False, {}  # > 45min = geralmente já foi
    if sells5m   < MIN_SELLS_5M:             return False, {}

    return True, {
        "addr":      addr,
        "symbol":    base.get("symbol", "???"),
        "price":     float(price_usd),
        "liq":       liq,
        "vol5m":     vol5m,
        "vol1h":     vol1h,
        "buys5m":    buys5m,
        "sells5m":   sells5m,
        "ratio":     ratio,
        "change_h1": change_h1,
        "change_m5": change_m5,
        "age_min":   age_min,
        "dex_id":    pair.get("dexId", "dex"),
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

        # Limpa cache periodicamente
        if worker_id == 0 and len(seen_tokens) > MAX_SEEN_TOKENS:
            seen_tokens = set(list(seen_tokens)[-(MAX_SEEN_TOKENS // 2):])
        for pair in fetch_pairs(url):
            passed, data = passes_dex_filters(pair)
            if not passed:
                continue

            # Reserva o endereço imediatamente com lock
            with lock:
                if data["addr"] in seen_tokens:
                    continue
                seen_tokens.add(data["addr"])

            # Joga na fila de verificação on-chain — não espera
            try:
                onchain_queue.put_nowait(data)
            except Exception:
                pass  # fila cheia — descarta (prefere velocidade)

        time.sleep(0.15)  # pausa mínima anti-rate-limit

# ============================================================
# ESTÁGIO 2 — VERIFICAÇÃO ON-CHAIN GMGN (8 workers paralelos)
# Consome a fila do scan e verifica cada token em paralelo
# ============================================================

def fetch_gmgn_token_info(addr: str) -> dict:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "application/json",
            "Referer":    "https://gmgn.ai/",
        }
        url  = f"https://gmgn.ai/api/v1/token/sol/{addr}"
        resp = requests.get(url, headers=headers, timeout=GMGN_TIMEOUT)
        if resp.status_code != 200:
            return {}
        data  = resp.json()
        token = data.get("data") or data.get("token") or data
        return {
            "top10_holders_pct": token.get("top10_holder_rate"),
            "dev_holding_pct":   token.get("dev_token_burn_ratio"),
            "holder_count":      token.get("holder_count"),
            "lp_burned":         token.get("burn_ratio"),
            "is_honeypot":       token.get("is_honeypot"),
            "buy_tax":           token.get("buy_tax"),
            "sell_tax":          token.get("sell_tax"),
            "is_open_source":    token.get("open_source"),
            "is_mintable":       token.get("is_mintable"),
            "smart_money_count": token.get("smart_degen_count", 0),
            "rug_ratio":         token.get("rug_ratio"),
        }
    except Exception as e:
        print(f"[GMGN] {addr[:8]}: {e}")
        return {}


def check_onchain_safety(info: dict) -> tuple:
    """Retorna (passou, motivo_bloqueio, flags)"""
    if not info:
        return True, "", ["⚠️ Dados on-chain indisponíveis — analise manualmente"]

    flags      = []
    hard_fails = []

    if info.get("is_honeypot") is True:
        return False, "🚨 HONEYPOT detectado", []

    rug = info.get("rug_ratio")
    if rug is not None:
        if rug > 0.8:
            return False, f"🚨 Rug ratio {rug:.0%}", []
        elif rug > 0.5:
            flags.append(f"🚫 Rug ratio alto ({rug:.0%})")

    if info.get("is_mintable") is True:
        hard_fails.append("mintable")
        flags.append("🚫 Contrato mintable — dev pode criar tokens infinitos")

    sell_tax = info.get("sell_tax") or 0
    buy_tax  = info.get("buy_tax")  or 0
    if sell_tax > 10:
        hard_fails.append(f"sell tax {sell_tax:.0f}%")
        flags.append(f"🚫 Sell tax {sell_tax:.0f}% — possível honeypot")
    elif sell_tax > 5:
        flags.append(f"⚠️ Sell tax: {sell_tax:.0f}%")
    elif sell_tax > 0:
        flags.append(f"✅ Sell tax: {sell_tax:.0f}%")

    lp = info.get("lp_burned")
    if lp is not None:
        lp_pct = float(lp) * 100 if float(lp) <= 1 else float(lp)
        if lp_pct >= 90:
            flags.append(f"✅ LP queimada ({lp_pct:.0f}%)")
        elif lp_pct >= 50:
            flags.append(f"⚠️ LP parcialmente queimada ({lp_pct:.0f}%)")
        else:
            hard_fails.append(f"LP não travada ({lp_pct:.0f}%)")
            flags.append(f"🚫 LP não travada ({lp_pct:.0f}%) — risco de rug")

    top10 = info.get("top10_holders_pct")
    if top10 is not None:
        t = float(top10) * 100 if float(top10) <= 1 else float(top10)
        if t > 50:
            hard_fails.append(f"top10 {t:.0f}%")
            flags.append(f"🚫 Top 10 wallets com {t:.0f}% — bomba-relógio")
        elif t > 35:
            flags.append(f"⚠️ Top 10 com {t:.0f}% — concentrado")
        else:
            flags.append(f"✅ Distribuição saudável — top 10 com {t:.0f}%")

    dev = info.get("dev_holding_pct")
    if dev is not None:
        d = float(dev) * 100 if float(dev) <= 1 else float(dev)
        if d > 15:
            hard_fails.append(f"dev {d:.0f}%")
            flags.append(f"🚫 Dev com {d:.0f}% do supply")
        elif d > 5:
            flags.append(f"⚠️ Dev com {d:.0f}%")
        else:
            flags.append(f"✅ Dev holding baixo ({d:.0f}%)")

    holders = info.get("holder_count")
    if holders is not None:
        if holders < 30:
            hard_fails.append(f"{holders} holders")
            flags.append(f"🚫 Apenas {holders} holders — muito concentrado")
        elif holders < 50:
            flags.append(f"⚠️ Poucos holders: {holders}")
        else:
            flags.append(f"✅ {holders} holders")

    smart = info.get("smart_money_count") or 0
    if smart >= 3:
        flags.append(f"✅ {smart} smart money wallets — sinal forte")
    elif smart >= 1:
        flags.append(f"✅ {smart} smart money wallet detectada")
    else:
        flags.append("⚠️ Nenhuma smart money ainda")

    if len(hard_fails) >= 2:
        return False, f"Bloqueado: {' + '.join(hard_fails)}", flags
    if hard_fails:
        return True, f"⚠️ {hard_fails[0]}", flags

    return True, "", flags


def calculate_risk_score(data: dict, onchain_flags: list, onchain_fail: str) -> dict:
    score   = 0
    greens  = []
    yellows = []
    reds    = []

    buys5m    = data["buys5m"]
    sells5m   = data["sells5m"]
    ratio     = data["ratio"]
    liq       = data["liq"]
    vol5m     = data["vol5m"]
    vol1h     = data["vol1h"]
    change_h1 = data["change_h1"]
    change_m5 = data["change_m5"]
    age_min   = data["age_min"]

    if onchain_fail and "⚠️" in onchain_fail:
        score += 20; reds.append(onchain_fail)

    for f in onchain_flags:
        if   f.startswith("✅"): score -= 3;  greens.append(f)
        elif f.startswith("⚠️"): score += 8;  yellows.append(f)
        elif f.startswith("🚫"): score += 20; reds.append(f)

    # Liquidez
    if liq >= 50_000:  score -= 10; greens.append(f"Boa liquidez (${liq:,.0f})")
    elif liq >= 15_000: score -= 5; greens.append(f"Liquidez ok (${liq:,.0f})")
    elif liq >= 5_000:  score += 5; yellows.append(f"Liquidez baixa (${liq:,.0f})")
    else:               score += 18; reds.append(f"Liquidez muito baixa (${liq:,.0f})")

    # Ratio
    if ratio > 10:    score += 15; yellows.append(f"Ratio elevado ({ratio:.1f}x)")
    elif ratio >= 2:  score -= 8;  greens.append(f"Força compradora ({ratio:.1f}x)")
    else:             score -= 3;  greens.append(f"Ratio equilibrado ({ratio:.1f}x)")

    # Volume de compras
    if buys5m > 400:   score += 20; reds.append(f"{buys5m} compras/5min — bot suspeito")
    elif buys5m > 100: score += 8;  yellows.append(f"Volume alto ({buys5m}/5min)")
    elif buys5m >= 20: score -= 8;  greens.append(f"Compras fortes ({buys5m}/5min)")
    elif buys5m >= 8:              greens.append(f"8+ compras de baleia ({buys5m}/5min)")

    # Aceleração de volume
    if vol5m > 0 and vol1h > 0:
        accel = vol5m / max(vol1h / 12, 1)
        if accel > 4:   score -= 10; greens.append(f"Volume acelerando ({accel:.1f}x)")
        elif accel > 1.5: score -= 5; greens.append(f"Volume acima da média ({accel:.1f}x)")
        elif accel < 0.5: score += 8; yellows.append("Volume desacelerando")

    # Idade
    if age_min < 10:   score += 20; reds.append(f"Par com {age_min:.0f} min — risco alto")
    elif age_min < 20: score += 10; yellows.append(f"Par muito novo ({age_min:.0f} min)")
    elif age_min < 45: score += 3;  yellows.append(f"Par novo ({age_min:.0f} min)")
    elif age_min < 90: score -= 5;  greens.append(f"Par com histórico ({age_min:.0f} min)")
    else:              score -= 10; greens.append(f"Par estabelecido ({age_min:.0f} min)")

    # Variação 1h
    if change_h1 > 100:  score += 22; reds.append(f"+{change_h1:.0f}% em 1h — pump avançado")
    elif change_h1 > 60: score += 12; reds.append(f"+{change_h1:.0f}% em 1h — alta intensa")
    elif change_h1 > 20: score += 5;  yellows.append(f"+{change_h1:.0f}% em 1h")
    elif change_h1 > 3:  score -= 8;  greens.append(f"Movimento saudável +{change_h1:.0f}% em 1h")
    else:                score -= 3;  greens.append(f"Início de movimento +{change_h1:.0f}% em 1h")

    # Variação 5min
    if change_m5 > 20:    score += 12; yellows.append(f"Pump +{change_m5:.0f}% em 5min")
    elif change_m5 > 5:   score += 3;  yellows.append(f"Subindo +{change_m5:.0f}% em 5min")
    elif change_m5 > 0:   score -= 5;  greens.append(f"Alta suave +{change_m5:.0f}% em 5min")
    elif change_m5 < -10: score += 12; reds.append(f"Caindo {change_m5:.0f}% em 5min")

    # Vendas
    if sells5m == 0:   score += 18; reds.append("Zero vendas — suspeito")
    elif sells5m < 3:  score += 5;  yellows.append(f"Poucas vendas ({sells5m})")
    else:              score -= 5;  greens.append(f"Mercado bilateral ({sells5m} vendas)")

    score = max(0, min(100, score))

    if score <= 30:
        return dict(score=score, emoji="🟢", label="SINAL VERDE",
                    desc="Baixo risco — bom potencial",
                    greens=greens, yellows=yellows, reds=reds)
    elif score <= 60:
        return dict(score=score, emoji="🟡", label="SINAL AMARELO",
                    desc="Risco moderado — use stop loss",
                    greens=greens, yellows=yellows, reds=reds)
    else:
        return dict(score=score, emoji="🔴", label="SINAL VERMELHO",
                    desc="Alto risco — probabilidade de perda elevada",
                    greens=greens, yellows=yellows, reds=reds)


def classify_whale(buys5m, ratio, vol5m, liq):
    if buys5m >= 50 and ratio >= 4 and vol5m >= 10_000:
        return "🚨", "MEGA BALEIA"
    if buys5m >= 20 and ratio >= 2.5 and liq >= 8_000:
        return "🐋", "BALEIA DETECTADA"
    return "📈", "ACUMULAÇÃO ATIVA"


def onchain_worker():
    """
    Consome a fila onchain_queue.
    Cada worker verifica 1 token no GMGN independentemente.
    8 workers = 8 verificações simultâneas.
    """
    while True:
        try:
            data = onchain_queue.get(timeout=5)
        except Empty:
            continue

        addr   = data["addr"]
        symbol = data["symbol"]

        # Verificação on-chain
        onchain = fetch_gmgn_token_info(addr)
        passed, fail_reason, onchain_flags = check_onchain_safety(onchain)

        if not passed:
            print(f"[BLOQUEADO] ${symbol} — {fail_reason}")
            with lock:
                report_stats["blocked"] += 1
            continue

        # Score combinado
        risk = calculate_risk_score(data, onchain_flags, fail_reason)
        whale_emoji, whale_label = classify_whale(
            data["buys5m"], data["ratio"], data["vol5m"], data["liq"]
        )

        with lock:
            monitored_tokens[addr] = {
                "symbol":      symbol,
                "price_entry": data["price"],
                "time":        datetime.utcnow().strftime("%H:%M UTC"),
                "liq":         data["liq"],
                "vol5m":       data["vol5m"],
                "signal":      risk["label"],
                "score":       risk["score"],
            }
            report_stats["sent"] += 1
            if "VERDE"  in risk["label"]: report_stats["green"]  += 1
            elif "AMAR" in risk["label"]: report_stats["yellow"] += 1
            else:                         report_stats["red"]    += 1

        # Monta mensagem
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
        for g in risk["greens"][:2]:  analysis += f"\n✅ {g}"
        for y in risk["yellows"][:2]: analysis += f"\n⚠️ {y}"
        for r in risk["reds"][:2]:    analysis += f"\n🚫 {r}"

        smart  = onchain.get("smart_money_count") or 0
        hlds   = onchain.get("holder_count")
        lp     = onchain.get("lp_burned")
        lp_pct = (float(lp) * 100 if float(lp) <= 1 else float(lp)) if lp else None

        extras = ""
        if smart > 0:  extras += f"🧠 Smart money: `{smart} wallets`\n"
        if hlds:       extras += f"👥 Holders: `{hlds}`\n"
        if lp_pct:     extras += f"🔒 LP queimada: `{lp_pct:.0f}%`\n"

        tips = {
            "🟢": "💡 Sinal limpo — boa janela de entrada",
            "🟡": "💡 Entre com cautela — defina stop loss antes",
            "🔴": "💡 Risco alto — evite ou aguarde confirmação",
        }

        msg = (
            f"{risk['emoji']} *{risk['label']}* — {risk['desc']}\n"
            f"{whale_emoji} *{whale_label}* — `{data['buys5m']}` compras | ratio `{data['ratio']:.1f}x`\n\n"
            f"💎 *${symbol}*  —  `{data['dex_id'].upper()}`\n"
            f"📄 *CA:* `{addr}`\n\n"
            f"💲 Preço:    `${data['price']:.10f}`\n"
            f"📈 Var 5m:  `{data['change_m5']:+.1f}%`  |  Var 1h: `{data['change_h1']:+.1f}%`\n"
            f"💧 Liq:      `${data['liq']:,.0f}`\n"
            f"📊 Vol 5m:  `${data['vol5m']:,.0f}`  |  Vol 1h: `${data['vol1h']:,.0f}`\n"
            f"🔥 Compras: `{data['buys5m']}` | Vendas: `{data['sells5m']}` | Ratio: `{data['ratio']:.1f}x`\n"
            f"⏰ Idade:   `{data['age_min']:.0f} min`\n"
            f"{extras}\n"
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
# INICIALIZAÇÃO DE TODOS OS WORKERS
# ============================================================

def scan():
    print(f"🐋 WHALE SNIPER PRO v5 — {SCAN_WORKERS} scan + {ONCHAIN_WORKERS} onchain")
    send(
        "🟢 *WHALE SNIPER PRO v5 — ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scan workers\n"
        f"🔬 `{ONCHAIN_WORKERS}` verificações on-chain paralelas\n"
        f"📨 Pipeline assíncrono 3 estágios\n"
        f"🔄 `{len(ENDPOINTS)}` endpoints simultâneos\n\n"
        "🎯 *Modo: CAPTURA PRECOCE + EQUILIBRADO*\n\n"
        "🛡️ *Filtros DEX:*\n"
        f"  🐋 Compras: `{MIN_WHALE_BUYS}–{MAX_WHALE_BUYS}` /5min\n"
        f"  📊 Ratio: `{MIN_BUY_SELL_RATIO}x–{MAX_BUY_SELL_RATIO}x`\n"
        f"  💧 Liq: `${MIN_LIQUIDITY:,}–${MAX_LIQUIDITY:,}` | Vol5m mín `${MIN_VOLUME_M5:,}`\n"
        f"  📈 Var 1h: `{MIN_PRICE_CHANGE_H1:.0f}%–{MAX_PRICE_CHANGE_H1:.0f}%` (aceita 0%)\n"
        f"  ⚡ Var 5m: `{MIN_PRICE_CHANGE_M5:.0f}%–{MAX_PRICE_CHANGE_M5:.0f}%`\n"
        f"  ⏰ Idade: `{MIN_AGE_MINUTES}–{MAX_AGE_MINUTES} min` (janela fechada)\n\n"
        "🔬 *Verificação on-chain GMGN:*\n"
        "  🍯 Honeypot | 🔒 LP lock | 👥 Holders\n"
        "  💸 Taxas | 👨‍💻 Dev holding | 🧠 Smart money\n\n"
        "📢 Relatório a cada 2h"
    )

    # Inicia workers de scan
    for i in range(SCAN_WORKERS):
        t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
        t.start()
        time.sleep(0.03)

    # Inicia workers on-chain
    for i in range(ONCHAIN_WORKERS):
        t = threading.Thread(target=onchain_worker, daemon=True)
        t.start()
        time.sleep(0.03)

    # Inicia sender TG
    threading.Thread(target=telegram_sender, daemon=True).start()

    # Mantém thread principal viva
    while True:
        time.sleep(60)

# ============================================================
# MONITOR DE SAÍDA — a cada 3 min
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
                        f"📉 Variação: `{pct:+.1f}%`\n"
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

def fetch_batch_prices(batch_addrs):
    try:
        r = requests.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{','.join(batch_addrs)}",
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
                snapshot = dict(monitored_tokens)
                stats    = dict(report_stats)
                report_stats.update({"sent": 0, "green": 0,
                                     "yellow": 0, "red": 0, "blocked": 0})

            if not snapshot:
                send("📊 *RELATÓRIO 2H*\nNenhum token alertado no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs   = list(snapshot.keys())
            batches = [addrs[i:i+30] for i in range(0, len(addrs), 30)]
            current_prices = {}
            with ThreadPoolExecutor(max_workers=4) as ex:
                for f in as_completed([ex.submit(fetch_batch_prices, b) for b in batches]):
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
            total    = len(winners) + len(losers)
            hit_rate = (len(winners) / total * 100) if total else 0
            now      = datetime.utcnow().strftime("%d/%m %H:%M UTC")

            report = (
                f"📊 *RELATÓRIO — {now}*\n"
                f"{'─' * 30}\n"
                f"📤 Alertas: `{stats['sent']}` | "
                f"🚫 Bloqueados: `{stats.get('blocked',0)}`\n"
                f"🟢`{stats['green']}` 🟡`{stats['yellow']}` 🔴`{stats['red']}`\n"
                f"🎯 Acerto: `{hit_rate:.0f}%` "
                f"(`{len(winners)}` ↑ / `{len(losers)}` ↓)\n"
                f"{'─' * 30}\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, _, __, sig, sc in winners[:15]:
                    icon   = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    blocks = "█" * min(int(abs(pct) / 20), 8)
                    report += f"  {icon} `{pct:+6.1f}%` {blocks} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, _, __, sig, sc in losers[:8]:
                    icon = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    report += f"  {icon} `{pct:+6.1f}%` *${sym}*\n"
                report += "\n"

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
            f"WHALE SNIPER PRO v5 | "
            f"Alertas: {len(monitored_tokens)} | "
            f"Fila onchain: {onchain_queue.qsize()} | "
            f"Fila TG: {alert_queue.qsize()} | "
            f"Bloqueados: {report_stats.get('blocked',0)} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
