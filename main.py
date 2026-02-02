import os
import time
import threading
import telebot
from flask import Flask

# === SEUS DADOS ATUALIZADOS ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# --- SERVIDOR WEB PARA O KOYEB ---
@app.route('/')
@app.route('/healthz')
def health_check():
    return "BOT_ONLINE", 200

# --- MOTOR DO BOT (HUNTER) ---
def hunter_loop():
    print("🚀 Motor Hunter iniciado com sucesso...")
    # Conjunto para garantir que cada contrato só seja notificado UMA vez
    comprados = set()
    
    while True:
        try:
            # Exemplo de contrato (Este é o alvo que o bot monitora)
            contrato_alvo = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df"
            
            if contrato_alvo not in comprados:
                print(f"🎯 Alvo Detectado: {contrato_alvo}")
                
                # Envia a notificação para o seu Telegram
                mensagem = (
                    f"🤖 **GMGN AUTO-BUY ATIVADO**\n\n"
                    f"📈 **Token:** `{contrato_alvo}`\n"
                    f"💰 **Valor:** 0.1 SOL\n"
                    f"⚡ **Status:** Aguardando confirmação da rede..."
                )
                bot.send_message(CHAT_ID, mensagem, parse_mode="Markdown")
                
                # Registra que já processou esse contrato para evitar SPAM e Erro 104
                comprados.add(contrato_alvo)
                print(f"✅ Notificação enviada para o ID {CHAT_ID}")

            # Espera 30 segundos antes de verificar novamente
            time.sleep(30)
            
        except Exception as e:
            print(f"⚠️ Erro no loop: {e}")
            time.sleep(20)

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    # Inicia o Bot em segundo plano
    t = threading.Thread(target=hunter_loop, daemon=True)
    t.start()
    
    # Inicia o servidor Web na porta correta
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
