import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
from solders.keypair import Keypair

# --- SETUP ---
app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY_STR = os.getenv('PRIVATE_KEY', '').strip()
VALOR_COMPRA = 0.1 

bot = telebot.TeleBot(TOKEN)

@app.route('/')
def home(): return "SNIPER GMGN ACTIVE", 200

# --- RELATÓRIO ---
def loop_relatorio(chat_id):
    while True:
        time.sleep(7200) # 2 Horas
        try:
            bot.send_message(chat_id, "📊 *RELATÓRIO AUTOMÁTICO*\nStatus: Monitorando GMGN\nLucro: 0.00 SOL", parse_mode="Markdown")
        except: pass

# --- SNIPER ---
@bot.message_handler(commands=['start'])
def start(m):
    Thread(target=loop_relatorio, args=(m.chat.id,), daemon=True).start()
    bot.reply_to(m, "🎯 *Sniper Conectado!* Mande um Contrato para operar.")

@bot.message_handler(func=lambda msg: len(msg.text) >= 32)
def trade(m):
    ca = m.text.strip()
    bot.reply_to(m, f"⚡ *Iniciando Sniper em:* `{ca}`\nValor: {VALOR_COMPRA} SOL", parse_mode="Markdown")
    # Lógica de compra aqui...

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    while True:
        try:
            bot.remove_webhook()
            bot.polling(none_stop=True, interval=3)
        except:
            time.sleep(10)
