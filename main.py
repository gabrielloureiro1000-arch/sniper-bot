import os
import time
import socket
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURAÇÃO DO SERVIDOR WEB (Para o Koyeb) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Solana operando normalmente!"

def run_flask():
    # O Koyeb exige que o app rode na porta 8080
    app.run(host='0.0.0.0', port=8080)

# --- CONFIGURAÇÃO DO BOT ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = None

if TOKEN:
    try:
        bot = TeleBot(TOKEN)
        print("✅ Token do Telegram carregado com sucesso.")
    except Exception as e:
        print(f"❌ Erro ao iniciar bot: {e}")
else:
    print("❌ Erro: Variável TELEGRAM_TOKEN não encontrada.")

# --- FUNÇÃO DE BUSCA NA JUPITER (Resiliente) ---
def get_jupiter_quote(mint_address):
    # Endereço da SOL (Input)
    sol_mint = "So11111111111111111111111111111111111111112"
    url = "https://quote-api.jup.ag/v6/quote"
    
    params = {
        "inputMint": sol_mint,
        "outputMint": mint_address,
        "amount": "100000000", # 0.1 SOL em lamports
        "slippageBps": 50 # 0.5% de slippage
    }

    session = requests.Session()
    # Tenta 5 vezes antes de desistir do DNS/Conexão
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Erro na Jupiter para o token {mint_address}: {e}")
        return None

# --- COMANDOS DO BOT ---
if bot:
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        bot.reply_to(message, "🤖 Bot Solana Ativo!\nEnvie o endereço de um token para ver o preço.")

    @bot.message_handler(func=lambda m: True)
    def handle_address(message):
        token_address = message.text.strip()
        
        # Verifica se parece um endereço Solana (comprimento comum)
        if len(token_address) >= 32 and len(token_address) <= 44:
            bot.send_message(message.chat.id, "🔍 Consultando Jupiter API...")
            data = get_jupiter_quote(token_address)
            
            if data:
                out_amount = int(data.get('outAmount', 0)) / 10**6 # Exemplo para tokens com 6 decimais
                bot.reply_to(message, f"📈 Cotação para 0.1 SOL:\nReceberá aprox: {out_amount:.2f} do token.")
            else:
                bot.reply_to(message, "❌ Não consegui obter a cotação. A API pode estar instável.")
        else:
            bot.reply_to(message, "Endereço inválido. Envie um contrato Solana válido.")

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    # Inicia o Flask em segundo plano
    Thread(target=run_flask).start()
    
    # Inicia o Polling do Telegram
    if bot:
        print("Iniciando escuta do Telegram...")
        while True:
            try:
                bot.polling(none_stop=True, interval=0, timeout=20)
            except Exception as e:
                print(f"Erro no polling: {e}")
                time.sleep(5)
