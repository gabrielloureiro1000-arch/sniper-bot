import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# ==========================================================
# CONFIGURAÇÃO FIXA - ID: 5080696866
# ==========================================================
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866" 
# ==========================================================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
seen_tokens = set()

# COMANDO DE LIMPEZA PARA DESTRAVAR
try:
    bot.remove_webhook()
    time.sleep(2)
except:
    pass

@app.route('/')
def health_check():
    return "Hunter Pro Online", 200

# TESTE MANUAL: Digite /status no Telegram para ver se ele responde
@bot.message_handler(commands=['status'])
def send_status(message):
    bot.reply_to(message, "✅ O Hunter está online e monitorando a Solana!")

def get_market_data():
    try:
        # Busca tokens ativos
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url, timeout=20).json()
        return response.get('pairs', [])
    except:
        return []

def hunter_loop():
    """Monitora o mercado e envia alertas automáticos"""
    # Aviso imediato no seu Telegram que o bot ligou
    try:
        bot.send_message(CHAT_ID, "🚀 **BOT LIGADO!** Iniciando varredura na Solana...")
    except Exception as e:
        print(f"Erro ao enviar msg inicial: {e}")

    while True:
        try:
            pairs = get_market_data()
            for pair in pairs:
                if pair.get('chainId') != 'solana': continue
                
                token_address = pair['baseToken']['address']
                if token_address in seen_tokens: continue

                # Filtros de Lucro
                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol = pair.get('volume', {}).get('h1', 0)
                
                # Se atender aos requisitos, avisa você
                if 30000 < liq < 500000 and 60000 < mcap < 1000000:
                    if vol > (mcap * 0.12):
                        price = float(pair['priceUsd'])
                        
                        msg = (
                            f"🚨 **GEMA DETECTADA: {pair['baseToken']['symbol']}**\n"
                            f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                            f"💧 **Liquidez:** `${liq:,.0f}`\n\n"
                            f"🟢 **ENTRADA:** `{price:.10f}`\n"
                            f"🎯 **ALVO (2x):** `{price*2:.10f}`\n"
                            f"🛑 **STOP:** `{price*0.7:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [GMGN.ai](https://gmgn.ai/sol/token/{token_address})\n"
                        )
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
                        seen_tokens.add(token_address)
            
            if len(seen_tokens) > 500: seen_tokens.clear()
        except:
            pass
        time.sleep(60)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Inicia Servidor de Vida
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Inicia Escuta de Comandos (/status)
    Thread(target=bot.infinity_polling).start()
    
    # Inicia o Caçador de Moedas
    time.sleep(5)
    hunter_loop()
