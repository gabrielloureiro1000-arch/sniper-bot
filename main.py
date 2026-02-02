import os
import time
import threading
import requests
import telebot
from flask import Flask

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
# O código vai ler sua chave do Koyeb automaticamente
PRIVATE_KEY = os.environ.get("SOLANA_PRIVATE_KEY") 

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# Memória para não repetir (set é mais rápido)
tokens_processados = set()

@app.route('/')
@app.route('/healthz')
def health():
    return "SNIPER_RUNNING", 200

def scanner_sniper():
    print("🎯 Sniper iniciado: Monitorando lançamentos filtrados...")
    
    while True:
        try:
            # API do DexScreener para novos perfis (Tokens que pagaram para aparecer)
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                tokens = response.json()
                
                for token in tokens:
                    if token.get('chainId') == 'solana':
                        address = token.get('tokenAddress')
                        
                        if address not in tokens_processados:
                            # Prepara os links de análise
                            link_gmgn = f"https://gmgn.ai/sol/token/{address}"
                            link_rugcheck = f"https://rugcheck.xyz/tokens/{address}"
                            
                            mensagem = (
                                f"🔥 **NOVO TOKEN DETECTADO**\n\n"
                                f"🪙 **CA:** `{address}`\n\n"
                                f"🛠️ **Ferramentas de Análise:**\n"
                                f"✅ [Analisar no GMGN]({link_gmgn})\n"
                                f"🛡️ [Checar Rug (Segurança)]({link_rugcheck})\n\n"
                                f"💰 *Configurado para compra de 0.1 SOL*"
                            )
                            
                            bot.send_message(CHAT_ID, mensagem, parse_mode="Markdown")
                            tokens_processados.add(address)
                            print(f"✅ Alerta enviado: {address}")
                            
                            # Limpeza de memória (mantém apenas os últimos 200)
                            if len(tokens_processados) > 200:
                                tokens_processados.clear()

            # Espera 10 segundos para a próxima varredura
            time.sleep(10)
            
        except Exception as e:
            print(f"Erro no Sniper: {e}")
            time.sleep(5)

if __name__ == "__main__":
    # Inicia o scanner Sniper
    threading.Thread(target=scanner_sniper, daemon=True).start()
    
    # Inicia o servidor Web
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
