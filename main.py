import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# CONFIGURAÇÃO FIXA - SEU ID
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866" 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
seen_tokens = set()

@app.route('/')
def health_check():
    return "Hunter Ativo", 200

def hunter_loop():
    """Scanner que envia gemas direto para o seu Telegram"""
    print("🚀 Scanner iniciado com sucesso!")
    
    # Mensagem de confirmação que o bot ligou
    try:
        bot.send_message(CHAT_ID, "✅ **SISTEMA DESTRAVADO!** O Hunter está caçando gemas na Solana...")
    except:
        pass

    while True:
        try:
            # Busca dados do mercado
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            response = requests.get(url, timeout=20).json()
            pairs = response.get('pairs', [])

            for pair in pairs:
                addr = pair['baseToken']['address']
                if addr in seen_tokens: continue

                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol = pair.get('volume', {}).get('h1', 0)
                
                # FILTROS DE ELITE (Só o que dá lucro)
                if 40000 < liq < 500000 and 70000 < mcap < 1000000:
                    if vol > (mcap * 0.15):
                        price = float(pair['priceUsd'])
                        msg = (
                            f"🚨 **GEMA VALIDADA** 🚨\n"
                            f"📊 **MCap:** `${mcap:,.0f}` | 💧 **Liq:** `${liq:,.0f}`\n\n"
                            f"🟢 **ENTRADA:** `{price:.10f}`\n"
                            f"🎯 **ALVO (2x):** `{price*2:.10f}`\n"
                            f"🛑 **STOP:** `{price*0.7:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [Link GMGN.ai](https://gmgn.ai/sol/token/{addr})"
                        )
                        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
                        seen_tokens.add(addr)
            
            if len(seen_tokens) > 500: seen_tokens.clear()
        except Exception as e:
            print(f"Erro no loop: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    # Inicia o servidor de vida para a Koyeb
    port = int(os.environ.get("PORT", 8080))
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=port))
    t.daemon = True
    t.start()
    
    # Inicia apenas o Scanner (Sem infinity_polling para evitar o erro 409)
    hunter_loop()
