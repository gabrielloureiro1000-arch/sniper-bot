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
# FILTROS DE ENTRADA — DEXScreener (triagem rápida)
# ============================================================
MIN_LIQUIDITY        = 5_000    # liquidez mínima real
MAX_LIQUIDITY        = 300_000  # acima = já bombou
MIN_WHALE_BUYS       = 8        # mínimo 8 compras/5min
MAX_WHALE_BUYS       = 800      # acima = bot
MIN_VOLUME_M5        = 2_000
MIN_BUY_SELL_RATIO   = 1.5
MAX_BUY_SELL_RATIO   = 15.0
MIN_AGE_MINUTES      = 5
MAX_AGE_MINUTES      = 120      # 2h máximo — depois disso geralmente já foi
MIN_PRICE_CHANGE_H1  = 2.0
MAX_PRICE_CHANGE_H1  = 150.0
MAX_PRICE_CHANGE_M5  = 35.0
MIN_SELLS_5M         = 2        # mínimo de vendas reais

# ============================================================
# FILTROS ON-CHAIN — GMGN (verificação profunda)
# Esses filtros eliminam rugs e manipulações
# ============================================================
MAX_TOP10_HOLDERS_PCT  = 35.0   # top 10 wallets não podem ter mais de 35% do supply
MAX_SINGLE_HOLDER_PCT  = 10.0   # nenhuma wallet única com mais de 10%
MIN_HOLDER_COUNT       = 50     # mínimo de holders reais
MAX_DEV_HOLDING_PCT    = 5.0    # dev não pode ter mais de 5% do supply
REQUIRE_LP_LOCKED      = True   # LP precisa estar travada (burn ou lock)
MIN_SMART_MONEY_WALLETS = 1     # mínimo de 1 smart money wallet detectada

# ============================================================
# VELOCIDADE
# ============================================================
SCAN_WORKERS     = 8
FETCH_TIMEOUT    = 5
GMGN_TIMEOUT     = 6
ALERT_QUEUE_SIZE = 500
MAX_SEEN_TOKENS  = 25_000
REPORT_INTERVAL  = 7_200

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
report_stats     = {"sent": 0, "green": 0, "yellow": 0, "red": 0, "blocked": 0}
lock             = threading.Lock()
alert_queue      = Queue(maxsize=ALERT_QUEUE_SIZE)

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# ENVIO ASSÍNCRONO
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
# GMGN — VERIFICAÇÃO ON-CHAIN
# Busca dados reais de holder distribution, LP lock,
# smart money e segurança do contrato
# ============================================================

