import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")
MIN_SCORE      = int(os.getenv("MIN_SCORE", "40"))       # 0-100, filtra tokens fracos
MIN_LIQUIDITY  = int(os.getenv("MIN_LIQUIDITY", "500"))  # em USD
MIN_TX         = int(os.getenv("MIN_TX", "10"))          # mínimo de transações
DEX_INTERVAL   = int(os.getenv("DEX_INTERVAL", "5"))     # segundos
PUMP_INTERVAL  = int(os.getenv("PUMP_INTERVAL", "10"))   # segundos

bot = telebot.TeleBot(TELEGRAM_TOKEN)

seen   = set()
alerts = 0
stats  = {"compra": 0, "venda": 0, "neutro": 0}

app = Flask(__name__)


# ─── TELEGRAM ──────────────────────────────────────────────────────────────
def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print("telegram error:", e)


# ─── SCORE + SINAL ─────────────────────────────────────────────────────────
def calcular_score(liq, buys, sells, vol, price_change_5m=0):
    """
    Retorna (score 0-100, sinal, razoes[])
    """
    ratio  = buys / max(sells, 1)
    razoes = []
    pontos = 0

    # Liquidez
    if liq >= 50000:
        pontos += 20
        razoes.append("✅ Liquidez alta: ${:,.0f}".format(liq))
    elif liq >= 5000:
        pontos += 10
        razoes.append("🟡 Liquidez média: ${:,.0f}".format(liq))
    else:
        razoes.append("⚠️ Liquidez baixa: ${:,.0f}".format(liq))

    # Ratio compra/venda
    if ratio >= 5:
        pontos += 30
        razoes.append("✅ Ratio C/V excelente: {:.1f}x".format(ratio))
    elif ratio >= 2:
        pontos += 18
        razoes.append("✅ Ratio C/V bom: {:.1f}x".format(ratio))
    elif ratio >= 1:
        pontos += 8
        razoes.append("🟡 Ratio C/V neutro: {:.1f}x".format(ratio))
    else:
        razoes.append("🔴 Pressão de venda: {:.1f}x".format(ratio))

    # Volume
    if vol >= liq * 2:
        pontos += 20
        razoes.append("✅ Volume 2x acima da liquidez")
    elif vol >= liq:
        pontos += 10
        razoes.append("🟡 Volume similar à liquidez")

    # Transações
    tx = buys + sells
    if tx >= 300:
        pontos += 15
        razoes.append("✅ Alto número de transações: {}".format(tx))
    elif tx >= 100:
        pontos += 8
        razoes.append("🟡 Transações moderadas: {}".format(tx))

    # Variação de preço (5m)
    if price_change_5m > 30:
        pontos += 15
        razoes.append("✅ Alta de preço em 5m: +{:.0f}%".format(price_change_5m))
    elif price_change_5m < -20:
        pontos -= 10
        razoes.append("🔴 Queda de preço em 5m: {:.0f}%".format(price_change_5m))

    score = max(0, min(100, pontos))

    # Sinal final
    if score >= 65 and ratio >= 2:
        sinal = "🟢 COMPRA"
    elif score < 30 or ratio < 0.7:
        sinal = "🔴 VENDA / EVITAR"
    elif score >= 45:
        sinal = "👀 OBSERVAR"
    else:
        sinal = "⚪ NEUTRO"

    return score, sinal, razoes


def label_score(score):
    if score >= 70: return "🔥 HOT"
    if score >= 45: return "🌡 WARM"
    return "❄️ COLD"


