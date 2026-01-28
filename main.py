import telebot
import requests
import time
import os
from flask import Flask
from threading import Thread

# 1. Configuração do Servidor Web para a Render
app = Flask('')
@app.route('/')
def home(): return "Sniper Ativo e Operacional"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# 2. Configurações do Bot (Token Novo Aplicado)
TOKEN = "8595782081:AAEZ885Y-CEYV85Qd0WGDW50_qryE4gXyEs"
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
        print(f"Erro ao buscar dados: {e}")
        return []

# 3. Comando Start
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "🎯 **SNIPER PROFISSIONAL ATIVADO**\nMonitorando Smart Money (MCap $15k - $600k)...")
    vistos = set()
    print(f"Bot iniciado pelo usuário: {message.chat.id}")
    
    while True:
        try:
            tokens = buscar_gemas()
            for t in tokens:
                addr = t.get('address')
                mcap = t.get('market_cap', 0)
                
                # Filtro de Market Cap
                if addr not in vistos and 15000 <= mcap <= 600000:
                    symbol = t.get('symbol', '???')
                    name = t.get('name', 'Token')
                    
                    msg = (f"💎 **GEMA SMART MONEY DETECTADA**\n\n"
                           f"**Token:** {name} (${symbol})\n"
                           f"**Market Cap:** ${mcap:,.0f}\n\n"
                           f"🔗 [Analisar na GMGN](
