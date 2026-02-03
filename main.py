import os
import time
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. CONFIGURAÇÃO DO SERVIDOR WEB (Obrigatório para o Koyeb) ---
app = Flask('')

@app.route('/')
def home():
    # Isso responde ao Health Check do Koyeb
    return "O Bot está rodando!", 200

def run_flask():
    # O Koyeb usa a porta 8080 por padrão
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- 2. INICIALIZAÇÃO DO BOT ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = None

if TOKEN:
    try:
        # Tira espaços em branco que podem vir do copiar/colar
        bot = TeleBot(TOKEN.strip())
        print("✅ Bot do Telegram inicializado.")
    except Exception as e:
        print(f"❌ Erro ao validar TOKEN: {e}")
else:
    print("⚠️ AVISO: Variável TELEGRAM_TOKEN não encontrada. O bot não responderá.")

# --- 3. LÓGICA DE COTAÇÃO JUPITER ---
def get_quote(mint):
    url = f"https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={mint}&amount=100000000&slippageBps=100"
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1)
    session.mount('https://', HTTPAdapter(max_retries=retries))
    try:
        res = session.get(url, timeout=10)
        return res.json()
    except:
        return None

# --- 4. TRATAMENTO DE MENSAGENS ---
if bot:
    @bot.message_handler(func=lambda m: True)
    def handle(m):
        if len(m.text) > 30:
            bot.reply_to(m, "Buscando preço...")
            data = get_quote(m.text)
            if data:
                bot.send_message(m.chat.id, f"Resultado: {data.get('outAmount')}")
            else:
                bot.send_message(m.chat.id, "Erro na API da Jupiter.")

# --- 5. LOOP PRINCIPAL ---
if __name__ == "__main__":
    # Inicia o Flask em uma thread separada
    server_thread = Thread(target=run_flask)
    server_thread.daemon = True
    server_thread.start()
    
    # Mantém o processo principal rodando
    if bot:
        print("🚀 Iniciando Polling...")
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=20)
            except Exception as e:
                print(f"Erro no Polling: {e}")
                time.sleep(5)
    else:
        # Se o bot falhar, mantemos o servidor Flask vivo para o Koyeb não dar erro
        print("😴 Bot inativo (sem Token), mas servidor Web ativo para evitar erro de deploy.")
        while True:
            time.sleep(60)
