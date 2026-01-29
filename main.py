import os
import telebot
import requests
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÃO ---
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- SERVIDOR PARA MANTER ONLINE (HEALTH CHECK) ---
@app.route('/')
def index():
    return "Sniper Bot is Running!"

def run():
    # A Koyeb fornece a porta automaticamente, mas usamos 8080 como padrão
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- COMANDOS DO BOT ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🎯 Sniper Bot Ativo! Envie o endereço do contrato (Solana) para analisar.")

@bot.message_handler(func=lambda message: len(message.text) > 30) # Filtro simples para contratos
def analyze_token(message):
    contract = message.text.strip()
    bot.reply_to(message, f"🔍 Analisando: `{contract}`...", parse_mode="Markdown")
    
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        response = requests.get(url).json()
        
        if response.get('pairs'):
            pair = response['pairs'][0]
            price = pair.get('priceUsd', 'N/A')
            liquidity = pair.get('liquidity', {}).get('usd', 0)
            mcap = pair.get('fdv', 0)
            
            msg = (
                f"✅ **Token Encontrado!**\n\n"
                f"💵 Preço: ${price}\n"
                f"💧 Liquidez: ${liquidity:,.2f}\n"
                f"📊 Market Cap: ${mcap:,.2f}\n"
                f"🔗 [Ver na DexScreener]({pair['url']})"
            )
            bot.send_message(message.chat.id, msg, parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Token não encontrado ou sem liquidez.")
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ Erro ao buscar dados.")

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    # Inicia o servidor Flask em uma thread separada
    t = Thread(target=run)
    t.start()
    
    # Inicia o Polling do Telegram
    print("Bot iniciado...")
    bot.infinity_polling()