# ─── DEXSCREENER ───────────────────────────────────────────────────────────
def scan_dex():
    global seen, stats

    while True:
        print("[DEX] scanning...")
        try:
            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            pairs = r.json().get("pairs", [])

            for pair in pairs:
                base   = pair.get("baseToken", {})
                token  = base.get("address")
                symbol = base.get("symbol", "UNKNOWN")

                if not token or token in seen:
                    continue

                liq   = pair.get("liquidity", {}).get("usd", 0) or 0
                vol   = pair.get("volume", {}).get("h24", 0) or 0
                buys  = pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0
                sells = pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0
                tx    = buys + sells

                pc5m  = pair.get("priceChange", {}).get("m5", 0) or 0

                # Filtros mínimos
                if liq < MIN_LIQUIDITY or tx < MIN_TX:
                    continue

                seen.add(token)

                score, sinal, razoes = calcular_score(liq, buys, sells, vol, pc5m)

                # Pular tokens abaixo do score mínimo
                if score < MIN_SCORE:
                    continue

                # Atualizar estatísticas
                if "COMPRA" in sinal:
                    stats["compra"] += 1
                elif "VENDA" in sinal:
                    stats["venda"] += 1
                else:
                    stats["neutro"] += 1

                gmgn = "https://gmgn.ai/sol/token/{}".format(token)
                dex  = "https://dexscreener.com/solana/{}".format(token)

                razoes_txt = "\n".join("  " + r for r in razoes)

                msg = (
                    "🚨 *TOKEN DETECTADO — DEX*\n\n"
                    "*Token:* `{symbol}`\n"
                    "*Score:* {label} ({score}/100)\n"
                    "*Sinal:* {sinal}\n\n"
                    "*Liquidez:* ${liq:,.0f}\n"
                    "*Volume 24h:* ${vol:,.0f}\n"
                    "*Compras:* {buys}  |  *Vendas:* {sells}\n"
                    "*Δ Preço 5m:* {pc5m:+.1f}%\n\n"
                    "*Razões:*\n{razoes}\n\n"
                    "[GMGN]({gmgn}) · [DexScreener]({dex})"
                ).format(
                    symbol=symbol, label=label_score(score), score=score,
                    sinal=sinal, liq=liq, vol=vol, buys=buys, sells=sells,
                    pc5m=pc5m, razoes=razoes_txt, gmgn=gmgn, dex=dex,
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
            r = requests.get(url, timeout=10)

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

                # Pump.fun não traz métricas completas — score básico
                usd_mc = coin.get("usd_market_cap", 0) or 0
                reply_count = coin.get("reply_count", 0) or 0

                score = 0
                razoes = []

                if usd_mc > 10000:
                    score += 30
                    razoes.append("✅ Market cap: ${:,.0f}".format(usd_mc))
                if reply_count > 20:
                    score += 20
                    razoes.append("✅ Engajamento: {} replies".format(reply_count))
                if coin.get("twitter"):
                    score += 10
                    razoes.append("✅ Tem Twitter")
                if coin.get("website"):
                    score += 10
                    razoes.append("✅ Tem website")
                if coin.get("telegram"):
                    score += 10
                    razoes.append("✅ Tem Telegram")

                if score < MIN_SCORE:
                    continue

                sinal = "🟢 COMPRA" if score >= 50 else "👀 OBSERVAR"
                stats["compra" if "COMPRA" in sinal else "neutro"] += 1

                gmgn   = "https://gmgn.ai/sol/token/{}".format(token)
                razoes_txt = "\n".join("  " + r for r in razoes) if razoes else "  Novo token — analisar manualmente"

                msg = (
                    "🔥 *NOVO TOKEN — PUMP.FUN*\n\n"
                    "*Token:* `{symbol}` — {name}\n"
                    "*Score:* {label} ({score}/100)\n"
                    "*Sinal:* {sinal}\n\n"
                    "*Razões:*\n{razoes}\n\n"
                    "[Analisar no GMGN]({gmgn})"
                ).format(
                    symbol=symbol, name=name, label=label_score(score),
                    score=score, sinal=sinal, razoes=razoes_txt, gmgn=gmgn,
                )

                send(msg)

        except Exception as e:
            print("[PUMP] error:", e)

        time.sleep(PUMP_INTERVAL)


# ─── RELATÓRIO A CADA 2H ───────────────────────────────────────────────────
def report():
    while True:
        time.sleep(7200)
        msg = (
            "📊 *RELATÓRIO DO BOT*\n\n"
            "Tokens vistos: {seen}\n"
            "Alertas enviados: {alerts}\n\n"
            "🟢 Sinais de COMPRA: {compra}\n"
            "🔴 Sinais de VENDA: {venda}\n"
            "⚪ Neutros: {neutro}\n\n"
            "Score mínimo: {min_score}\n"
            "Status: ✅ ONLINE"
        ).format(
            seen=len(seen), alerts=alerts,
            compra=stats["compra"], venda=stats["venda"], neutro=stats["neutro"],
            min_score=MIN_SCORE,
        )
        send(msg)


# ─── FLASK SERVER ──────────────────────────────────────────────────────────
@app.route("/")
def home():
    return "sniper running — tokens: {} | alerts: {}".format(len(seen), alerts)


# ─── START ─────────────────────────────────────────────────────────────────
def start():
    send(
        "🚀 *MEMECOIN SNIPER ONLINE*\n\n"
        "Score mínimo: {}\n"
        "Liquidez mínima: ${:,}\n"
        "Scanner DEX: {}s | PUMP: {}s".format(
            MIN_SCORE, MIN_LIQUIDITY, DEX_INTERVAL, PUMP_INTERVAL
        )
    )
    threading.Thread(target=scan_dex,  daemon=True).start()
    threading.Thread(target=scan_pump, daemon=True).start()
    threading.Thread(target=report,    daemon=True).start()


if __name__ == "__main__":
    start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
