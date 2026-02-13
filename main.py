import telebot
import os
import time
import threading
from flask import Flask

# 1. Configuração do Flask (Essencial para o Render não dar erro de porta)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is Running", 200

# 2. Configuração do Bot
TOKEN = os.getenv('TELEGRAM_TOKEN')

def iniciar_bot():
    if not TOKEN:
        print("❌ ERRO: Variável TELEGRAM_TOKEN não encontrada!")
        return

    bot = telebot.TeleBot(TOKEN)

    @bot.message_handler(commands=['start'])
    def welcome(message):
        bot.reply_to(message, f"✅ Sniper Ativo!\nSeu Chat ID: {message.chat.id}")

    print("🔄 Limpando sessões do Telegram...")
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("🤖 Sniper conectado e aguardando comandos...")
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"❌ Erro no Polling: {e}")

def scanner_loop():
    while True:
        print("🔎 Scanner: Monitorando tokens na Solana...")
        time.sleep(60)

if __name__ == "__main__":
    # Inicia o scanner em segundo plano
    t_scan = threading.Thread(target=scanner_loop, daemon=True)
    t_scan.start()

    # Inicia o bot em segundo plano
    t_bot = threading.Thread(target=iniciar_bot, daemon=True)
    t_bot.start()

    # Roda o servidor web na thread principal
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Servidor Web iniciado na porta {port}")
    app.run(host='0.0.0.0', port=port)
