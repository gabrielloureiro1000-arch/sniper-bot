import os
import time
import threading
import requests
import telebot
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEX_INTERVAL = 5

MIN_LIQUIDITY = 1500
MIN_VOLUME = 4000
MIN_BUYS = 8
WHALE_VOLUME = 20000

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)

seen_tokens = set()
alerts = 0

monitored = {}

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

        print("telegram error", e)


def performance_report():

    while True:

        time.sleep(7200)

        if not monitored:
            continue

        report = "📊 RELATÓRIO 2H\n\n"

        addresses = ",".join(monitored.keys())

        try:

            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses}"

            r = requests.get(url, timeout=10)

            data = r.json().get("pairs", [])

            prices = {}

            for p in data:

                addr = p.get("baseToken", {}).get("address")
                price = p.get("priceUsd")

                if addr and price:
                    prices[addr] = float(price)

            for addr, info in monitored.items():

                if addr not in prices:
                    continue

                initial = info["price"]
                current = prices[addr]

                change = ((current - initial) / initial) * 100

                emoji = "🚀" if change >= 0 else "🔻"

                report += f"{emoji} {info['symbol']} {change:+.2f}%\n"

            report += f"\n📨 alertas enviados: {alerts}"

            send(report)

        except Exception as e:

            print("report error", e)


def scan():

    print("🚀 MEMECOIN SNIPER ATIVO")

    while True:

        try:

            url = "https://api.dexscreener.com/latest/dex/search?q=sol"

            r = requests.get(url, timeout=10)

            pairs = r.json().get("pairs", [])

            for pair in pairs:

                token = pair.get("baseToken", {})

                addr = token.get("address")
                symbol = token.get("symbol", "???")

                if not addr:
                    continue

                if addr in seen_tokens:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0)
                volume = pair.get("volume", {}).get("m5", 0)

                buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)

                price = pair.get("priceUsd")

                if not price:
                    continue

                price = float(price)

                if liquidity < MIN_LIQUIDITY:
                    continue

                if volume < MIN_VOLUME:
                    continue

                if buys < MIN_BUYS:
                    continue

                if buys <= sells:
                    continue

                whale = False

                if volume > WHALE_VOLUME:
                    whale = True

                seen_tokens.add(addr)

                monitored[addr] = {
                    "symbol": symbol,
                    "price": price,
                    "timestamp": time.time()
                }

                gmgn = f"https://gmgn.ai/sol/token/{addr}"

                emoji = "🐋" if whale else "🚀"

                msg = (
                    f"{emoji} TOKEN EM ACUMULAÇÃO\n\n"
                    f"💎 {symbol}\n\n"
                    f"`{addr}`\n\n"
                    f"💰 preço ${price:.8f}\n"
                    f"💧 liquidez ${liquidity:,.0f}\n"
                    f"📊 volume5m ${volume:,.0f}\n\n"
                    f"🔥 buys {buys}\n"
                    f"📉 sells {sells}\n\n"
                    f"🔗 GMGN\n{gmgn}"
                )

                send(msg)

        except Exception as e:

            print("scan error", e)

        time.sleep(DEX_INTERVAL)


@app.route("/")
def health():
    return "BOT ONLINE"


def start():

    t1 = threading.Thread(target=scan)
    t1.daemon = True
    t1.start()

    t2 = threading.Thread(target=performance_report)
    t2.daemon = True
    t2.start()


if __name__ == "__main__":

    start()

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
