import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÃO ---
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "SEU_ID_AQUI"  # Mande /id para o bot @userinfobot para descobrir o seu
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Memória temporária para não repetir o mesmo token
seen_tokens = set()

@app.route('/')
def health_check(): return "Hunter Online", 200

def get_market_data():
    """Busca os tokens mais promissores da rede Solana"""
    try:
        # Busca os tokens com maior volume/atividade recente na Solana
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url, timeout=10).json()
        return response.get('pairs', [])
    except:
        return []

def scan_and_alert():
    """Filtro de Elite: Só envia o que tem potencial real"""
    print("Iniciando monitoramento de mercado...")
    while True:
        pairs = get_market_data()
        for pair in pairs:
            token_address = pair['baseToken']['address']
            
            if token_address in seen_tokens:
                continue

            # --- SEUS FILTROS DE LUCRO ---
            liquidity = pair.get('liquidity', {}).get('usd', 0)
            mcap = pair.get('fdv', 0)
            vol_1h = pair.get('volume', {}).get('h1', 0)
            
            # FILTRO: Liquidez > $40k, MCap entre $60k e $600k (Gema), Volume Forte
            if 40000 < liquidity < 400000 and 60000 < mcap < 800000:
                if vol_1h > (mcap * 0.15): # Volume deve ser > 15% do Market Cap
                    
                    # --- CÁLCULO DE ENTRADA E SAÍDA ---
                    price = float(pair['priceUsd'])
                    target_2x = price * 2
                    target_5x = price * 5
                    stop_loss = price * 0.65 # -35%
                    
                    msg = (
                        f"🚀 **GEMA VALIDADA DETECTADA** 🚀\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💎 **Token:** {pair['baseToken']['name']} ({pair['baseToken']['symbol']})\n"
                        f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                        f"💧 **Liquidez:** `${liquidity:,.0f}`\n"
                        f"🔥 **Vol 1h:** `${vol_1h:,.0f}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🟢 **PONTO DE ENTRADA:** `{price:.10f}`\n"
                        f"🎯 **ALVO 1 (2x):** `{target_2x:.10f}`\n"
                        f"🚀 **ALVO 2 (5x):** `{target_5x:.10f}`\n"
                        f"🛑 **STOP LOSS:** `{stop_loss:.10f}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{token_address})\n"
                        f"🔗 [Gráfico DexScreener]({pair['url']})\n"
                        f"⚠️ *Checar se LP está Burned na GMGN!*"
                    )
                    
                    try:
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
                        seen_tokens.add(token_address)
                    except:
                        pass
        
        # Limpa o histórico a cada 200 tokens para não pesar a memória
        if len(seen_tokens) > 200: seen_tokens.clear()
        time.sleep(60) # Varredura a cada 1 minuto

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Inicia o Servidor de Health Check (Koyeb precisa disso)
    Thread(target=run_flask).start()
    # Inicia o Scanner Automático
    scan_and_alert()
