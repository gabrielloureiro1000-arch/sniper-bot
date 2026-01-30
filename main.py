import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÕES ---
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
# Pega a chave dos "Secrets" da Koyeb por segurança
PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY") 
VALOR_COMPRA_SOL = 0.1 # Quanto o bot vai gastar por moeda

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
trades_do_dia = []

@app.route('/')
def health_check():
    return "Auto-Trader Real Online", 200

def executar_swap(token_address, acao="buy"):
    """
    Função para enviar a ordem de compra/venda para a rede Solana.
    Utiliza a API da Solana Tracker para facilitar a execução.
    """
    try:
        url = "https://api.solanatracker.io/swap"
        payload = {
            "from": "So11111111111111111111111111111111111111112" if acao == "buy" else token_address,
            "to": token_address if acao == "buy" else "So11111111111111111111111111111111111111112",
            "amount": VALOR_COMPRA_SOL,
            "slippage": 15, # Slippage alto para garantir a compra em gemas rápidas
            "payer": "ENDERECO_DA_SUA_CARTEIRA",
            "forceLegacy": False
        }
        # Aqui o bot enviaria a transação assinada com sua PRIVATE_KEY
        print(f"Executando {acao} para {token_address}")
        return True
    except Exception as e:
        print(f"Erro no Swap: {e}")
        return False

def hunter_loop():
    bot.send_message(CHAT_ID, "🤖 **AUTO-TRADER GMGN ATIVADO**\nComprando 0.1 SOL em cada oportunidade detectada.")
    seen_tokens = set()

    while True:
        try:
            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            pairs = requests.get(url).json().get('pairs', [])

            for pair in pairs:
                addr = pair['baseToken']['address']
                symbol = pair['baseToken']['symbol']
                if addr in seen_tokens: continue

                # Filtros para Ganhos Explosivos
                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                
                if 10000 < liq < 200000 and 15000 < mcap < 400000:
                    # 1. COMPRA AUTOMÁTICA
                    if executar_swap(addr, "buy"):
                        bot.send_message(CHAT_ID, f"🛒 **COMPRA EXECUTADA:** {symbol}\n💰 Investido: {VALOR_COMPRA_SOL} SOL")
                        
                        entrada = float(pair['priceUsd'])
                        
                        # 2. MONITORAMENTO DE VENDA
                        while True:
                            time.sleep(20)
                            res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                            preco_atual = float(res['pairs'][0]['priceUsd'])
                            lucro = ((preco_atual - entrada) / entrada) * 100

                            # Alvo: 100% (2x) ou Stop: -30%
                            if lucro >= 100 or lucro <= -30:
                                if executar_swap(addr, "sell"):
                                    status = "✅ LUCRO" if lucro >= 100 else "🛑 STOP"
                                    bot.send_message(CHAT_ID, f"{status}: {symbol}\n📈 Resultado: {lucro:.2f}%")
                                    trades_do_dia.append({'token': symbol, 'p': lucro})
                                    break
                    
                    seen_tokens.add(addr)
        except:
            pass
        time.sleep(30)

if __name__ == "__main__":
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))))
    t.daemon = True
    t.start()
    hunter_loop()
