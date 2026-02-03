import os
import time
import socket
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. CONFIGURAÇÃO DO SERVIDOR WEB (Essencial para o Koyeb) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Solana: Status Online"

def run_flask():
    # Porta 8080 é o padrão do Koyeb
    app.run(host='0.0.0.0', port=8080)

# --- 2. CARREGAMENTO SEGURO DO TOKEN ---
# Isso evita o erro 'NoneType' que aparece nos seus logs
TOKEN = os.getenv('TELEGRAM_TOKEN')

def get_bot():
    if not TOKEN:
        print("❌ ERRO: A variável 'TELEGRAM_TOKEN' está vazia ou não configurada.")
        return None
    try:
        instance = TeleBot(TOKEN)
        # Teste simples de validação
        print(f"✅ Token detectado: {TOKEN[:6]}***")
        return instance
    except Exception as e:
        print(f"❌ Erro ao validar token: {e}")
        return None

bot = get_bot()

# --- 3. LÓGICA DE COTAÇÃO JUPITER (Com correção de DNS) ---
def get_jupiter_quote(mint_address):
    url = "https://quote-api.jup.ag/v6/quote"
    sol_mint = "So11111111111111111111111111111111111111112"
    
    params = {
        "inputMint": sol_mint,
        "outputMint": mint_address,
        "amount": "100000000",  # 0.1 SOL
        "slippageBps": 100
    }

    # Sessão com tentativas automáticas para vencer o NameResolutionError
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        # Timeout curto para não travar o bot em loops infinitos
        response = session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️ Erro de conexão Jupiter: {e}")
        return None

# --- 4. COMANDOS DO TELEGRAM ---
if bot:
    @bot.message_handler(commands=['start'])
    def start(message):
        bot.reply_to(message, "🤖 Bot Online! Envie o contrato do token Solana para cotação.")

    @bot.message_handler(func=lambda m: True)
    def handle_msg(message):
        text = message.text.strip()
        if len(text) > 30: # Filtro básico para endereços Solana
            bot.reply_to(message, "🔍 Consultando Jupiter API...")
            data = get_jupiter_quote(text)
            if data:
                price = data.get('outAmount')
                bot.send_message(message.chat.id, f"✅ Cotação encontrada!\nRetorno: {price} unidades.")
            else:
                bot.send_message(message.chat.id, "❌ Falha no DNS/API. Tente novamente em 10 segundos.")

# --- 5. EXECUÇÃO ---
if __name__ == "__main__":
    # Inicia servidor Web para o Health Check
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    if bot:
        print("🚀 Bot iniciando polling...")
        bot.polling(none_stop=True)
    else:
        print("🛑 Bot parado: Corrija o TOKEN nas variáveis de ambiente do Koyeb.")
        # Mantém o processo vivo para o Flask responder e você ler os logs
        while True:
            time.sleep(60)
