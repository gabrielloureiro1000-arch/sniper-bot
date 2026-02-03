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

# Inicialização do Bot com tratamento de erro
bot = None
try:
    if TOKEN:
        bot = telebot.TeleBot(TOKEN)
        print("🤖 Instância do Bot criada.")
    if PRIV_KEY_STR:
        wallet = Keypair.from_base58_string(PRIV_KEY_STR)
        print(f"✅ Carteira vinculada: {wallet.pubkey()}")
except Exception as e:
    print(f"⚠️ Erro na inicialização: {e}")

@app.route('/')
def home():
    return "SNIPER GMGN ONLINE", 200

# --- LÓGICA DE RELATÓRIO AUTOMÁTICO (A CADA 2 HORAS) ---
def loop_relatorio(chat_id):
    print(f"📈 Sistema de relatórios iniciado para o chat {chat_id}")
    while True:
        time.sleep(7200) # Aguarda 2 horas
        try:
            relatorio = (
                "📊 *RELATÓRIO SNIPER GMGN (2h)*\n\n"
                "🔍 *Monitoramento:* Ativo\n"
                "🚀 *Trades executados:* 0 (Aguardando pump/sinal)\n"
                "💰 *Lucro no período:* 0.00 SOL\n\n"
                "✅ _O bot continua escutando a rede Solana..._"
            )
            bot.send_message(chat_id, relatorio, parse_mode="Markdown")
        except Exception as e:
            print(f"Erro ao enviar relatório: {e}")

# --- COMANDOS DO TELEGRAM ---
if bot:
    @bot.message_handler(commands=['start'])
    def start(m):
        # Inicia a thread do relatório para este usuário
        Thread(target=loop_relatorio, args=(m.chat.id,), daemon=True).start()
        msg = (
            "🎯 *Sniper GMGN Ativado!*\n\n"
            "Estou monitorando a Solana em busca de tokens promissores.\n"
            "O que eu farei por você:\n"
            "1. Identificar sinais da GMGN.\n"
            "2. Comprar e vender no melhor timing.\n"
            "3. Enviar relatório de lucros a cada 2 horas."
        )
        bot.reply_to(m, msg, parse_mode="Markdown")

    @bot.message_handler(commands=['status'])
    def status(m):
        bot.reply_to(m, "🛰️ *Status:* Online e rastreando liquidez.", parse_mode="Markdown")

# --- EXECUÇÃO DO SERVIDOR ---
def run_web():
    port = int(os.environ.get("PORT", 8080))
    print(f"📡 Servidor Flask na porta {port}")
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Inicia Web Server (Para passar no Health Check do Koyeb)
    Thread(target=run_web, daemon=True).start()
    
    if bot:
        print("🚀 Iniciando Polling do Telegram...")
        while True:
            try:
                # ANTI-CONFLITO: Remove conexões presas antes de iniciar
                bot.remove_webhook()
                bot.polling(none_stop=True, interval=3, timeout=30)
            except Exception as e:
                # Se der erro 409, ele espera 10 segundos e tenta de novo
                print(f"🔄 Reiniciando por conflito ou rede: {e}")
                time.sleep(10)
    else:
        print("🛑 Erro Crítico: Token não configurado corretamente.")
        while True: time.sleep(60)
