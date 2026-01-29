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

# RESOLVE O ERRO 409: Limpa qualquer conexão anterior
try:
    bot.remove_webhook()
    time.sleep(2)
except:
    pass

@app.route('/')
def health_check():
    return "Hunter Ativo", 200

def get_market_data():
    try:
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url, timeout=20).json()
        return response.get('pairs', [])
    except:
        return []

def hunter_loop():
    """Varredura automática de Gemas"""
    # Envia aviso de que o sistema resetou com sucesso
    try:
        bot.send_message(CHAT_ID, "🚀 **HUNTER REINICIADO!** Monitorando a Solana...")
    except:
        print("Erro ao enviar mensagem inicial.")

    while True:
        try:
            pairs = get_market_data()
            for pair in pairs:
                if pair.get('chainId') != 'solana': continue
                addr = pair['baseToken']['address']
                if addr in seen_tokens: continue

                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol = pair.get('volume', {}).get('h1', 0)
                
                # FILTROS DE LUCRO (Ajustados para maior precisão)
                if 35000 < liq < 500000 and 70000 < mcap < 1000000:
                    if vol > (mcap * 0.15):
                        price = float(pair['priceUsd'])
                        msg = (
                            f"🚨 **GEMA VALIDADA** 🚨\n"
                            f"📊 **MCap:** `${mcap:,.0f}`\n"
                            f"💧 **Liquidez:** `${liq:,.0f}`\n\n"
                            f"🟢 **ENTRADA:** `{price:.10f}`\n"
                            f"🎯 **ALVO (2x):** `{price*2:.10f}`\n"
                            f"🛑 **STOP LOSS:** `{price*0.7:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})\n"
                        )
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
                        seen_tokens.add(addr)
            
            if len(seen_tokens) > 500: seen_tokens.clear()
        except:
            pass
        time.sleep(60)

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # 1. Inicia Health Check
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # 2. Inicia Polling (ignora erros de conflito 409 pendentes)
    Thread(target=bot.infinity_polling, kwargs={'skip_pending': True}).start()
    
    # 3. Inicia o Scanner
    time.sleep(5)
    hunter_loop()
