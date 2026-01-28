import telebot
import requests
import time
import os
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "Bot Online"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Puxa o token direto da configuração da Render
TOKEN = os.environ.get('TELEGRAM_TOKEN')
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
    bot.reply_to(message, "🎯 **SNIPER ATIVADO**")
    vistos = set()
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                mcap = t.get('market_cap', 0)
                if addr not in vistos and 15000 <= mcap <= 600000:
                    symbol = t.get('symbol', '???')
                    msg = f"💎 **GEMA:** ${symbol}\n**MCap:** ${mcap:,.0f}\nhttps://gmgn.ai/sol/token/{addr}"
                    bot.send_message(message.chat.id, msg)
                    vistos.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling()
