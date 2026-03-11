import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# Filtros — ajuste via variáveis de ambiente no Render
MIN_SCORE     = int(os.getenv("MIN_SCORE", "60"))        # Score mínimo (0-100)
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "5000"))  # Liquidez mínima USD
MIN_VOLUME    = int(os.getenv("MIN_VOLUME", "10000"))    # Volume 24h mínimo USD
MIN_BUY_RATIO = float(os.getenv("MIN_BUY_RATIO", "2.0"))# Ratio compra/venda mínimo
MIN_BUYS      = int(os.getenv("MIN_BUYS", "50"))         # Mínimo de compras 24h
DEX_INTERVAL  = int(os.getenv("DEX_INTERVAL", "5"))
PUMP_INTERVAL = int(os.getenv("PUMP_INTERVAL", "10"))

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen   = set()
alerts = 0
stats  = {"compra": 0, "observar": 0, "ignorado": 0}


# ─── TELEGRAM ──────────────────────────────────────────────────────────────
def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print("telegram error:", e)


# ─── SCORE DE MOMENTUM ─────────────────────────────────────────────────────
#
# Foco em UMA coisa: tokens sendo comprados com intensidade REAL agora,
# com liquidez suficiente para entrar e sair sem perder no slippage.
#
def calcular_score(liq, vol, buys, sells, pc5m, pc1h, pc6h):
    score  = 0
    razoes = []
    riscos = []
    ratio  = buys / max(sells, 1)

    # 1. LIQUIDEZ — base de segurança para entrar e sair
    if liq >= 100_000:
        score += 25
        razoes.append("✅ Liquidez forte: ${:,.0f}".format(liq))
    elif liq >= 20_000:
        score += 15
        razoes.append("✅ Liquidez ok: ${:,.0f}".format(liq))
    elif liq >= 5_000:
        score += 5
        razoes.append("🟡 Liquidez baixa: ${:,.0f}".format(liq))
    else:
        riscos.append("🚨 Liquidez muito baixa — rug pull fácil")

    # 2. RATIO COMPRA/VENDA — intensidade real de compra
    if ratio >= 8:
        score += 30
        razoes.append("✅ Pressão de compra extrema: {:.1f}x".format(ratio))
    elif ratio >= 5:
        score += 22
        razoes.append("✅ Pressão de compra alta: {:.1f}x".format(ratio))
    elif ratio >= 2:
        score += 12
        razoes.append("🟡 Pressão de compra moderada: {:.1f}x".format(ratio))
    else:
        score -= 10
        riscos.append("⚠️ Ratio baixo ({:.1f}x) — sem interesse real".format(ratio))

    # 3. VOLUME vs LIQUIDEZ — momentum real vs liquidez parada
    vol_ratio = vol / max(liq, 1)
    if vol_ratio >= 5:
        score += 20
        razoes.append("✅ Volume 5x acima da liquidez — momentum forte")
    elif vol_ratio >= 2:
        score += 12
        razoes.append("✅ Volume 2x acima da liquidez")
    elif vol_ratio >= 1:
        score += 5
        razoes.append("🟡 Volume similar à liquidez")
    else:
        riscos.append("⚠️ Volume baixo para a liquidez — pouco interesse")

    # 4. NÚMERO DE COMPRAS — evita volume artificial com poucas txns grandes
    if buys >= 500:
        score += 15
        razoes.append("✅ Muitas compras únicas: {} txns".format(buys))
    elif buys >= 200:
        score += 10
        razoes.append("✅ Compras altas: {} txns".format(buys))
    elif buys >= 50:
        score += 4
        razoes.append("🟡 Compras moderadas: {} txns".format(buys))
    else:
        riscos.append("⚠️ Poucas compras — possível manipulação por baleias")

    # 5. VARIAÇÃO DE PREÇO RECENTE — confirmação de pump ativo
    if pc5m >= 20:
        score += 10
        razoes.append("✅ Pump ativo em 5min: +{:.0f}%".format(pc5m))
    elif pc5m >= 5:
        score += 5
        razoes.append("🟡 Alta em 5min: +{:.0f}%".format(pc5m))
    elif pc5m <= -15:
        score -= 15
        riscos.append("🔴 Queda forte em 5min: {:.0f}% — possível dump".format(pc5m))

    if pc1h >= 50:
        score += 8
        razoes.append("✅ Alta forte em 1h: +{:.0f}%".format(pc1h))
    elif pc1h <= -30:
        score -= 10
        riscos.append("🔴 Queda em 1h: {:.0f}%".format(pc1h))

    # 6. TENDÊNCIA 6H — já passou do pico?
    if pc6h >= 300:
        riscos.append("⚠️ Alta de {:.0f}% em 6h — pode já ter passado o pico".format(pc6h))
    elif pc6h >= 50:
        score += 5
        razoes.append("🟡 Tendência positiva em 6h: +{:.0f}%".format(pc6h))

    score = max(0, min(100, score))

    if score >= 65 and ratio >= MIN_BUY_RATIO and liq >= MIN_LIQUIDITY:
        sinal = "🟢 COMPRA"
    elif score >= 45:
        sinal = "👀 OBSERVAR"
    else:
        sinal = "⚪ NEUTRO"

    return score, sinal, razoes, riscos


