import os
import time
from flask import Flask
from threading import Thread
import telebot

app = Flask('')

# Pega o token e remove qualquer sujeira (espaços, aspas extras)
RAW_TOKEN = os.getenv('TELEGRAM_TOKEN', '').replace('"', '').replace("'", "").strip()

bot = None
if ":" in RAW_TOKEN:
    try:
        bot = telebot.TeleBot(RAW_TOKEN)
        print("✅ Token validado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao iniciar bot: {e}")
else:
    print("⚠️ AVISO: Variável TELEGRAM_TOKEN está vazia ou sem o formato correto (falta o ':')")

@app.route('/')
def health():
    return "SERVER_ALIVE", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Inicia servidor web primeiro para o Koyeb dar OK no Health Check
    Thread(target=run_web, daemon=True).start()
    
    if bot:
        print("🚀 Polling iniciado...")
        while True:
            try:
                bot.remove_webhook()
                bot.polling(none_stop=True, interval=3)
            except Exception as e:
                print(f"Erro no Polling: {e}")
                time.sleep(10)
    else:
        print("🛑 Bot parado: Aguardando Token válido nas variáveis de ambiente.")
        while True:
            time.sleep(60)
