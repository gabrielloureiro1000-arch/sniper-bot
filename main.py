import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# ==========================================================
# CONFIGURAÇÃO - SEU ID JÁ ESTÁ INSERIDO
# ==========================================================
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866" 
# ==========================================================

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
seen_tokens = set()

@app.route('/')
def health_check():
    return "Hunter Pro Online", 200

def get_market_data():
    """Busca tokens ativos na rede Solana via DexScreener"""
    try:
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url, timeout=15).json()
        return response.get('pairs', [])
    except:
        return []

def hunter_loop():
    """O CORAÇÃO DO BOT: Procura as gemas e te avisa no seu ID"""
    print("🚀 Scanner de Lucro Iniciado...")
    while True:
        try:
            pairs = get_market_data()
            for pair in pairs:
                token_address = pair['baseToken']['address']
                
                # Pula se já avisamos desse token
                if token_address in seen_tokens:
                    continue

                # --- FILTROS DE ELITE (Para não perder dinheiro) ---
                liquidity = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol_1h = pair.get('volume', {}).get('h1', 0)
                
                # REGRAS:
                # 1. Liquidez > $40k (Mínimo para ter saída)
                # 2. Market Cap entre $60k e $800k (Potencial de Gema)
                # 3. Volume forte (Pelo menos 15% do Market Cap em 1 hora)
                if 40000 < liquidity < 400000 and 60000 < mcap < 800000:
                    if vol_1h > (mcap * 0.15):
                        
                        # --- CÁLCULO DE ESTRATÉGIA ---
                        price = float(pair['priceUsd'])
                        target_2x = price * 2
                        target_5x = price * 5
                        stop_loss = price * 0.70 # -30%
                        
                        msg = (
                            f"🚨 **GEMA DETECTADA: {pair['baseToken']['symbol']}** 🚨\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                            f"💧 **Liquidez:** `${liquidity:,.0f}`\n"
                            f"🔥 **Volume 1h:** `${vol_1h:,.0f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🟢 **ENTRADA SUGERIDA:** `{price:.10f}`\n"
                            f"🎯 **ALVO 1 (2x):** `{target_2x:.10f}`\n"
                            f"🚀 **ALVO 2 (5x):** `{target_5x:.10f}`\n"
                            f"🛑 **STOP LOSS:** `{stop_loss:.10f}`\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 [Analisar na GMGN](https://gmgn.ai/sol/token/{token_address})\n"
                            f"🔗 [Gráfico DexScreener]({pair['url']})\n\n"
                            f"⚠️ *DICA: Só entre se o LP estiver 'Burned' na GMGN!*"
                        )
                        
                        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
                        seen_tokens.add(token_address)
            
            # Limpa memória para não travar
            if len(seen_tokens) > 500:
                seen_tokens.clear()
                
        except Exception as e:
            print(f"Erro no Loop: {e}")
            
        time.sleep(60) # Varredura a cada 1 minuto

def run_flask():
    """Mantém a Koyeb feliz (Health Check)"""
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # Inicia o servidor de vida primeiro
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # Dá 5 segundos para o servidor estabilizar
    time.sleep(5)
    
    # Começa a caçar gemas
    hunter_loop()
