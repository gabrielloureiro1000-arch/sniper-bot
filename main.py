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
    return "Hunter Explosivo Online", 200

def get_explosive_gems():
    """Busca moedas com alta velocidade de volume e baixa capitalização"""
    try:
        # Busca os pares mais ativos da Solana nas últimas horas
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url, timeout=20).json()
        return response.get('pairs', [])
    except:
        return []

def hunter_loop():
    print("🚀 Scanner de Ganhos Explosivos Iniciado!")
    
    try:
        bot.send_message(CHAT_ID, "🔥 **MODO EXPLOSIVO ATIVADO!**\nBuscando gemas com potencial de 10x-50x...")
    except:
        pass

    while True:
        try:
            pairs = get_explosive_gems()
            for pair in pairs:
                addr = pair['baseToken']['address']
                if addr in seen_tokens: continue

                # DADOS DO TOKEN
                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol_5m = pair.get('volume', {}).get('m5', 0) # Volume dos últimos 5 minutos
                vol_1h = pair.get('volume', {}).get('h1', 0)
                
                # --- FILTROS PARA GANHOS EXPLOSIVOS ---
                # 1. Liquidez mínima de $15k (Aceita moedas mais novas)
                # 2. Market Cap entre $20k e $300k (Onde nascem os 50x)
                # 3. Volume de 5 min deve ser alto (Indica "pumping" agora)
                if 15000 < liq < 300000 and 20000 < mcap < 500000:
                    if vol_5m > (liq * 0.10) or vol_1h > (mcap * 0.30):
                        
                        price = float(pair['priceUsd'])
                        
                        # CÁLCULO DE POTENCIAL (VALORES DE SAÍDA)
                        # Alvo 1: 3x (Recuperar capital + lucro)
                        # Alvo 2: 10x (Gema consolidada)
                        # Alvo 3: 50x (Moonshot explosivo)
                        saida_3x = price * 3
                        saida_10x = price * 10
                        saida_50x = price * 50
                        
                        msg = (
                            f"🚀 **GEMA EXPLOSIVA DETECTADA** 🚀\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"💎 **Token:** {pair['baseToken']['symbol']}\n"
                            f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                            f"💧 **Liquidez:** `${liq:,.0f}`\n"
                            f"🔥 **Vol (5m):** `${vol_5m:,.0f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🟢 **PREÇO DE ENTRADA:** `{price:.10f}`\n\n"
                            f"💰 **VALORES DE SAÍDA (POTENCIAL):**\n"
                            f"🎯 **Alvo 1 (3x):** `{saida_3x:.10f}`\n"
                            f"🚀 **Alvo 2 (10x):** `{saida_10x:.10f}`\n"
                            f"🌕 **Alvo 3 (50x):** `{saida_50x:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{addr})\n"
                            f"⚠️ *Atenção: Risco alto. Verifique se o LP está Burned!*"
                        )
                        
                        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
                        seen_tokens.add(addr)
            
            if len(seen_tokens) > 500: seen_tokens.clear()
        except:
            pass
        
        time.sleep(45) # Varredura mais rápida (cada 45 seg)

if __name__ == "__main__":
    # Mantém a Koyeb ativa
    port = int(os.environ.get("PORT", 8080))
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=port))
    t.daemon = True
    t.start()
    
    hunter_loop()
