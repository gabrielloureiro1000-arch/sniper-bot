import telebot
import requests
import time
import os
from flask import Flask
from threading import Thread

# Configuração essencial para a Render não dar erro de porta
app = Flask('')
@app.route('/')
def home(): return "Sniper Online"

def run_flask():
    # A Render exige que o app rode na porta 10000 ou na definida pelo sistema
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

TOKEN = "8595782081:AAGjVk_NRdI5FQKFl4Z3Xc7wy1uZGf51mlw"
PROXY_KEY = "0964b99b46c741438a03ee5d76442a8a"
bot = telebot.TeleBot(TOKEN)

def buscar_gemas():
    url_gmgn = "https://gmgn.ai/api/v1/token_trending/sol?period=1h&limit=20"
    proxy_url = f"https://api.scraperant.com/v2/general?url={url_gmgn}&x-api-key={PROXY_KEY}"
    try:
        r = requests.get(proxy_url, timeout=20)
        return r.json().get('data', {}).get('tokens', [])
    except:
        return []

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🎯 **SNIPER ATIVADO**\nBuscando moedas...")
    vistos = set()
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                mcap = t.get('market_cap', 0)
                if addr not in vistos and 15000 <= mcap <= 600000:
                    symbol = t.get('symbol', '???')
                    msg = (f"💎 **GEMA DETECTADA**\n\n"
                           f"**Token:** ${symbol}\n"
                           f"**Market Cap:** ${mcap:,.0f}\n\n"
                           f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})")
                    bot.send_message(message.chat.id, msg, parse_mode="Markdown")
                    vistos.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    # Inicia o servidor web em segundo plano
    t = Thread(target=run_flask)
    t.start()
    print("🤖 Robô iniciado!")
    # Inicia o Telegram
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
