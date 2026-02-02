import os
import time
import threading
import telebot
from flask import Flask

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "SEU_TOKEN_AQUI")
CHAT_ID = os.environ.get("CHAT_ID", "SEU_CHAT_ID_AQUI")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# 1. Rota de Health Check (Essencial para o Koyeb)
@app.route('/healthz')
@app.route('/')
def health():
    return "OK", 200

# 2. Motor do Bot
def bot_worker():
    print("🚀 Motor do Hunter iniciado...")
    # Evita que o bot tente enviar mensagens antes da rede estar estável
    time.sleep(10) 
    
    tokens_comprados = set()
    
    while True:
        try:
            # Lógica de detecção (exemplo)
            contrato_alvo = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df"
            
            if contrato_alvo not in tokens_comprados:
                # print(f"Executando buy para {contrato_alvo}")
                # bot.send_message(CHAT_ID, f"🎯 Alvo Detectado: {contrato_alvo}")
                tokens_comprados.add(contrato_alvo)
            
            time.sleep(30) # Delay seguro para não ser banido por spam
        except Exception as e:
            print(f"Erro no Worker: {e}")
            time.sleep(10)

# 3. Inicialização
if __name__ == "__main__":
    # Inicia o bot em uma thread separada (background)
    worker_thread = threading.Thread(target=bot_worker, daemon=True)
    worker_thread.start()
    
    # Inicia o servidor Web (foreground)
    # O Koyeb injeta automaticamente a variável PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
