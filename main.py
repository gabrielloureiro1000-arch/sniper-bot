import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ─────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEX_INTERVAL = 6

MIN_LIQUIDITY = 2000
MIN_VOLUME_M5 = 5000
MIN_BUYS = 6
MIN_PRICE_CHANGE = 3

WHALE_BUYS = 8
WHALE_AVG = 900

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)

seen = set()

monitored_tokens = {}

alerts = 0

# ─── TELEGRAM ───────────────────────────

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

# ─── RELATÓRIO 2H ───────────────────────

def report():

    while True:

        time.sleep(7200)

        if not monitored_tokens:
            continue

        report_msg = "📊 *RELATÓRIO DE PERFORMANCE (2H)*\n\n"

        addresses = ",".join(monitored_tokens.keys())

        try:

            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses}"

            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                continue

            pairs = r.json().get("pairs", [])

            current = {}

            for p in pairs:

                addr = p.get("baseToken", {}).get("address")
                price = p.get("priceUsd")

                if addr and price:
                    current[addr] = float(price)

            positives = 0
            negatives = 0

            for addr, info in monitored_tokens.items():

                if addr not in current:
                    continue

                initial = info["price"]
                now = current[addr]

                change = ((now - initial) / initial) * 100

                if change >= 0:
                    emoji = "🚀"
                    positives += 1
                else:
                    emoji = "🔻"
                    negatives += 1

                report_msg += f"{emoji} *{info['symbol']}* `{change:+.2f}%`\n"

            report_msg += "\n"
            report_msg += f"🧠 Sinais enviados: {alerts}\n"
            report_msg += f"📈 Positivos: {positives}\n"
            report_msg += f"📉 Negativos: {negatives}"

            send(report_msg)

        except Exception as e:

            print("Erro relatório:", e)

# ─── SCANNER PRINCIPAL ──────────────────

def scan():

    print("🚀 SNIPER ATIVO")

    while True:

        try:

            url = "https://api.dexscreener.com/latest/dex/search?q=sol"

            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            pairs = r.json().get("pairs", [])

            for pair in pairs:

                token = pair.get("baseToken", {})

                token_addr = token.get("address")
                symbol = token.get("symbol", "???")

                if not token_addr:
                    continue

                if token_addr in seen:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0)
                volume_m5 = pair.get("volume", {}).get("m5", 0)

                buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)

                price_change = pair.get("priceChange", {}).get("m5", 0)

                price = pair.get("priceUsd")

                if not price:
                    continue

                price = float(price)

                if liquidity < MIN_LIQUIDITY:
                    continue

                if volume_m5 < MIN_VOLUME_M5:
                    continue

                if buys < MIN_BUYS:
                    continue

                if buys <= sells:
                    continue

                if price_change < MIN_PRICE_CHANGE:
                    continue

                avg_buy = 0

                if buys > 0:
                    avg_buy = volume_m5 / buys

                whale = False

                if buys >= WHALE_BUYS and avg_buy >= WHALE_AVG:
                    whale = True

                seen.add(token_addr)

                monitored_tokens[token_addr] = {
                    "symbol": symbol,
                    "price": price,
                    "timestamp": time.time()
                }

                gmgn = f"https://gmgn.ai/sol/token/{token_addr}?chain=sol"

                if whale:
                    header = "🐋 *BALEIAS COMPRANDO*"
                else:
                    header = "🚀 *TOKEN EM MOVIMENTO*"

                msg = (
                    f"{header}\n\n"
                    f"💎 *{symbol}*\n\n"
                    f"`{token_addr}`\n\n"
                    f"💰 Preço `${price:.8f}`\n"
                    f"💧 Liquidez `${liquidity:,.0f}`\n"
                    f"📊 Volume5m `${volume_m5:,.0f}`\n\n"
                    f"🔥 Buys `{buys}`\n"
                    f"📉 Sells `{sells}`\n\n"
                    f"🔗 [ABRIR NO GMGN]({gmgn})"
                )

                send(msg)

        except Exception as e:

            print("Erro scanner:", e)

        time.sleep(DEX_INTERVAL)

# ─── HEALTHCHECK ────────────────────────

@app.route("/")
def health():
    return "BOT ONLINE"

# ─── START ──────────────────────────────

def start():

    t1 = threading.Thread(target=scan)
    t1.daemon = True
    t1.start()

    t2 = threading.Thread(target=report)
    t2.daemon = True
    t2.start()

if __name__ == "__main__":

    start()

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
