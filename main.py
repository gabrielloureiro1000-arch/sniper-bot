import os
import time
import threading
import requests
import telebot
from flask import Flask
from datetime import datetime
from queue import Queue, Empty

# ============================================================
# CONFIGURAÇÃO
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# FILTROS — SIMPLES E FUNCIONAIS
# Baseado no código institucional que funcionava
# ============================================================
MIN_LIQ      = 15_000   # liquidez mínima segura
MAX_LIQ      = 500_000  # acima = já foi
MIN_BUYS     = 10       # baleias entrando
MAX_BUYS     = 1000     # anti-bot
MIN_RATIO    = 1.5      # compras > vendas
MIN_SELLS    = 2        # mercado real
MIN_VOL      = 800      # volume mínimo
MIN_AGE      = 2        # evita rug dos primeiros segundos
MAX_AGE      = 60       # janela de 1 hora
MIN_M5       = 1.0      # subindo em 5min
MAX_M5       = 40.0     # não muito violento
MIN_H1       = 1.0      # tendência positiva
MAX_H1       = 200.0    # ainda tem espaço

REPORT_INTERVAL = 7_200  # 2 horas

ENDPOINTS = [
    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=sol+pump",
    "https://api.dexscreener.com/latest/dex/search?q=sol+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+hot",
    "https://api.dexscreener.com/latest/dex/search?q=sol+gem",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
]

# ============================================================
# ESTADO
# ============================================================
seen      = set()
history   = {}   # addr -> {symbol, price, time, signal}
stats     = {"sent": 0, "green": 0, "yellow": 0, "red": 0}
lock      = threading.Lock()
tg_queue  = Queue()

# ============================================================
# TELEGRAM
# ============================================================

def tg_worker():
    while True:
        try:
            msg = tg_queue.get(timeout=5)
            for _ in range(3):
                try:
                    bot.send_message(CHAT_ID, msg,
                        parse_mode="Markdown",
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
# GMGN — só informação extra, nunca bloqueia
# ============================================================

def get_gmgn(addr):
    try:
        r = requests.get(
            f"https://gmgn.ai/api/v1/token/sol/{addr}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gmgn.ai/"},
            timeout=4
        )
        if r.status_code != 200:
            return {}
        d = r.json().get("data", {}) or {}
        return {
            "smart":   d.get("smart_degen_count", 0) or 0,
            "holders": d.get("holder_count",       0) or 0,
            "top10":   d.get("top10_holder_rate",   0) or 0,
            "lp":      d.get("burn_ratio",          0) or 0,
            "hp":      d.get("is_honeypot",     False),
            "tax":     d.get("sell_tax",            0) or 0,
            "rug":     d.get("rug_ratio",           0) or 0,
        }
    except:
        return {}

def is_lixo(g):
    """Bloqueia SOMENTE lixo confirmado 100%."""
    if g.get("hp") is True:          return True, "HONEYPOT"
    if g.get("rug", 0) > 0.85:       return True, f"RUG {g['rug']:.0%}"
    if g.get("tax", 0) > 25:         return True, f"SELL TAX {g['tax']:.0f}%"
    top10 = g.get("top10", 0)
    if top10 > 0:
        t = float(top10)*100 if float(top10) <= 1 else float(top10)
        if t > 85:                   return True, f"TOP10 {t:.0f}%"
    return False, ""

# ============================================================
# SINAL DE RISCO
# ============================================================

