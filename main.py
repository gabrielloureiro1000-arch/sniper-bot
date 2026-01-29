import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# CONFIGURAÇÃO FIXA
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866" 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
seen_tokens = set()

@app.route('/')
def health_check():
    return "OK", 200

def hunter_loop():
    """Scanner que envia as gemas direto para o seu Telegram"""
    print("🚀 Scanner iniciado sem conflitos!")
    # Tenta avisar que ligou. Se der erro de conflito aqui, o 'pass' ignora e continua.
    try:
        bot.send_message(CHAT_ID, "✅ **SISTEMA DESTRAVADO!** Monitorando Solana agora...")
    except:
        pass

    while True:
        try:
            # Busca dados da DexScreener
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            response = requests.get(url, timeout=20).json()
            pairs = response.get('pairs', [])

            for pair in pairs:
                addr = pair['baseToken']['address']
                if addr in seen_tokens: continue

                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol = pair.get('volume', {}).get('h1', 0)
                
                # FILTROS DE LUCRO
                if 40000 < liq < 500000 and 70000 < mcap < 1000000:
                    if vol > (mcap * 0.15):
                        price = float(pair['priceUsd'])
                        msg = (
                            f"🚨 **GEMA VALIDADA**\n"
                            f"📊 **MCap:** `${mcap:,.0f}` | 💧 **Liq:** `${liq:,.0f}`\n\n"
                            f"🟢 **ENTRADA:** `{price:.10f}`\n"
                            f"🎯 **ALVO (2x):** `{price*2:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [Link GMGN.ai](https://gmgn.ai/sol/token/{addr})"
                        )
                        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
                        seen_tokens.add(addr)
            
            if len(seen_tokens) > 500: seen_tokens.clear()
        except:
            pass
        time.sleep(60)

if __name__ == "__main__":
    # Inicia apenas o servidor de vida para a Koyeb não dar erro
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))))
    t.daemon = True
    t.start()
    
    # Inicia o scanner diretamente
    hunter_loop()
