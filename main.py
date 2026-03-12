```python
import os
import time
import threading
import requests
import telebot
from flask import Flask

# ───── CONFIGURAÇÃO ─────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

DEX_INTERVAL = 5

MIN_LIQUIDITY = 1500
MIN_VOLUME_M5 = 2000
MIN_BUYS = 4

bot = telebot.TeleBot(TELEGRAM_TOKEN)

app = Flask(__name__)

seen = set()
alerts = 0

monitored_tokens = {}

# ───── TELEGRAM ─────────────────────────────────

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

# ───── RELATÓRIO A CADA 2H ─────────────────────

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

            prices = {}

            for p in pairs:

                addr = p.get("baseToken", {}).get("address")
                price = p.get("priceUsd")

                if addr and price:
                    prices[addr] = float(price)

            positives = 0
            negatives = 0

            for addr, info in monitored_tokens.items():

                if addr not in prices:
                    continue

                initial = info["price"]
                current = prices[addr]

                change = ((current - initial) / initial) * 100

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

# ───── SCANNER PRINCIPAL ───────────────────────

def scan():

    print("🚀 SCANNER SOLANA ATIVO")

    while True:

        try:

            url = "https://api.dexscreener.com/latest/dex/pairs/solana"

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
                volume = pair.get("volume", {}).get("m5", 0)

                buys = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                sells = pair.get("txns", {}).get("m5", {}).get("sells", 0)

                price = pair.get("priceUsd")

                if not price:
                    continue

                price = float(price)

                # FILTROS

                if liquidity < MIN_LIQUIDITY:
                    continue

                if volume < MIN_VOLUME_M5:
                    continue

                if buys < MIN_BUYS:
                    continue

                if buys <= sells:
                    continue

                seen.add(token_addr)

                monitored_tokens[token_addr] = {
                    "symbol": symbol,
                    "price": price,
                    "timestamp": time.time()
                }

                gmgn = f"https://gmgn.ai/sol/token/{token_addr}?chain=sol"

                msg = (
                    f"🚀 *TOKEN COMPRADO AGORA*\n\n"
                    f"💎 *{symbol}*\n\n"
                    f"`{token_addr}`\n\n"
                    f"💰 Preço `${price:.8f}`\n"
                    f"💧 Liquidez `${liquidity:,.0f}`\n"
                    f"📊 Volume5m `${volume:,.0f}`\n\n"
                    f"🔥 Buys `{buys}`\n"
                    f"📉 Sells `{sells}`\n\n"
                    f"🔗 [ABRIR GMGN]({gmgn})"
                )

                send(msg)

        except Exception as e:

            print("Erro scanner:", e)

        time.sleep(DEX_INTERVAL)

# ───── HEALTHCHECK ─────────────────────────────

@app.route("/")
def health():
    return "BOT ONLINE"

# ───── START ───────────────────────────────────

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
```
