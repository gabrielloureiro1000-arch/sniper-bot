import time
import requests
import telebot
import threading
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "SEU_TOKEN"
CHAT_ID = "SEU_CHAT_ID"
PRIVATE_KEY = "SUA_CHAVE_PRIVADA"
RPC_URL = "https://api.mainnet-beta.solana.com"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# --- SAÚDE DO SERVIDOR (Para o Koyeb não derrubar) ---
@app.route('/')
def health_check():
    return "Bot is Running", 200

# --- LÓGICA DO BOT (Em Segundo Plano) ---
def hunter_loop():
    tokens_processados = set()
    print("Iniciando loop do Hunter...")
    
    while True:
        try:
            # Substitua pelo seu scanner real do GMGN
            contrato = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df" 
            
            if contrato not in tokens_processados:
                print(f"Alvo detectado: {contrato}")
                # Aqui entra sua função de swap_jup que passamos antes
                # bot.send_message(CHAT_ID, f"Compra tentada: {contrato}")
                tokens_processados.add(contrato)
            
            time.sleep(20) # Delay para evitar Connection Reset
        except Exception as e:
            print(f"Erro no loop: {e}")
            time.sleep(10)

# --- INICIALIZAÇÃO MULTI-TAREFA ---
if __name__ == "__main__":
    # 1. Inicia o Bot em uma Thread separada
    t = threading.Thread(target=hunter_loop)
    t.daemon = True
    t.start()

    # 2. Inicia o Flask na porta que o Koyeb exige
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
