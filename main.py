import os
import time
import socket
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURAÇÃO DO FLASK (Para o Koyeb manter vivo) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Online e Saudável!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = os.getenv('TELEGRAM_TOKEN') # Sua variável no Koyeb
bot = TeleBot(TOKEN)

# --- FUNÇÃO DE DIAGNÓSTICO DE REDE ---
def diagnostic():
    print("\n--- INICIANDO DIAGNÓSTICO DE REDE ---")
    hosts = ['google.com', 'quote-api.jup.ag', 'api.mainnet-beta.solana.com']
    for host in hosts:
        try:
            ip = socket.gethostbyname(host)
            print(f"✅ DNS OK: {host} -> {ip}")
        except Exception as e:
            print(f"❌ ERRO DNS: {host} não pôde ser resolvido: {e}")
    print("------------------------------------\n")

# --- SISTEMA DE REQUISIÇÃO COM RETRY (CORREÇÃO DO ERRO 104) ---
def safe_get_quote(input_mint, output_mint, amount, slippage=1500):
    url = "https://quote-api.jup.ag/v6/quote"
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": amount,
        "slippageBps": slippage
    }
    
    session = requests.Session()
    # Tenta 5 vezes com espera progressiva (backoff)
    retries = Retry(
        total=5,
        backoff_factor=2, 
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Erro no Swap/Jupiter: {e}")
        return None

# --- COMANDOS DO TELEGRAM ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Robô de Swap Solana Ativo! Aguardando sinais...")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Exemplo simples: se receber um endereço, tenta buscar cotação
    if len(message.text) > 30: # Provável endereço de token
        bot.send_message(message.chat.id, "Buscando cotação na Jupiter...")
        # Mint da SOL (fixo) e Mint do Token (da mensagem)
        sol_mint = "So11111111111111111111111111111111111111112"
        quote = safe_get_quote(sol_mint, message.text, 100000000) # 0.1 SOL
        
        if quote:
            out_amount = quote.get('outAmount', '0')
            bot.send_message(message.chat.id, f"Cotação recebida! Valor estimado: {out_amount}")
        else:
            bot.send_message(message.chat.id, "Erro de conexão com a API da Jupiter. Tentando novamente em instantes...")

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    diagnostic() # Roda o teste de rede antes de tudo
    
    # Inicia o Flask em uma thread separada
    t = Thread(target=run_flask)
    t.start()
    
    # Inicia o bot do Telegram
    print("Bot iniciando polling...")
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            print(f"Erro no Polling (Telegram): {e}")
            time.sleep(5)
