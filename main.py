import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. CONFIGURAÇÃO DO SERVIDOR WEB (Essencial para o Koyeb) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Sniper Solana: ONLINE", 200

def run_flask():
    # O Koyeb usa a porta 8080 por padrão
    port = int(os.environ.get("PORT", 8080))
    print(f"📡 Iniciando servidor Web na porta {port}...")
    app.run(host='0.0.0.0', port=port)

# --- 2. INICIALIZAÇÃO ROBUSTA DO BOT (Passo C) ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
bot = None

print("--- DIAGNÓSTICO DE INICIALIZAÇÃO ---")
if TOKEN:
    try:
        # Limpa espaços em branco e valida o bot
        clean_token = TOKEN.strip()
        bot = telebot.TeleBot(clean_token)
        print(f"✅ Variável 'TELEGRAM_TOKEN' encontrada!")
        print(f"✅ Prefixo do Token: {clean_token[:10]}...")
    except Exception as e:
        print(f"❌ ERRO ao configurar o bot: {e}")
else:
    print("❌ ERRO CRÍTICO: Variável 'TELEGRAM_TOKEN' não encontrada no sistema.")
    print("👉 Certifique-se de que o nome no painel do Koyeb é exatamente TELEGRAM_TOKEN")

# --- 3. LÓGICA DE COTAÇÃO JUPITER ---
def get_jupiter_quote(mint_address):
    # Endereço da SOL e URL da Jupiter
    sol_mint = "So11111111111111111111111111111111111111112"
    url = f"https://quote-api.jup.ag/v6/quote"
    
    params = {
        "inputMint": sol_mint,
        "outputMint": mint_address,
        "amount": "100000000", # 0.1 SOL
        "slippageBps": 100
    }

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        response = session.get(url, params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f"⚠️ Erro na Jupiter API: {e}")
        return None

# --- 4. COMANDOS DO TELEGRAM ---
if bot:
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        bot.reply_to(message, "🤖 Bot Sniper Solana Ativo!\n\nEnvie o endereço do contrato (Mint Address) para ver a cotação.")

    @bot.message_handler(func=lambda m: True)
    def handle_address(message):
        token_address = message.text.strip()
        
        # Filtro simples para endereços Solana (geralmente 32-44 caracteres)
        if len(token_address) >= 32:
            bot.send_message(message.chat.id, "🔍 Consultando Jupiter...")
            data = get_jupiter_quote(token_address)
            
            if data and 'outAmount' in data:
                # Exemplo simplificado de exibição (ajuste decimais se necessário)
                saida = int(data['outAmount'])
                bot.reply_to(message, f"📈 Cotação para 0.1 SOL:\n\nReceberá aprox: {saida} unidades do token.")
            else:
                bot.reply_to(message, "❌ Não foi possível obter a cotação. Verifique o contrato.")
        else:
            bot.reply_to(message, "⚠️ Isso não parece um endereço de contrato Solana válido.")

# --- 5. EXECUÇÃO PRINCIPAL ---
if __name__ == "__main__":
    # Inicia o Flask em uma thread separada para não travar o bot
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    if bot:
        print("🚀 Iniciando Polling do Telegram (Escutando mensagens)...")
        while True:
            try:
                bot.polling(none_stop=True, interval=0, timeout=20)
            except Exception as e:
                # O erro 409 (Conflict) será capturado aqui e o bot tentará reconectar
                print(f"🔄 Reiniciando Polling por erro: {e}")
                time.sleep(5)
    else:
        print("🛑 O Bot não foi iniciado devido à falta do Token.")
        # Mantém o processo vivo para o Flask continuar respondendo ao Koyeb
        while True:
            time.sleep(60)
