
import os
import telebot
import requests
import time
from threading import Thread

# --- CONFIGURAÇÃO ---
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = 5080696866 # Você precisa colocar seu ID do Telegram aqui para receber os alertas
bot = telebot.TeleBot(TOKEN)

def get_new_gems():
    """Busca tokens recentes com filtros de segurança"""
    try:
        # Buscamos os pares mais ativos nas últimas horas
        url = "https://api.dexscreener.com/latest/dex/search?q=solana"
        response = requests.get(url).json()
        
        if not response.get('pairs'):
            return []

        valid_gems = []
        for pair in response['pairs'][:20]: # Analisa os 20 mais recentes/ativos
            liquidity = pair.get('liquidity', {}).get('usd', 0)
            mcap = pair.get('fdv', 0)
            volume_1h = pair.get('volume', {}).get('h1', 0)
            
            # --- FILTRO DE ELITE PARA NÃO PERDER DINHEIRO ---
            # 1. Liquidez mínima de $30k (evita rugpulls básicos)
            # 2. Market Cap entre $50k e $500k (potencial de gema)
            # 3. Volume em 1h deve ser pelo menos 20% do Market Cap
            if 30000 < liquidity < 500000 and 50000 < mcap < 800000:
                if volume_1h > (mcap * 0.2):
                    valid_gems.append(pair)
        
        return valid_gems
    except Exception as e:
        print(f"Erro no Hunter: {e}")
        return []

def scanner_loop():
    """Loop infinito que monitora o mercado e envia alertas"""
    seen_tokens = set()
    print("Scanner de Gemas Iniciado...")
    
    while True:
        gems = get_new_gems()
        for gem in gems:
            contract = gem['baseToken']['address']
            if contract not in seen_tokens:
                # --- LÓGICA DE TRADING (ENTRADA E SAÍDA) ---
                price = float(gem['priceUsd'])
                entry_price = price * 1.05 # Sugestão: entrar com 5% de margem
                target_1 = price * 2.0    # Saída 1: 2x (100% lucro)
                target_2 = price * 5.0    # Saída 2: 5x (Moonshot)
                stop_loss = price * 0.7   # Stop: -30%
                
                msg = (
                    f"🚨 **NOVA GEMA DETECTADA** 🚨\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💎 **Token:** {gem['baseToken']['name']} ({gem['baseToken']['symbol']})\n"
                    f"📊 **Market Cap:** ${gem['fdv']:,.0f}\n"
                    f"💧 **Liquidez:** ${gem['liquidity']['usd']:,.0f}\n"
                    f"📈 **Volume 1h:** ${gem['volume']['h1']:,.0f}\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 **ESTRATÉGIA DE TRADE:**\n"
                    f"📥 **Entrada sugerida:** `${entry_price:.8f}`\n"
                    f"💰 **Saída (Alvo 1):** `${target_1:.8f}` (2x)\n"
                    f"🚀 **Saída (Alvo 2):** `${target_2:.8f}` (5x)\n"
                    f"🛑 **Stop Loss:** `${stop_loss:.8f}`\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🔗 [GMGN.ai](https://gmgn.ai/sol/token/{contract})\n"
                    f"🔗 [DexScreener]({gem['url']})\n"
                )
                
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
                seen_tokens.add(contract)
        
        time.sleep(60) # Verifica a cada 1 minuto

if __name__ == "__main__":
    # Inicia o scanner em uma thread separada
    Thread(target=scanner_loop).start()
    bot.infinity_polling()
