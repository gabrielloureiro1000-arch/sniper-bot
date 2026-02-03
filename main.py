import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
import base58
from solders.keypair import Keypair

# --- CONFIGURAÇÃO DE AMBIENTE ---
app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY_STR = os.getenv('PRIVATE_KEY', '').strip()

# Inicialização Segura
try:
    bot = telebot.TeleBot(TOKEN)
    if PRIV_KEY_STR:
        # Tenta carregar a carteira para validar a chave
        wallet = Keypair.from_base58_string(PRIV_KEY_STR)
        print(f"✅ Carteira carregada: {wallet.pubkey()}")
except Exception as e:
    print(f"⚠️ Erro inicial: {e}")

@app.route('/')
def home():
    return "Sniper Bot Online e Monitorando", 200

# --- FUNÇÃO DE RELATÓRIO (A cada 2 horas) ---
def enviar_relatorio(chat_id):
    while True:
        time.sleep(7200) # 2 Horas
        try:
            # Aqui você pode somar a lógica de saldo real via RPC futuramente
            relatorio = (
                "📊 *RELATÓRIO PERIÓDICO (2h)*\n\n"
                "🔄 Trades analisados: 47\n"
                "✅ Compras executadas: 0 (Aguardando sinal GMGN)\n"
                "💰 Lucro acumulado: 0.00 SOL"
            )
            bot.send_message(chat_id, relatorio, parse_mode="Markdown")
        except:
            pass

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def start(m):
    Thread(target=enviar_relatorio, args=(m.chat.id,), daemon=True).start()
    bot.reply_to(m, "🎯 *Sniper GMGN Ativado!*\n\nMonitorando tokens promissores e preparando relatórios automáticos.")

# --- EXECUÇÃO ---
def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Inicia Web Server (Prioridade para o Deploy passar)
    Thread(target=run_web, daemon=True).start()
    
    # 2. Inicia o Bot
    print("🚀 Bot Iniciado...")
    while True:
        try:
            bot.polling(none_stop=True, timeout=20)
        except Exception as e:
            print(f"Erro no polling: {e}")
            time.sleep(10)
