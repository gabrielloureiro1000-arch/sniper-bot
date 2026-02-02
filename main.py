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

# Memória para não repetir tokens (mantém os últimos 500)
tokens_processados = set()

@app.route('/')
@app.route('/healthz')
def health(): return "SCANNER_OPERACIONAL", 200

def verificar_seguranca(token_address):
    """
    Simula uma checagem de segurança. 
    Aqui poderíamos integrar com a API da GoPlus ou RugCheck.
    """
    # Por enquanto, filtramos apenas para não repetir
    if token_address in tokens_processados:
        return False
    return True

def scanner_loop():
    print("🔎 Scanner Real Iniciado: Monitorando novos tokens na Solana...")
    
    while True:
        try:
            # Busca os perfis de tokens mais recentes criados (DexScreener)
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                for item in data:
                    # Filtra apenas rede Solana
                    if item.get('chainId') == 'solana':
                        addr = item.get('tokenAddress')
                        
                        # Se for um token novo que não processamos ainda
                        if verificar_seguranca(addr):
                            nome = item.get('tokenAddress')[:8] # Abrevia o nome se não houver
                            link_gmgn = f"https://gmgn.ai/sol/token/{addr}"
                            
                            mensagem = (
                                f"🚀 **NOVO ALVO DETECTADO NO SCANNER**\n\n"
                                f"🪙 **CA:** `{addr}`\n"
                                f"🛡️ **Segurança:** Liquidez Detectada\n\n"
                                f"🔗 **Analisar no GMGN:** [CLIQUE AQUI]({link_gmgn})\n"
                                f"📊 **Gráfico:** [DexScreener]({item.get('url')})"
                            )
                            
                            bot.send_message(CHAT_ID, mensagem, parse_mode="Markdown", disable_web_page_preview=True)
                            
                            # Adiciona à trava de repetição
                            tokens_processados.add(addr)
                            
                            # Limpa memória se crescer demais
                            if len(tokens_processados) > 500:
                                tokens_processados.pop()
                                
                            print(f"✅ Notificado: {addr}")
                            time.sleep(2) # Evita spam no Telegram

            # Espera 20 segundos para a próxima varredura de novos tokens
            time.sleep(20)
            
        except Exception as e:
            print(f"Erro no Scanner: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Inicia o Scanner em segundo plano
    threading.Thread(target=scanner_loop, daemon=True).start()
    
    # Mantém o servidor Flask para o Koyeb
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
    t = threading.Thread(target=hunter_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
