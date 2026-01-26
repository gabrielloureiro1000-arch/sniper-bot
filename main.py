import telebot
import requests
import time
from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home(): return "Bot Online"
def run_flask(): app.run(host='0.0.0.0', port=8080)

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
    bot.reply_to(message, "🎯 **TESTE DE SNIPER ATIVADO**\nBuscando TODAS as moedas para testar a conexão...")
    vistos = set()
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                if addr not in vistos:
                    symbol = t.get('symbol', '???')
                    mcap = t.get('market_cap', 0)
                    msg = (f"💎 **MOEDA ENCONTRADA**\n\n"
                           f"**Token:** ${symbol}\n"
                           f"**Market Cap:** ${mcap:,.0f}\n\n"
                           f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})")
                    bot.send_message(message.chat.id, msg, parse_mode="Markdown")
                    vistos.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling()
