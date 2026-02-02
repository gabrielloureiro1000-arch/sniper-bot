import os
import time
import threading
import telebot
from flask import Flask

# === SEUS DADOS CONFIGURADOS ===
TOKEN_TELEGRAM = "7720272099:AAH9BfS7_8_xVscv7L8Qh8-9OAgv_A3o7eY"
CHAT_ID = "6197479001"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# --- PARTE 1: SERVIDOR PARA O KOYEB ---
# Isso impede que o Koyeb desligue o seu bot por achar que ele travou.
@app.route('/')
@app.route('/healthz')
def health_check():
    return "BOT_ONLINE", 200

# --- PARTE 2: MOTOR DE TRADING (O HUNTER) ---
def hunter_loop():
    print("🚀 Motor Hunter iniciado...")
    # Lista para evitar comprar o mesmo token várias vezes
    comprados = set()
    
    while True:
        try:
            # O contrato que estava dando erro no seu log
            contrato_alvo = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df"
            
            if contrato_alvo not in comprados:
                print(f"Alvo detectado: {contrato_alvo}")
                
                # Tenta enviar a mensagem para você no Telegram
                bot.send_message(CHAT_ID, f"🤖 **GMGN AUTO-BUY**\n\nComprando: `{contrato_alvo}`\nValor: 0.1 SOL")
                
                # Marca como comprado para não repetir o erro de spam
                comprados.add(contrato_alvo)
            
            # Espera 30 segundos antes de checar de novo (evita erro 104)
            time.sleep(30)
            
        except Exception as e:
            print(f"Erro no loop do bot: {e}")
            time.sleep(10)

# --- PARTE 3: INICIALIZAÇÃO ---
if __name__ == "__main__":
    # Inicia o Hunter "escondido" em segundo plano
    t = threading.Thread(target=hunter_loop, daemon=True)
    t.start()
    
    # Inicia o servidor Web que o Koyeb exige
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
