import telebot
import requests
import time
import os
from flask import Flask
from threading import Thread

# Servidor Web para manter o robô vivo
app = Flask('')
@app.route('/')
def home(): return "Sniper Ativo"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Token do Telegram
TOKEN = "8595782081:AAEZ885Y-CEYV85Qd0WGDW50_qryE4gXyEs"
bot = telebot.TeleBot(TOKEN)

def buscar_oportunidades():
    # API da DexScreener é gratuita e mais estável que 'raspar' site
    url = "https://api.dexscreener.com/latest/dex/search?q=solana"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.json().get('pairs', [])
        return []
    except:
        return []

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🎯 **SNIPER KOYEB ATIVADO**\nBuscando gemas na Solana...")
    enviados = set()
    while True:
        try:
            tokens = buscar_oportunidades()
            for t in tokens:
                addr = t.get('baseToken', {}).get('address')
                mcap = t.get('fdv', 0)
                # Filtro: $10k a $500k
                if addr not in enviados and 10000 <= mcap <= 500000:
                    symbol = t.get('baseToken', {}).get('symbol')
                    msg = f"🚀 **GEMA:** ${symbol}\n**MCap:** ${mcap:,.0f}\n🔗 [Analisar](https://gmgn.ai/sol/token/{addr})"
                    bot.send_message(message.chat.id, msg)
                    enviados.add(addr)
        except: pass
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling()