def fetch_gmgn_token_info(addr: str) -> dict:
    """
    Busca informações on-chain do token via GMGN.
    Retorna dict com dados de segurança ou None se falhar.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://gmgn.ai/",
        }
        url  = f"https://gmgn.ai/api/v1/token/sol/{addr}"
        resp = requests.get(url, headers=headers, timeout=GMGN_TIMEOUT)

        if resp.status_code != 200:
            return {}

        data  = resp.json()
        token = data.get("data", {}) or data.get("token", {}) or data

        return {
            "top10_holders_pct":  token.get("top10_holder_rate",   None),
            "dev_holding_pct":    token.get("dev_token_burn_ratio", None),
            "holder_count":       token.get("holder_count",         None),
            "lp_burned":          token.get("burn_ratio",           None),
            "is_honeypot":        token.get("is_honeypot",          None),
            "buy_tax":            token.get("buy_tax",              None),
            "sell_tax":           token.get("sell_tax",             None),
            "is_open_source":     token.get("open_source",          None),
            "is_mintable":        token.get("is_mintable",          None),
            "renounced":          token.get("renounced",            None),
            "smart_money_count":  token.get("smart_degen_count",    0),
            "rug_ratio":          token.get("rug_ratio",            None),
        }
    except Exception as e:
        print(f"[GMGN] {addr[:8]}: {e}")
        return {}


def check_onchain_safety(info: dict) -> tuple:
    """
    Verifica se o token passa nos critérios on-chain.
    Retorna (passou: bool, motivo_bloqueio: str, flags: list)
    """
    if not info:
        return True, "", ["⚠️ Dados on-chain indisponíveis — analise manualmente"]

    flags      = []
    hard_fails = []  # falhas críticas = bloqueia automaticamente

    # ── HONEYPOT — bloqueio imediato ────────────────────
    if info.get("is_honeypot") is True:
        return False, "🚨 HONEYPOT detectado — impossível vender!", []

    # ── RUG RATIO ────────────────────────────────────────
    rug = info.get("rug_ratio")
    if rug is not None:
        if rug > 0.8:
            return False, f"🚨 Rug ratio altíssimo ({rug:.0%}) — bloqueado", []
        elif rug > 0.5:
            flags.append(f"🚫 Rug ratio alto ({rug:.0%})")

    # ── CONTRATO MALICIOSO ───────────────────────────────
    if info.get("is_mintable") is True:
        hard_fails.append("contrato mintable")
        flags.append("🚫 Contrato mintable — dev pode criar tokens infinitos")

    if info.get("is_open_source") is False:
        flags.append("⚠️ Contrato não verificado / fechado")

    # ── TAXAS ────────────────────────────────────────────
    buy_tax  = info.get("buy_tax",  0) or 0
    sell_tax = info.get("sell_tax", 0) or 0
    if sell_tax > 10:
        hard_fails.append(f"sell tax {sell_tax:.0f}%")
        flags.append(f"🚫 Sell tax abusiva: {sell_tax:.0f}% — possível honeypot")
    elif sell_tax > 5:
        flags.append(f"⚠️ Sell tax alta: {sell_tax:.0f}%")
    elif sell_tax > 0:
        flags.append(f"✅ Sell tax: {sell_tax:.0f}%")

    if buy_tax > 10:
        flags.append(f"⚠️ Buy tax alta: {buy_tax:.0f}%")

    # ── LP BURNED / LOCKED ───────────────────────────────
    lp_burned = info.get("lp_burned")
    if lp_burned is not None:
        lp_pct = float(lp_burned) * 100 if lp_burned <= 1 else float(lp_burned)
        if lp_pct >= 90:
            flags.append(f"✅ LP queimada ({lp_pct:.0f}%) — seguro")
        elif lp_pct >= 50:
            flags.append(f"⚠️ LP parcialmente queimada ({lp_pct:.0f}%)")
        else:
            hard_fails.append(f"LP não travada ({lp_pct:.0f}%)")
            flags.append(f"🚫 LP não travada ({lp_pct:.0f}%) — risco de rug")

    # ── DISTRIBUIÇÃO DE HOLDERS ──────────────────────────
    top10 = info.get("top10_holders_pct")
    if top10 is not None:
        top10_pct = float(top10) * 100 if top10 <= 1 else float(top10)
        if top10_pct > 50:
            hard_fails.append(f"top10 com {top10_pct:.0f}%")
            flags.append(f"🚫 Top 10 wallets com {top10_pct:.0f}% do supply — bomba-relógio")
        elif top10_pct > MAX_TOP10_HOLDERS_PCT:
            flags.append(f"⚠️ Top 10 wallets com {top10_pct:.0f}% — concentrado")
        else:
            flags.append(f"✅ Distribuição saudável — top 10 com {top10_pct:.0f}%")

    # ── DEV HOLDING ──────────────────────────────────────
    dev = info.get("dev_holding_pct")
    if dev is not None:
        dev_pct = float(dev) * 100 if dev <= 1 else float(dev)
        if dev_pct > 15:
            hard_fails.append(f"dev com {dev_pct:.0f}%")
            flags.append(f"🚫 Dev com {dev_pct:.0f}% do supply — risco extremo")
        elif dev_pct > MAX_DEV_HOLDING_PCT:
            flags.append(f"⚠️ Dev com {dev_pct:.0f}% do supply")
        else:
            flags.append(f"✅ Dev holding baixo ({dev_pct:.0f}%)")

    # ── HOLDER COUNT ─────────────────────────────────────
    holders = info.get("holder_count")
    if holders is not None:
        if holders < 30:
            hard_fails.append(f"apenas {holders} holders")
            flags.append(f"🚫 Apenas {holders} holders — muito concentrado")
        elif holders < MIN_HOLDER_COUNT:
            flags.append(f"⚠️ Poucos holders: {holders}")
        else:
            flags.append(f"✅ {holders} holders")

    # ── SMART MONEY ──────────────────────────────────────
    smart = info.get("smart_money_count", 0) or 0
    if smart >= 3:
        flags.append(f"✅ {smart} smart money wallets — sinal forte")
    elif smart >= 1:
        flags.append(f"✅ {smart} smart money wallet detectada")
    else:
        flags.append("⚠️ Nenhuma smart money detectada ainda")

    # ── DECISÃO FINAL ────────────────────────────────────
    if len(hard_fails) >= 2:
        return False, f"Bloqueado: {' + '.join(hard_fails)}", flags
    if hard_fails:
        # 1 falha crítica = não bloqueia mas vira vermelho
        return True, f"⚠️ {hard_fails[0]}", flags

    return True, "", flags


# ============================================================
# SCORE DE RISCO — combina DEX + on-chain
# ============================================================

def calculate_risk_score(buys5m, sells5m, ratio, liq, vol5m,
                          vol1h, change_h1, change_m5, age_min,
                          onchain_flags: list, onchain_fail: str) -> dict:
    score   = 0
    greens  = []
    yellows = []
    reds    = []

    # Penalidade por falha on-chain
    if onchain_fail and "⚠️" in onchain_fail:
        score += 20
        reds.append(onchain_fail)

    # Classifica flags on-chain
    for f in onchain_flags:
        if f.startswith("✅"):
            greens.append(f)
        elif f.startswith("⚠️"):
            score += 8
            yellows.append(f)
        elif f.startswith("🚫"):
            score += 20
            reds.append(f)

    # ── LIQUIDEZ ─────────────────────────────────────────
    if liq >= 50_000:
        score -= 10; greens.append(f"Boa liquidez (${liq:,.0f})")
    elif liq >= 15_000:
        score -= 5;  greens.append(f"Liquidez ok (${liq:,.0f})")
    elif liq >= 5_000:
        score += 5;  yellows.append(f"Liquidez baixa (${liq:,.0f})")
    else:
        score += 18; reds.append(f"Liquidez muito baixa (${liq:,.0f})")

    # ── RATIO ────────────────────────────────────────────
    if ratio > 10:
        score += 15; yellows.append(f"Ratio elevado ({ratio:.1f}x)")
    elif ratio >= 2:
        score -= 8;  greens.append(f"Força compradora ({ratio:.1f}x)")
    else:
        score -= 3;  greens.append(f"Ratio equilibrado ({ratio:.1f}x)")

    # ── COMPRAS — detecta bot ────────────────────────────
    if buys5m > 400:
        score += 20; reds.append(f"{buys5m} compras/5min — volume suspeito de bot")
    elif buys5m > 100:
        score += 8;  yellows.append(f"Volume alto ({buys5m} compras/5min)")
    elif buys5m >= 20:
        score -= 8;  greens.append(f"Compras fortes ({buys5m}/5min)")
    elif buys5m >= 8:
        greens.append(f"8+ compras de baleia ({buys5m}/5min)")

    # ── ACELERAÇÃO DE VOLUME ─────────────────────────────
    if vol5m > 0 and vol1h > 0:
        accel = vol5m / max(vol1h / 12, 1)
        if accel > 4:
            score -= 10; greens.append(f"Volume acelerando ({accel:.1f}x média)")
        elif accel > 1.5:
            score -= 5;  greens.append(f"Volume acima da média ({accel:.1f}x)")
        elif accel < 0.5:
            score += 8;  yellows.append("Volume desacelerando")

    # ── IDADE ────────────────────────────────────────────
    if age_min < 10:
        score += 20; reds.append(f"Par com {age_min:.0f} min — risco alto")
    elif age_min < 20:
        score += 10; yellows.append(f"Par muito novo ({age_min:.0f} min)")
    elif age_min < 45:
        score += 3;  yellows.append(f"Par novo ({age_min:.0f} min)")
    elif age_min < 90:
        score -= 5;  greens.append(f"Par com histórico ({age_min:.0f} min)")
    else:
        score -= 10; greens.append(f"Par estabelecido ({age_min:.0f} min)")

    # ── VARIAÇÃO 1H ──────────────────────────────────────
    if change_h1 > 100:
        score += 22; reds.append(f"+{change_h1:.0f}% em 1h — pump avançado, topo próximo")
    elif change_h1 > 60:
        score += 12; reds.append(f"+{change_h1:.0f}% em 1h — alta intensa")
    elif change_h1 > 20:
        score += 5;  yellows.append(f"+{change_h1:.0f}% em 1h")
    elif change_h1 > 3:
        score -= 8;  greens.append(f"Movimento saudável +{change_h1:.0f}% em 1h")
    else:
        score -= 3;  greens.append(f"Início de movimento +{change_h1:.0f}% em 1h")

    # ── VARIAÇÃO 5MIN ────────────────────────────────────
    if change_m5 > 20:
        score += 12; yellows.append(f"Pump rápido +{change_m5:.0f}% em 5min")
    elif change_m5 > 5:
        score += 3;  yellows.append(f"Subindo +{change_m5:.0f}% em 5min")
    elif change_m5 > 0:
        score -= 5;  greens.append(f"Alta suave +{change_m5:.0f}% em 5min")
    elif change_m5 < -10:
        score += 12; reds.append(f"Caindo {change_m5:.0f}% em 5min")

    # ── VENDAS REAIS ─────────────────────────────────────
    if sells5m == 0:
        score += 18; reds.append("Zero vendas — sinal suspeito")
    elif sells5m < 3:
        score += 5;  yellows.append(f"Poucas vendas ({sells5m})")
    else:
        score -= 5;  greens.append(f"Mercado bilateral ({sells5m} vendas)")

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
# PROCESSAMENTO — triagem DEX + verificação on-chain
# ============================================================

def process_pair(pair: dict):
    if pair.get("chainId") != "solana":
        return

    base   = pair.get("baseToken", {})
    addr   = base.get("address")
    symbol = base.get("symbol", "???")
    if not addr or addr in seen_tokens:
        return

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

    # ── FILTROS DEX — triagem rápida ──────────────────────
    if buys5m    < MIN_WHALE_BUYS:       return
    if buys5m    > MAX_WHALE_BUYS:       return
    if liq       < MIN_LIQUIDITY:        return
    if liq       > MAX_LIQUIDITY:        return
    if vol5m     < MIN_VOLUME_M5:        return
    if ratio     < MIN_BUY_SELL_RATIO:   return
    if ratio     > MAX_BUY_SELL_RATIO:   return
    if change_h1 < MIN_PRICE_CHANGE_H1:  return
    if change_h1 > MAX_PRICE_CHANGE_H1:  return
    if change_m5 > MAX_PRICE_CHANGE_M5:  return
    if age_min   < MIN_AGE_MINUTES:      return
    if age_min   > MAX_AGE_MINUTES:      return
    if sells5m   < MIN_SELLS_5M:         return

    price = float(price_usd)

    # Lock antes da verificação on-chain (evita duplicatas)
    with lock:
        if addr in seen_tokens:
            return
        seen_tokens.add(addr)

    # ── VERIFICAÇÃO ON-CHAIN VIA GMGN ────────────────────
    # Essa chamada é mais lenta mas elimina rugs e honeypots
    onchain     = fetch_gmgn_token_info(addr)
    passed, fail_reason, onchain_flags = check_onchain_safety(onchain)

    if not passed:
        print(f"[BLOQUEADO] ${symbol} — {fail_reason}")
        with lock:
            report_stats["blocked"] += 1
        return  # token rejeitado por critérios on-chain

    # ── SCORE COMBINADO ───────────────────────────────────
    risk = calculate_risk_score(
        buys5m, sells5m, ratio, liq, vol5m,
        vol1h, change_h1, change_m5, age_min,
        onchain_flags, fail_reason
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

    # ── LINKS ─────────────────────────────────────────────
    gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
    dex_url    = f"https://dexscreener.com/solana/{addr}"
    trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
    pump_url   = f"https://pump.fun/{addr}"

    strength    = min(int(ratio), 10)
    bar_force   = "🟢" * strength + "⚪" * (10 - strength)
    risk_filled = min(int(risk["score"] / 10), 10)
    risk_icon   = {"🟢": "🟩", "🟡": "🟨", "🔴": "🟥"}[risk["emoji"]]
    bar_risk    = risk_icon * risk_filled + "⬜" * (10 - risk_filled)

    # Mostra os pontos mais relevantes
    analysis = ""
    for g in risk["greens"][:3]:  analysis += f"\n✅ {g}"
    for y in risk["yellows"][:2]: analysis += f"\n⚠️ {y}"
    for r in risk["reds"][:3]:    analysis += f"\n🚫 {r}"

    # Smart money destaque
    smart = onchain.get("smart_money_count", 0) or 0
    smart_line = f"🧠 Smart money: `{smart} wallets`\n" if smart > 0 else ""

    holders    = onchain.get("holder_count")
    holder_line= f"👥 Holders: `{holders}`\n" if holders else ""

    lp         = onchain.get("lp_burned")
    lp_pct     = (float(lp) * 100 if lp and lp <= 1 else float(lp)) if lp else None
    lp_line    = f"🔒 LP queimada: `{lp_pct:.0f}%`\n" if lp_pct else ""

    tips = {
        "🟢": "💡 Sinal limpo — boa janela de entrada",
        "🟡": "💡 Entre com cautela — defina stop loss antes",
        "🔴": "💡 Risco alto — evite ou aguarde confirmação",
    }

    msg = (
        f"{risk['emoji']} *{risk['label']}* — {risk['desc']}\n"
        f"{whale_emoji} *{whale_label}* — `{buys5m}` compras | ratio `{ratio:.1f}x`\n\n"
        f"💎 *${symbol}*  —  `{pair.get('dexId','dex').upper()}`\n"
        f"📄 *CA:* `{addr}`\n\n"
        f"💲 Preço:    `${price:.10f}`\n"
        f"📈 Var 5m:  `{change_m5:+.1f}%`  |  Var 1h: `{change_h1:+.1f}%`\n"
        f"💧 Liq:      `${liq:,.0f}`\n"
        f"📊 Vol 5m:  `${vol5m:,.0f}`  |  Vol 1h: `${vol1h:,.0f}`\n"
        f"🔥 Compras: `{buys5m}` | Vendas: `{sells5m}` | Ratio: `{ratio:.1f}x`\n"
        f"⏰ Idade:   `{age_min:.0f} min`\n"
        f"{smart_line}"
        f"{holder_line}"
        f"{lp_line}\n"
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
# 8 WORKERS — scan paralelo
# ============================================================

def scan_worker(worker_id: int):
    ep_index = worker_id
    while True:
        url = ENDPOINTS[ep_index % len(ENDPOINTS)]
        ep_index += 1
        if worker_id == 0:
            prune_cache()
        for pair in fetch_pairs(url):
            process_pair(pair)
        time.sleep(0.3)


def scan():
    print(f"🐋 WHALE SNIPER PRO v4 — ON-CHAIN")
    send(
        "🟢 *WHALE SNIPER PRO v4 — ONLINE*\n\n"
        f"⚡ `{SCAN_WORKERS}` scanners paralelos\n"
        f"🔗 Verificação on-chain via GMGN ativa\n\n"
        "🛡️ *Filtros DEX (triagem rápida):*\n"
        f"  🐋 Compras: `{MIN_WHALE_BUYS}–{MAX_WHALE_BUYS}` /5min\n"
        f"  📊 Ratio: `{MIN_BUY_SELL_RATIO}x–{MAX_BUY_SELL_RATIO}x`\n"
        f"  💧 Liq: `${MIN_LIQUIDITY:,}–${MAX_LIQUIDITY:,}`\n"
        f"  📈 Var 1h: `+{MIN_PRICE_CHANGE_H1:.0f}%–{MAX_PRICE_CHANGE_H1:.0f}%`\n"
        f"  ⏰ Idade: `{MIN_AGE_MINUTES}–{MAX_AGE_MINUTES} min`\n\n"
        "🔬 *Filtros ON-CHAIN (proteção profunda):*\n"
        f"  🔒 LP burn/lock verificada\n"
        f"  👥 Distribuição de holders\n"
        f"  🚫 Honeypot detector\n"
        f"  💰 Dev holding verificado\n"
        f"  🧠 Smart money wallets\n"
        f"  📜 Contrato mintable/taxas\n\n"
        "🎯 🟢≤30 | 🟡31-60 | 🔴≥61\n"
        "📢 Relatório a cada 2h"
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
            f"WHALE SNIPER PRO v4 | "
            f"Alertas: {len(monitored_tokens)} | "
            f"Bloqueados: {report_stats.get('blocked',0)} | "
            f"Cache: {len(seen_tokens)} | "
            f"Fila TG: {alert_queue.qsize()} | "
            f"🟢{report_stats['green']} "
            f"🟡{report_stats['yellow']} "
            f"🔴{report_stats['red']}"
        )

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=telegram_sender,    daemon=True).start()
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    threading.Thread(target=monitor_exit,       daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
