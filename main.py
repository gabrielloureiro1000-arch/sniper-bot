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
    return "Sniper Vivo e Operante"

# COMANDO DE TESTE: Responde ao /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    msg = f"✅ Sniper Conectado!\n\nSeu Chat ID: `{chat_id}`\n\nAgora eu já consigo te enviar alertas de tokens!"
    bot.reply_to(message, msg, parse_mode="Markdown")
    print(f"✅ Interação recebida! Usuário {chat_id} deu start.")

# ESCUTA TUDO: Se você mandar qualquer coisa, ele responde
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, "Estou monitorando os tokens... Digite /start para ver seu ID.")

def scanner_mock():
    while True:
        print("🔎 Scanner: 30 tokens analisados.")
        time.sleep(60)

def run_bot():
    bot.remove_webhook()
    time.sleep(1)
    print("🤖 Bot em modo de escuta...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Thread do Scanner
    threading.Thread(target=scanner_mock, daemon=True).start()
    
    # Thread do Bot
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Flask (Principal para o Render não derrubar)
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
