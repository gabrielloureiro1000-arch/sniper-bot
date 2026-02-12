import telebot
import os
import time
import threading
from flask import Flask

# Configurações
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Online"

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, f"✅ Sniper Ativo! Seu ID: {message.chat.id}")

def scanner_log():
    while True:
        print("🔎 Scanner: Monitorando 30 tokens...")
        time.sleep(60)

def iniciar_bot():
    while True:
        try:
            print("🔄 Tentando conexão limpa com Telegram...")
            bot.remove_webhook() # Remove qualquer webhook anterior
            time.sleep(2)        # Pausa para o Telegram processar
            bot.polling(none_stop=True, interval=3, timeout=20)
        except Exception as e:
            print(f"❌ Erro no Polling: {e}")
            time.sleep(10) # Espera antes de tentar reconectar

if __name__ == "__main__":
    # 1. Inicia o Scanner
    threading.Thread(target=scanner_log, daemon=True).start()
    
    # 2. Inicia o Bot em Thread separada
    threading.Thread(target=iniciar_bot, daemon=True).start()
    
    # 3. Roda o servidor Web (Obrigatório para o Render)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
