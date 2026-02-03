import os
import time
from flask import Flask
from threading import Thread
import telebot

# Configurações básicas
app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
bot = telebot.TeleBot(TOKEN) if TOKEN else None

@app.route('/')
def health_check():
    return "BOT_ALIVE", 200

def run_web():
    # O Koyeb exige que o app responda na porta 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Inicia o servidor web IMEDIATAMENTE
    Thread(target=run_web, daemon=True).start()
    
    # 2. Inicia o Bot apenas se o Token existir
    if bot:
        print("🚀 Sniper GMGN Iniciando...")
        while True:
            try:
                bot.remove_webhook()
                bot.polling(none_stop=True, interval=3)
            except Exception as e:
                print(f"Erro no Polling: {e}")
                time.sleep(10)
    else:
        print("❌ ERRO: TELEGRAM_TOKEN não encontrado!")
        while True: time.sleep(60)
