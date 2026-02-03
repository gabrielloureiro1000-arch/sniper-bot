import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot

# --- SERVIDOR PARA MANTER O KOYEB FELIZ ---
app = Flask('')

@app.route('/')
def home():
    return "SERVIDOR ONLINE", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- INICIALIZAÇÃO DO BOT ---
# O segredo está no .strip() e no tratamento de erro
raw_token = os.environ.get('TELEGRAM_TOKEN', '')
TOKEN = raw_token.strip().replace('"', '').replace("'", "")

bot = None

print("--- DIAGNÓSTICO ---")
if ":" in TOKEN:
    try:
        bot = telebot.TeleBot(TOKEN)
        print(f"✅ Token validado com sucesso: {TOKEN[:5]}***")
    except Exception as e:
        print(f"❌ Erro ao iniciar TeleBot: {e}")
else:
    print(f"❌ ERRO DE FORMATO: O Token lido foi [{TOKEN}].")
    print("O Token do Telegram DEVE ter dois pontos (Ex: 123456:ABC-DEF)")

# --- COMANDO SIMPLES PARA TESTE ---
if bot:
    @bot.message_handler(commands=['start'])
    def welcome(m):
        bot.reply_to(m, "🚀 BOT OPERACIONAL!")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    # Roda o Flask em paralelo
    Thread(target=run_flask, daemon=True).start()
    
    if bot:
        print("📡 Escutando Telegram...")
        while True:
            try:
                bot.polling(none_stop=True, timeout=20)
            except Exception as e:
                print(f"🔄 Erro de conexão (provável conflito 409): {e}")
                time.sleep(5)
    else:
        print("🛑 Bot em espera. Corrija o Token no painel do Koyeb.")
        while True: time.sleep(60)
