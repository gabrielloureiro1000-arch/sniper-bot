
import telebot
import requests
import time
import os
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "Sniper Online"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Puxa das configurações da Render (Environment) ou usa o reserva
TOKEN = os.environ.get('TELEGRAM_TOKEN', "8595782081:AAEZ885Y-CEYV85Qd0WGDW50_qryE4gXyEs")
PROXY_KEY = "0964b99b46c741438a03ee5d76442a8a"
bot = telebot.TeleBot(TOKEN)

def buscar_gemas():
    url_gmgn = "https://gmgn.ai/api/v1/token_trending/sol?period=1h&limit=20"
    proxy_url = f"https://api.scraperant.com/v2/general?url={url_gmgn}&x-api-key={PROXY_KEY}"
    try:
        r = requests.get(proxy_url, timeout=20)
        if r.status_code == 200:
            return r.json().get('data', {}).get('tokens', [])
        return []
    except Exception as e:
        print(f"Aguardando rede... {e}")
        return []

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🎯 **SNIPER ATIVADO**\nBuscando gemas entre $15k e $600k...")
    vistos = set()
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                mcap = t.get('market_cap', 0)
                if addr not in vistos and 15000 <= mcap <= 600000:
                    symbol = t.get('symbol', '???')
                    msg = (f"💎 **NOVA GEMA**\n\n"
                           f"**Token:** ${symbol}\n"
                           f"**MCap:** ${mcap:,.0f}\n\n"
                           f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})")
                    bot.send_message(message.chat.id, msg, parse_mode="Markdown")
                    vistos.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("🤖 Robô tentando conexão final...")
    # O infinity_polling evita que o bot caia por instabilidade da Render
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
