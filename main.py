import os
import time
import requests
from flask import Flask
from threading import Thread
from telebot import TeleBot
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- SERVIDOR WEB PARA HEALTH CHECK ---
app = Flask('')

@app.route('/')
def home():
    return "Sniper Bot Online", 200

def run_flask():
    # Usa a porta 8080 exigida pelo Koyeb
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- INICIALIZAÇÃO DO BOT ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = None

if TOKEN:
    try:
        # strip() remove espaços invisíveis que podem causar erro
        bot = TeleBot(TOKEN.strip())
        print("✅ Bot configurado.")
    except Exception as e:
        print(f"❌ Erro no Token: {e}")
else:
    print("⚠️ Variável TELEGRAM_TOKEN não encontrada.")

# --- CONSULTA JUPITER ---
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

# --- COMANDOS ---
if bot:
    @bot.message_handler(commands=['start'])
    def start(m):
        bot.reply_to(m, "🤖 Sniper Bot Ativo! Envie o contrato do token.")

    @bot.message_handler(func=lambda m: True)
    def handle(m):
        if len(m.text) > 30:
            bot.reply_to(m, "🔍 Verificando preço na Jupiter...")
            data = get_quote(m.text)
            if data:
                price = data.get('outAmount')
                bot.send_message(m.chat.id, f"Cotação para 0.1 SOL: {price}")
            else:
                bot.send_message(m.chat.id, "❌ Erro na consulta. Tente novamente.")

# --- EXECUÇÃO ---
if __name__ == "__main__":
    # Inicia Flask primeiro para o deploy passar
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    if bot:
        print("🚀 Polling iniciado...")
        while True:
            try:
                bot.polling(none_stop=True, interval=1, timeout=20)
            except Exception as e:
                print(f"Erro: {e}")
                time.sleep(5)
    else:
        while True: time.sleep(60)