def label_score(score):
    if score >= 75: return "🔥 HOT"
    if score >= 55: return "🌡 WARM"
    return "❄️ COLD"


# ─── DEXSCREENER ───────────────────────────────────────────────────────────
def scan_dex():
    global seen, stats

    while True:
        print("[DEX] scanning...")
        try:
            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r   = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            for pair in r.json().get("pairs", []):
                base   = pair.get("baseToken", {})
                token  = base.get("address")
                symbol = base.get("symbol", "UNKNOWN")

                if not token or token in seen:
                    continue

                liq   = pair.get("liquidity", {}).get("usd", 0) or 0
                vol   = pair.get("volume", {}).get("h24", 0) or 0
                buys  = pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0
                sells = pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0
                pc5m  = pair.get("priceChange", {}).get("m5", 0) or 0
                pc1h  = pair.get("priceChange", {}).get("h1", 0) or 0
                pc6h  = pair.get("priceChange", {}).get("h6", 0) or 0

                # Filtros hard — descarta antes de calcular score
                if liq  < MIN_LIQUIDITY:                  continue
                if vol  < MIN_VOLUME:                     continue
                if buys < MIN_BUYS:                       continue
                if buys / max(sells, 1) < MIN_BUY_RATIO:  continue

                seen.add(token)

                score, sinal, razoes, riscos = calcular_score(liq, vol, buys, sells, pc5m, pc1h, pc6h)

                if score < MIN_SCORE:
                    stats["ignorado"] += 1
                    continue

                stats["compra" if "COMPRA" in sinal else "observar"] += 1

                gmgn = "https://gmgn.ai/sol/token/{}".format(token)
                dex  = "https://dexscreener.com/solana/{}".format(token)

                razoes_txt = "\n".join("  " + x for x in razoes)
                riscos_txt = ("\n\n*⚠️ Atenção:*\n" + "\n".join("  " + x for x in riscos)) if riscos else ""

                msg = (
                    "{sinal} *{symbol}* — {label} {score}/100\n\n"
                    "*Liquidez:* ${liq:,.0f}\n"
                    "*Volume 24h:* ${vol:,.0f}\n"
                    "*Compras:* {buys}  |  *Vendas:* {sells}\n"
                    "*Ratio C/V:* {ratio:.1f}x\n"
                    "*Δ 5min:* {pc5m:+.1f}%  |  *Δ 1h:* {pc1h:+.1f}%  |  *Δ 6h:* {pc6h:+.1f}%\n\n"
                    "*Por que alertei:*\n{razoes}"
                    "{riscos}\n\n"
                    "[GMGN]({gmgn}) · [DexScreener]({dex})"
                ).format(
                    sinal=sinal, symbol=symbol,
                    label=label_score(score), score=score,
                    liq=liq, vol=vol, buys=buys, sells=sells,
                    ratio=buys / max(sells, 1),
                    pc5m=pc5m, pc1h=pc1h, pc6h=pc6h,
                    razoes=razoes_txt, riscos=riscos_txt,
                    gmgn=gmgn, dex=dex,
                )

                send(msg)

        except Exception as e:
            print("[DEX] error:", e)

        time.sleep(DEX_INTERVAL)