def sinal(data, g):
    """
    🟢 Verde  = baixo risco, entre com confiança
    🟡 Amarelo = atenção, use stop loss
    🔴 Vermelho = cuidado, alto risco
    """
    pontos = 0

    # Positivos
    if data["ratio"] >= 4:    pontos += 3
    elif data["ratio"] >= 2:  pontos += 2
    else:                     pontos += 1

    if data["buys"] >= 30:    pontos += 3
    elif data["buys"] >= 15:  pontos += 2
    else:                     pontos += 1

    if data["age"] <= 15:     pontos += 3
    elif data["age"] <= 30:   pontos += 2
    else:                     pontos += 1

    if data["h1"] <= 30:      pontos += 3  # ainda no início
    elif data["h1"] <= 70:    pontos += 2
    else:                     pontos += 1

    vol_accel = 0
    if data["vol1h"] > 0:
        vol_accel = data["vol5m"] / max(data["vol1h"] / 12, 1)
    if vol_accel >= 3:        pontos += 3
    elif vol_accel >= 1.5:    pontos += 2
    else:                     pontos += 1

    # Bônus GMGN
    smart = g.get("smart", 0)
    if smart >= 3:            pontos += 4
    elif smart >= 1:          pontos += 2

    lp = g.get("lp", 0)
    if lp > 0:
        lp_pct = float(lp)*100 if float(lp) <= 1 else float(lp)
        if lp_pct >= 80:      pontos += 2
        elif lp_pct >= 50:    pontos += 1
        else:                 pontos -= 2

    top10 = g.get("top10", 0)
    if top10 > 0:
        t = float(top10)*100 if float(top10) <= 1 else float(top10)
        if t > 50:            pontos -= 2
        elif t <= 30:         pontos += 1

    # Decisão
    if pontos >= 16:
        return "🟢", "VERDE — SEGURO", "Baixo risco — boa janela de entrada"
    elif pontos >= 11:
        return "🟡", "AMARELO — ATENÇÃO", "Risco moderado — use stop loss"
    else:
        return "🔴", "VERMELHO — CUIDADO", "Alto risco — entre pequeno ou evite"

# ============================================================
# PROCESSAMENTO
# ============================================================

def processar(pair):
    if pair.get("chainId") != "solana":
        return

    base  = pair.get("baseToken", {})
    addr  = base.get("address")
    if not addr or addr in seen:
        return

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
    dex   = pair.get("dexId", "dex")

    created = pair.get("pairCreatedAt")
    age     = ((time.time()*1000 - created)/60_000) if created else 999

    if not price: return

    # ── FILTROS ──────────────────────────────────────────
    if liq   < MIN_LIQ  or liq > MAX_LIQ:   return
    if buys  < MIN_BUYS or buys > MAX_BUYS:  return
    if ratio < MIN_RATIO:                    return
    if sells < MIN_SELLS:                    return
    if vol5m < MIN_VOL:                      return
    if age   < MIN_AGE  or age > MAX_AGE:    return
    if m5    < MIN_M5   or m5 > MAX_M5:      return
    if h1    < MIN_H1   or h1 > MAX_H1:      return
    if sells > 0 and sells/buys < 0.08:      return  # anti-bot

    price = float(price)

    with lock:
        if addr in seen:
            return
        seen.add(addr)

    # GMGN — bônus, nunca bloqueia se falhar
    g = get_gmgn(addr)
    lixo, motivo = is_lixo(g)
    if lixo:
        print(f"[LIXO] ${base.get('symbol','?')} — {motivo}")
        return

    emoji, label, desc = sinal({"ratio": ratio, "buys": buys, "age": age,
                                  "h1": h1, "vol5m": vol5m, "vol1h": vol1h}, g)
    symbol = base.get("symbol", "???")

    with lock:
        history[addr] = {
            "symbol": symbol, "price": price,
            "time":   datetime.utcnow().strftime("%H:%M UTC"),
            "signal": label,
        }
        stats["sent"] += 1
        if "VERDE"  in label: stats["green"]  += 1
        elif "AMAR" in label: stats["yellow"] += 1
        else:                 stats["red"]    += 1

    # Pontos de saída
    empate = price * 1.035   # +3.5% cobre taxas
    alvo1  = price * 1.30    # +30%
    alvo2  = price * 1.70    # +70%
    stop   = price * 0.85    # -15%

    # Barra de força
    forca  = min(int(ratio), 10)
    barra  = "🟢" * forca + "⚪" * (10 - forca)

    # Info GMGN
    smart  = g.get("smart", 0)
    hlds   = g.get("holders", 0)
    lp     = g.get("lp", 0)
    lp_pct = (float(lp)*100 if float(lp) <= 1 else float(lp)) if lp else 0

    info_gmgn = ""
    if smart > 0:  info_gmgn += f"🧠 Smart Money: `{smart} wallets`\n"
    if hlds  > 0:  info_gmgn += f"👥 Holders: `{hlds}`\n"
    if lp_pct > 0: info_gmgn += f"🔒 LP queimada: `{lp_pct:.0f}%`\n"
    if not info_gmgn: info_gmgn = "🔬 GMGN: `verificando dados...`\n"

    msg = (
        f"{emoji} *{label}*\n"
        f"_{desc}_\n\n"
        f"💎 *${symbol}*  —  `{dex.upper()}`\n"
        f"📄 `{addr}`\n\n"
        f"💲 Entrada: `${price:.10f}`\n"
        f"📈 5min: `{m5:+.1f}%`  |  1h: `{h1:+.1f}%`\n"
        f"💧 Liq: `${liq:,.0f}`\n"
        f"📊 Vol 5m: `${vol5m:,.0f}`\n"
        f"🔥 Compras: `{buys}` | Vendas: `{sells}` | Ratio: `{ratio:.1f}x`\n"
        f"⏰ Idade: `{age:.0f} min`\n"
        f"{info_gmgn}\n"
        f"💪 Força: {barra}\n\n"
        f"━━━ 💰 PONTOS DE SAÍDA ━━━\n"
        f"⚖️ Sem prejuízo: `${empate:.10f}` *(+3.5%)*\n"
        f"🎯 Alvo 1: `${alvo1:.10f}` *(+30%)*\n"
        f"🚀 Alvo 2: `${alvo2:.10f}` *(+70%)*\n"
        f"🛑 Stop loss: `${stop:.10f}` *(-15%)*\n\n"
        f"🔗 [GMGN](https://gmgn.ai/sol/token/{addr})  "
        f"[DEX](https://dexscreener.com/solana/{addr})  "
        f"[PUMP](https://pump.fun/{addr})\n"
        f"⚡ [COMPRAR TROJAN](https://t.me/solana_trojan_bot?start=r-user_{addr})"
    )
    send(msg)

