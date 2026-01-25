import telebot
import requests
import time
from flask import Flask
from threading import Thread

# Parte para a Render não desligar o bot
app = Flask('')
@app.route('/')
def home(): return "Bot Online"
def run_flask(): app.run(host='0.0.0.0', port=8080)

# CONFIGURAÇÕES (Não mude nada aqui)
TOKEN = "8595782081:AAGjVk_NRdI5FQKFl4Z3Xc7wy1uZGf51mlw"
PROXY_KEY = "0964b99b46c741438a03ee5d76442a8a"
bot = telebot.TeleBot(TOKEN)

def buscar_gemas():
    url_gmgn = "https://gmgn.ai/api/v1/token_trending/sol?period=1h&limit=20"
    proxy_url = f"https://api.scraperant.com/v2/general?url={url_gmgn}&x-api-key={PROXY_KEY}"
    try:
        r = requests.get(proxy_url, timeout=30)
        return r.json().get('data', {}).get('tokens', [])
    except:
        return []

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🎯 **SNIPER SOLANA ATIVADO**\nBuscando Smart Money (MCap $15k - $600k)...")
    vistos = set()
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                mcap = t.get('market_cap', 0)
                if addr not in vistos and 15000 <= mcap <= 600000:
                    symbol = t.get('symbol', '???')
                    msg = (f"💎 **NOVA GEMA DETECTADA**\n\n"
                           f"**Token:** ${symbol}\n"
                           f"**Market Cap:** ${mcap:,.0f}\n\n"
                           f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})")
                    bot.send_message(message.chat.id, msg, parse_mode="Markdown")
                    vistos.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    print("🤖 Sniper Iniciado...")
    bot.infinity_polling()
