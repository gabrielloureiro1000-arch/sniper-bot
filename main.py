import os
import time
import socket
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURAÇÃO DO FLASK ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Online!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- INICIALIZAÇÃO SEGURA DO BOT ---
TOKEN = os.getenv('TELEGRAM_TOKEN')

if not TOKEN:
    print("\n❌ ERRO CRÍTICO: Variável 'TELEGRAM_TOKEN' não encontrada!")
    print("Verifique o painel do Koyeb > Environment Variables.\n")
    bot = None
else:
    try:
        bot = TeleBot(TOKEN)
        print("✅ Token do Telegram carregado com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao validar Token: {e}")
        bot = None

# --- REQUISIÇÃO JUPITER COM RETRIES ---
def safe_get_quote(input_mint, output_mint, amount, slippage=1500):
    url = "https://quote-api.jup.ag/v6/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount,
        "slippageBps": slippage
    }
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        response = session.get(url, params=params, timeout=15)
        return response.json()
    except Exception as e:
        print(f"Erro na Jupiter: {e}")
        return None

# --- COMANDOS ---
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        bot.reply_to(message, "Bot Ativo!")

    @bot.message_handler(func=lambda m: True)
    def handle_message(message):
        if len(message.text) > 30:
            sol_mint = "So11111111111111111111111111111111111111112"
            quote = safe_get_quote(sol_mint, message.text, 100000000)
            if quote:
                bot.send_message(message.chat.id, f"Cotação: {quote.get('outAmount')}")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    # Inicia Flask
    Thread(target=run_flask).start()
    
    if bot:
        print("Iniciando polling do Telegram...")
        bot.polling(none_stop=True)
    else:
        print("Bot não iniciado devido a erro no Token. O Flask continuará rodando.")
        while True: time.sleep(10)