# ============================================================
# SCAN — simples e rápido
# ============================================================

def scan():
    global seen
    idx = 0
    while True:
        url = ENDPOINTS[idx % len(ENDPOINTS)]
        idx += 1
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                for pair in (r.json().get("pairs") or []):
                    processar(pair)
        except:
            pass
        if len(seen) > 20_000:
            seen = set(list(seen)[-10_000:])
        time.sleep(0.3)

# ============================================================
# MONITOR DE SAÍDA — a cada 2 min
# ============================================================

def monitor_saida():
    time.sleep(120)
    while True:
        try:
            with lock:
                check = {k: v for k, v in history.items()
                         if not v.get("saiu")}
            if not check:
                time.sleep(120)
                continue

            addrs = list(check.keys())
            precos = {}
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
                            precos[a] = {"price": float(v), "sells": s}
                except:
                    pass

            for addr, info in check.items():
                d = precos.get(addr)
                if not d or info["price"] <= 0:
                    continue
                pct   = ((d["price"] - info["price"]) / info["price"]) * 100
                sells = d["sells"]
                msg   = None

                if pct <= -15:
                    msg = (
                        f"🚨 *STOP LOSS — SAIA AGORA*\n\n"
                        f"💎 *${info['symbol']}* caiu `{pct:.1f}%`\n"
                        f"📉 Entrada: `${info['price']:.10f}`\n"
                        f"📉 Atual:   `${d['price']:.10f}`\n"
                        f"⚠️ *Limite atingido — proteja seu capital!*\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif pct >= 30:
                    msg = (
                        f"🤑 *TAKE PROFIT — REALIZE LUCRO*\n\n"
                        f"💎 *${info['symbol']}* subiu `+{pct:.1f}%`\n"
                        f"📈 Entrada: `${info['price']:.10f}`\n"
                        f"📈 Atual:   `${d['price']:.10f}`\n"
                        f"💡 Venda 50% agora e deixe o resto correr!\n\n"
                        f"⚡ [VENDER NO TROJAN](https://t.me/solana_trojan_bot)"
                    )
                elif sells > 40 and pct < -5:
                    msg = (
                        f"⚠️ *DUMP DETECTADO*\n\n"
                        f"💎 *${info['symbol']}* — `{sells}` vendas/5min\n"
                        f"📉 Desde alerta: `{pct:+.1f}%`\n"
                        f"🔍 Considere sair!\n\n"
                        f"🔗 [DEX](https://dexscreener.com/solana/{addr})"
                    )

                if msg:
                    send(msg)
                    with lock:
                        if addr in history:
                            history[addr]["saiu"] = True

        except Exception as e:
            print(f"[SAIDA] {e}")
        time.sleep(120)

# ============================================================
# RELATÓRIO 2H
# ============================================================

def relatorio():
    time.sleep(REPORT_INTERVAL)
    while True:
        try:
            with lock:
                snap  = dict(history)
                st    = dict(stats)
                stats.update({"sent": 0, "green": 0, "yellow": 0, "red": 0})

            if not snap:
                send("📊 *RELATÓRIO 2H*\nNenhum token no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs = list(snap.keys())
            precos = {}
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                try:
                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=10)
                    for p in (r.json().get("pairs") or []):
                        a = p.get("baseToken", {}).get("address")
                        v = p.get("priceUsd")
                        if a and v:
                            precos[a] = float(v)
                except:
                    pass

            ganhos, perdas, sem_dado = [], [], []
            for addr, info in snap.items():
                cur = precos.get(addr, 0)
                if cur > 0 and info["price"] > 0:
                    pct = ((cur - info["price"]) / info["price"]) * 100
                    row = (pct, info["symbol"], info.get("signal",""))
                    (ganhos if pct >= 0 else perdas).append(row)
                else:
                    sem_dado.append(info["symbol"])

            ganhos.sort(reverse=True)
            perdas.sort()
            total    = len(ganhos) + len(perdas)
            acerto   = (len(ganhos) / total * 100) if total else 0
            now      = datetime.utcnow().strftime("%d/%m %H:%M UTC")

            txt = (
                f"📊 *RELATÓRIO — {now}*\n"
                f"{'─'*28}\n"
                f"📤 Alertas: `{st['sent']}` | "
                f"🟢`{st['green']}` 🟡`{st['yellow']}` 🔴`{st['red']}`\n"
                f"🎯 Acerto: `{acerto:.0f}%` (`{len(ganhos)}` ↑ / `{len(perdas)}` ↓)\n"
                f"{'─'*28}\n\n"
            )

            if ganhos:
                txt += f"🚀 *SUBIRAM ({len(ganhos)})*\n"
                for pct, sym, sig in ganhos[:15]:
                    ic = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    bl = "█" * min(int(abs(pct)/15), 8)
                    txt += f"  {ic} `{pct:+6.1f}%` {bl} *${sym}*\n"
                txt += "\n"

            if perdas:
                txt += f"🔻 *CAÍRAM ({len(perdas)})*\n"
                for pct, sym, sig in perdas[:8]:
                    ic = "🟢" if "VERDE" in sig else ("🟡" if "AMAR" in sig else "🔴")
                    txt += f"  {ic} `{pct:+6.1f}%` *${sym}*\n"
                txt += "\n"

            if sem_dado:
                txt += f"❓ Sem dados: {', '.join('$'+s for s in sem_dado[:5])}\n"
            if ganhos:
                txt += f"\n🏆 *Melhor:* `${ganhos[0][1]}` → `{ganhos[0][0]:+.1f}%`"
            if perdas:
                txt += f"\n💀 *Pior:*   `${perdas[0][1]}` → `{perdas[0][0]:+.1f}%`"

            send(txt)

            with lock:
                if len(history) > 200:
                    for k in list(history.keys())[:-200]:
                        del history[k]

        except Exception as e:
            print(f"[RELATORIO] {e}")
        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH
# ============================================================

@app.route("/")
def health():
    return (f"WHALE SNIPER | tokens={len(history)} | "
            f"fila={tg_queue.qsize()} | "
            f"🟢{stats['green']} 🟡{stats['yellow']} 🔴{stats['red']}")

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    send(
        "🟢 *WHALE SNIPER — ONLINE*\n\n"
        f"🔄 {len(ENDPOINTS)} endpoints em loop\n"
        f"🐋 Mín `{MIN_BUYS}` compras/5min\n"
        f"📊 Ratio mín `{MIN_RATIO}x`\n"
        f"💧 Liq `${MIN_LIQ:,}–${MAX_LIQ:,}`\n"
        f"📈 Var 5m `{MIN_M5:.0f}%–{MAX_M5:.0f}%` | 1h `{MIN_H1:.0f}%–{MAX_H1:.0f}%`\n"
        f"⏰ Idade `{MIN_AGE}–{MAX_AGE} min`\n\n"
        "🟢 Verde = seguro | 🟡 Amarelo = atenção | 🔴 Vermelho = cuidado\n"
        "💰 Cada alerta traz pontos de saída\n"
        "📢 Relatório a cada 2h"
    )

    threading.Thread(target=tg_worker,     daemon=True).start()
    threading.Thread(target=monitor_saida, daemon=True).start()
    threading.Thread(target=relatorio,     daemon=True).start()

    # 6 threads de scan paralelas
    for i in range(6):
        threading.Thread(target=scan, daemon=True).start()
        time.sleep(0.1)

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
