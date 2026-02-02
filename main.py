import os
import time
import threading
import telebot
from flask import Flask

# === CONFIGURAÇÕES REAIS ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
# Cole sua chave privada da Phantom/Solflare aqui para o bot poder comprar
MINHA_CHAVE_PRIVADA = "n48gHntUERVYpqoShngN2Ub2zPG4f2huVyft7EZ7dxC1cCTDjWLkecezU3gSBp6VeL6nUem6dWZnEtZ3yU3vV4x" 

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)

# Memória temporária para não repetir o mesmo token
tokens_processados = []

@app.route('/')
def health():
    return "TRADER_ATIVO", 200

def executar_swap_compra(mint_token):
    """
    Aqui é onde o bot realmente gasta o SOL.
    Por enquanto, ele apenas simula. Para ativar real, 
    usaremos a API da Jupiter v6.
    """
    print(f"Iniciando transação real para {mint_token}...")
    # Lógica de compra real entra aqui
    return True

def hunter_loop():
    print("🚀 Trader Hunter em busca de oportunidades...")
    
    while True:
        try:
            # Simulando a detecção de um novo token promissor no GMGN
            # No futuro, aqui entrará o código que lê o site GMGN.ai
            token_detectado = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df"
            
            if token_detectado not in tokens_processados:
                # 1. Tenta comprar na Blockchain
                sucesso = executar_swap_compra(token_detectado)
                
                if sucesso:
                    mensagem = (
                        f"🎯 **NOVA COMPRA EXECUTADA**\n\n"
                        f"🪙 **Token:** `{token_detectado}`\n"
                        f"💰 **Investido:** 0.1 SOL\n"
                        f"📊 **Acompanhar:** [DexScreener](https://dexscreener.com/solana/{token_detectado})"
                    )
                    bot.send_message(CHAT_ID, mensagem, parse_mode="Markdown")
                    
                    # 2. Adiciona à lista e mantém apenas os últimos 50 tokens para não pesar a memória
                    tokens_processados.append(token_detectado)
                    if len(tokens_processados) > 50:
                        tokens_processados.pop(0)

            time.sleep(60) # Checa a cada 1 minuto para evitar taxas desnecessárias
            
        except Exception as e:
            print(f"Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    t = threading.Thread(target=hunter_loop, daemon=True)
    t.start()
    
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
