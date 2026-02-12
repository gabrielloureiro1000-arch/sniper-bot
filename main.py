import os
import time
import requests
import threading
from flask import Flask
import telebot

# --- CONFIGURAÇÃO ---
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
app = Flask('')

# Inicializa o bot com um timeout maior para evitar quedas bobas
bot = telebot.TeleBot(TOKEN, threaded=False)

@app.route('/')
def home():
    return "Sniper Vivo e Operante", 200

def buscar_tokens():
    print("🛰️ Iniciando busca de tokens...")
    while True:
        try:
            # DexScreener costuma ser mais estável no Render
            response = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=15)
            if response.status_code == 200:
                tokens = response.json()
                print(f"🔎 Scanner: {len(tokens)} tokens analisados.")
            
            # Pausa longa para não ser bloqueado por excesso de requisições
            time.sleep(60)
        except Exception as e:
            print(f"❌ Erro no Scanner: {e}")
            time.sleep(30)

def rodar_bot():
    print("🤖 Tentando conectar ao Telegram...")
    while True:
        try:
            # remove_webhook ajuda a limpar conexões presas que causam o erro 409
            bot.remove_webhook()
            bot.polling(none_stop=True, interval=5, timeout=20)
        except Exception as e:
            print(f"⚠️ Erro no Bot (provável 409 ou rede): {e}")
            # Se der erro 409, ele espera 20 segundos para a outra instância morrer
            time.sleep(20)

if __name__ == "__main__":
    # 1. Flask para o Render não dar "Port Timeout"
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    
    # 2. Scanner em segundo plano
    threading.Thread(target=buscar_tokens, daemon=True).start()
    
    # 3. Bot no loop principal
    rodar_bot()
