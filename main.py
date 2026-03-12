import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ─────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEX_INTERVAL = 3

MIN_LIQUIDITY = 5000
MIN_VOLUME_M5 = 10000
MIN_BUYS_M5 = 20
MIN_PRICE_CHANGE = 5
MIN_MC = 20000

WHALE_MIN_AVG_BUY = 1000
WHALE_BUYS = 8

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen = set()
alerts = 0

# {address : info}
monitored_tokens = {}

# ─── TELEGRAM ───────────────────────────────────────────

def send(msg):
    global alerts
    try:
        bot.send_message(
            CHAT_ID,
            msg,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        alerts += 1
    except Exception as e:
        print("Telegram error:", e)

# ─── RELATÓRIO PERFORMANCE 2H ───────────────────────────

def report_performance():

    while True:

        time.sleep(7200)

        if not monitored_tokens:
            continue

        report = "📊 *PERFORMANCE DOS SNIPES (2H)*\n\n"

        addresses = ",".join(monitored_tokens.keys())

        positives = 0
        negatives = 0

        try:

            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses}"

            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                continue

            pairs = r.json().get("pairs", [])

            prices = {}

            for p in pairs:

                addr = p.get("baseToken", {}).get("address")

                price = p.get("priceUsd")

                if addr and price:
                    prices[addr] = float(price)

            for addr, info in list(monitored_tokens.items()):

                if addr not in prices:
                    continue

                p_initial = info["price"]
                p_current = prices[addr]

                change = ((p_current - p_initial) / p_initial) * 100

                if change >= 0:
                    emoji = "🚀"
                    positives += 1
                else:
                    emoji = "🔻"
                    negatives += 1

                report += f"{emoji} *{info['symbol']}* `{change:+.2f}%`\n"

                if time.time() - info["timestamp"] > 86400:
                    monitored_tokens.pop(addr)

            report += "\n"
            report += f"🧠 Sinais: {alerts}\n"
            report += f"📈 Positivos: {positives}\n"
            report += f"📉 Negativos: {negatives}"

            send(report)

        except Exception as e:
            print("Erro relatório:", e)

# ─── SCANNER PRINCIPAL ──────────────────────────────────

def scan_dex():

    print("🚀 SNIPER GMGN ATIVO")

    while True:

        try:

            r = requests.get(
                "https://api.dexscreener.com/latest/dex/search/?q=sol",
                timeout=5
            )

            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            pairs = r.json().get("pairs", [])

            for pair in pairs:

                token_addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")

                if not token_addr:
                    continue

                if token_addr in seen:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0)
                volume_m5 = pair.get("volume", {}).get("m5", 0)

                buys_m5 = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                sells_m5 = pair.get("txns", {}).get("m5", {}).get("sells", 0)

                price_change = pair.get("priceChange", {}).get("m5", 0)

                marketcap = pair.get("fdv", 0)

                price_usd = float(pair.get("priceUsd", 0)) if pair.get("priceUsd") else 0

                # ─── FILTROS ───

                if liquidity < MIN_LIQUIDITY:
                    continue

                if volume_m5 < MIN_VOLUME_M5:
                    continue

                if buys_m5 < MIN_BUYS_M5:
                    continue

                if buys_m5 <= sells_m5:
                    continue

                if price_change < MIN_PRICE_CHANGE:
                    continue

                if marketcap < MIN_MC:
                    continue

                # ─── DETECÇÃO DE BALEIAS ───

                avg_buy = 0

                if buys_m5 > 0:
                    avg_buy = volume_m5 / buys_m5

                whale_alert = False

                if buys_m5 >= WHALE_BUYS and avg_buy >= WHALE_MIN_AVG_BUY:
                    whale_alert = True

                seen.add(token_addr)

                monitored_tokens[token_addr] = {
                    "symbol": symbol,
                    "price": price_usd,
                    "timestamp": time.time()
                }

                gm_link = f"https://gmgn.ai/sol/token/{token_addr}?chain=sol"

                trojan_link = f"https://t.me/solana_trojan_bot?start=r-user_{token_addr}"

                if whale_alert:
                    header = "🐋 *BALEIAS ENTRANDO*"
                else:
                    header = "🚀 *TOKEN SNIPADO*"

                msg = (
                    f"{header}\n\n"
                    f"💎 *{symbol}*\n\n"
                    f"📄 `CONTRACT`\n"
                    f"`{token_addr}`\n\n"
                    f"💰 Preço `${price_usd:.8f}`\n"
                    f"💧 Liquidez `${liquidity:,.0f}`\n"
                    f"📊 Volume 5m `${volume_m5:,.0f}`\n\n"
                    f"🔥 Buys `{buys_m5}`\n"
                    f"📉 Sells `{sells_m5}`\n\n"
                    f"🔗 [GMGN]({gm_link})\n"
                    f"⚡ [BUY TROJAN]({trojan_link})"
                )

                send(msg)

        except Exception as e:
            print("Erro scanner:", e)

        time.sleep(DEX_INTERVAL)

# ─── HEALTHCHECK ───────────────────────────────────────

@app.route("/")
def health():
    return "SNIPER ONLINE"

# ─── START ─────────────────────────────────────────────

if __name__ == "__main__":

    threading.Thread(target=scan_dex, daemon=True).start()

    threading.Thread(target=report_performance, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
