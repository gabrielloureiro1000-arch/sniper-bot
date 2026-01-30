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
    return "Bot Online", 200

def hunter_loop():
    # TESTE DE CONEXÃO: Isso deve chegar no seu Telegram em 1 minuto
    print("🚀 Iniciando Scanner Ultra...")
    try:
        bot.send_message(CHAT_ID, "🛰️ **SCANNER ATIVADO!**\nO bot está rodando e monitorando a Solana agora.\nSe houver silêncio, é porque nenhuma moeda prestou ainda.")
    except Exception as e:
        print(f"Erro ao falar com Telegram: {e}")

    while True:
        try:
            # API da DexScreener
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            response = requests.get(url, timeout=20).json()
            pairs = response.get('pairs', [])

            for pair in pairs:
                # Filtro básico de segurança
                if pair.get('chainId') != 'solana': continue
                
                addr = pair['baseToken']['address']
                if addr in seen_tokens: continue

                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol_5m = pair.get('volume', {}).get('m5', 0)
                
                # --- FILTRO ULTRA SENSÍVEL (Pega moedas bem no início) ---
                # Liquidez > $8k (Mínimo absoluto para não ser travada)
                # Market Cap > $10k
                # Volume de 5min > $1k (Alguém está comprando agora)
                if liq > 8000 and mcap > 10000 and vol_5m > 1000:
                    
                    price = float(pair['priceUsd'])
                    
                    # Cálculo de Alvos de Saída
                    alvo_2x = price * 2
                    alvo_10x = price * 10
                    
                    msg = (
                        f"🔥 **ALERTA DE GEMA DETECTADA** 🔥\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💎 **Token:** {pair['baseToken']['symbol']}\n"
                        f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                        f"💧 **Liquidez:** `${liq:,.0f}`\n"
                        f"🚀 **Vol (5m):** `${vol_5m:,.0f}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🟢 **ENTRADA:** `{price:.10f}`\n\n"
                        f"💰 **ALVOS DE LUCRO:**\n"
                        f"🎯 **Dobrar (2x):** `{alvo_2x:.10f}`\n"
                        f"🚀 **Explodir (10x):** `{alvo_10x:.10f}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})\n"
                        f"⚠️ *Confira o selo 'Burned' na GMGN antes de entrar!*"
                    )
                    
                    bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
                    seen_tokens.add(addr)
            
            if len(seen_tokens) > 1000: seen_tokens.clear()
            
        except Exception as e:
            print(f"Erro no loop: {e}")
            
        time.sleep(30) # Varredura rápida (30 segundos)

if __name__ == "__main__":
    # Servidor para Koyeb
    port = int(os.environ.get("PORT", 8080))
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=port))
    t.daemon = True
    t.start()
    
    hunter_loop()