# ─── PUMP.FUN ──────────────────────────────────────────────────────────────
def scan_pump():
    global seen, stats

    while True:
        print("[PUMP] scanning...")
        try:
            url = "https://frontend-api.pump.fun/coins/latest"
            r   = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(PUMP_INTERVAL)
                continue

            for coin in r.json():
                token  = coin.get("mint")
                symbol = coin.get("symbol", "UNKNOWN")
                name   = coin.get("name", "")

                if not token or token in seen:
                    continue

                seen.add(token)

                usd_mc      = coin.get("usd_market_cap", 0) or 0
                reply_count = coin.get("reply_count", 0) or 0
                score       = 0
                razoes      = []
                riscos      = []

                if usd_mc >= 50_000:
                    score += 35
                    razoes.append("✅ Market cap relevante: ${:,.0f}".format(usd_mc))
                elif usd_mc >= 10_000:
                    score += 15
                    razoes.append("🟡 Market cap baixo: ${:,.0f}".format(usd_mc))
                else:
                    riscos.append("🚨 Market cap muito baixo — alto risco")

                if reply_count >= 100:
                    score += 30
                    razoes.append("✅ Comunidade ativa: {} replies".format(reply_count))
                elif reply_count >= 30:
                    score += 15
                    razoes.append("🟡 Engajamento moderado: {} replies".format(reply_count))
                else:
                    riscos.append("⚠️ Pouco engajamento — sem comunidade")

                sociais = sum([
                    bool(coin.get("twitter")),
                    bool(coin.get("website")),
                    bool(coin.get("telegram")),
                ])
                if sociais >= 2:
                    score += 20
                    razoes.append("✅ {} redes sociais verificadas".format(sociais))
                elif sociais == 1:
                    score += 8
                else:
                    riscos.append("⚠️ Sem redes sociais — risco elevado")

                if score < MIN_SCORE:
                    stats["ignorado"] += 1
                    continue

                sinal = "🟢 COMPRA" if score >= 60 else "👀 OBSERVAR"
                stats["compra" if "COMPRA" in sinal else "observar"] += 1

                gmgn       = "https://gmgn.ai/sol/token/{}".format(token)
                razoes_txt = "\n".join("  " + x for x in razoes)
                riscos_txt = ("\n\n*⚠️ Atenção:*\n" + "\n".join("  " + x for x in riscos)) if riscos else ""

                msg = (
                    "{sinal} *{symbol}* — PUMP.FUN — {label} {score}/100\n"
                    "_{name}_\n\n"
                    "*Por que alertei:*\n{razoes}"
                    "{riscos}\n\n"
                    "[Analisar no GMGN]({gmgn})"
                ).format(
                    sinal=sinal, symbol=symbol,
                    label=label_score(score), score=score,
                    name=name, razoes=razoes_txt,
                    riscos=riscos_txt, gmgn=gmgn,
                )

                send(msg)

        except Exception as e:
            print("[PUMP] error:", e)

        time.sleep(PUMP_INTERVAL)


# ─── RELATÓRIO A CADA 2H ───────────────────────────────────────────────────
def report():
    while True:
        time.sleep(7200)
        total = stats["compra"] + stats["observar"] + stats["ignorado"]
        msg = (
            "📊 *RELATÓRIO — 2h*\n\n"
            "Tokens analisados: {total}\n"
            "🟢 Alertas COMPRA: {compra}\n"
            "👀 Alertas OBSERVAR: {observar}\n"
            "❌ Ignorados (abaixo do filtro): {ignorado}\n\n"
            "📋 Tokens em memória: {seen}\n"
            "📨 Mensagens enviadas: {alerts}\n\n"
            "⚙️ *Filtros ativos:*\n"
            "  Score mín: {min_score}/100\n"
            "  Liquidez mín: ${min_liq:,}\n"
            "  Volume mín: ${min_vol:,}\n"
            "  Ratio C/V mín: {min_ratio}x\n"
            "  Compras mín: {min_buys} txns"
        ).format(
            total=total, compra=stats["compra"],
            observar=stats["observar"], ignorado=stats["ignorado"],
            seen=len(seen), alerts=alerts,
            min_score=MIN_SCORE, min_liq=MIN_LIQUIDITY,
            min_vol=MIN_VOLUME, min_ratio=MIN_BUY_RATIO,
            min_buys=MIN_BUYS,
        )
        send(msg)


# ─── SERVER ────────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return "sniper online | tokens: {} | alerts: {}".format(len(seen), alerts)


# ─── START ─────────────────────────────────────────────────────────────────
def start():
    send((
        "🚀 *MEMECOIN SNIPER ONLINE*\n\n"
        "⚙️ *Filtros ativos:*\n"
        "  Score mínimo: {min_score}/100\n"
        "  Liquidez mínima: ${min_liq:,}\n"
        "  Volume mínimo: ${min_vol:,}\n"
        "  Ratio compra/venda: ≥{min_ratio}x\n"
        "  Compras mínimas: {min_buys} txns\n\n"
        "Só alertarei tokens que passarem em TODOS os filtros."
    ).format(
        min_score=MIN_SCORE, min_liq=MIN_LIQUIDITY,
        min_vol=MIN_VOLUME, min_ratio=MIN_BUY_RATIO,
        min_buys=MIN_BUYS,
    ))
    threading.Thread(target=scan_dex,  daemon=True).start()
    threading.Thread(target=scan_pump, daemon=True).start()
    threading.Thread(target=report,    daemon=True).start()


if __name__ == "__main__":
    start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
