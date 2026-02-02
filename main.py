import os
import time
import threading
import requests
import telebot
from flask import Flask

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# Memória global para evitar repetições (Dicionário com timestamp)
tokens_vistos = {}

@app.route('/')
@app.route('/healthz')
def health(): return "BOT_ESTAVEL", 200

def scanner_calmo():
    print("🛡️ Iniciando Scanner com Filtro Anti-Spam...")
    
    while True:
        try:
            # Pegando apenas os mais recentes com perfil completo
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                for item in data:
                    if item.get('chainId') == 'solana':
                        addr = item.get('tokenAddress')
                        
                        # TRAVA 1: Se já vimos esse token nas últimas 24h, ignora totalmente
                        if addr in tokens_vistos:
                            continue
                        
                        # TRAVA 2: Ignorar o contrato de teste que estava em loop
                        if "0x873301F" in addr:
                            continue

                        # Se chegou aqui, é um token realmente novo para o bot
                        link_gmgn = f"https://gmgn.ai/sol/token/{addr}"
                        
                        mensagem = (
                            f"🆕 **TOKEN ÚNICO DETECTADO**\n\n"
                            f"🪙 **CA:** `{addr}`\n\n"
                            f"🔍 [Analisar no GMGN]({link_gmgn})\n"
                            f"📊 [DexScreener]({item.get('url')})"
                        )
                        
                        bot.send_message(CHAT_ID, mensagem, parse_mode="Markdown")
                        
                        # Registra na memória com o tempo atual
                        tokens_vistos[addr] = time.time()
                        print(f"✅ Novo token registrado: {addr}")
                        
                        # Pequeno delay entre mensagens se houver vários novos ao mesmo tempo
                        time.sleep(3)

            # TRAVA 3: Limpeza da memória (remove tokens com mais de 24h para não pesar)
            agora = time.time()
            tokens_vistos_limpos = {k: v for k, v in tokens_vistos.items() if agora - v < 86400}
            tokens_vistos.clear()
            tokens_vistos.update(tokens_vistos_limpos)

            # Espera 45 segundos para a próxima busca (evita ban da API e Spam)
            time.sleep(45)
            
        except Exception as e:
            print(f"Erro no loop: {e}")
            time.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=scanner_calmo, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
