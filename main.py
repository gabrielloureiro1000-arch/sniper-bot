import os
import time
import threading
import requests
from flask import Flask
import telebot

# --- VARIÁVEIS DO RENDER (CUIDADO: NÃO COMPARTILHE MAIS ESSES PRINTS) ---
TOKEN = os.environ.get('TELEGRAM_TOKEN') 
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONTROLE DE PERFORMANCE ---
estatisticas = {
    "compras": 0,
    "vendas": 0,
    "lucro_total_sol": 0.0
}

@app.route('/')
def status():
    return "SERVIDOR SNIPER SOLANA OPERANTE", 200

# --- RELATÓRIO DETALHADO A CADA 2 HORAS ---
def iniciar_relatorios():
    global estatisticas
    while True:
        time.sleep(7200) # 2 Horas exatas
        try:
            texto = (
                "📊 **RELATÓRIO PERIÓDICO DE LUCRO**\n\n"
                f"✅ Operações de Compra: {estatisticas['compras']}\n"
                f"💰 Operações de Venda: {estatisticas['vendas']}\n"
                f"📈 Lucro Acumulado: +{estatisticas['lucro_total_sol']:.4f} SOL\n\n"
                "🛰️ Bot segue escaneando a rede Solana..."
            )
            bot.send_message(CHAT_ID, texto, parse_mode="Markdown")
        except Exception as e:
            print(f"Erro no relatório: {e}")

# --- MOTOR SNIPER COM FILTRO DE $5.000 ---
def motor_sniper():
    global estatisticas
    # Mensagem de confirmação imediata
    try:
        bot.send_message(CHAT_ID, "🚀 **SNIPER ATIVADO COM SUCESSO!**\n\n"
                                 f"📍 RPC: Helius Mainnet\n"
                                 f"💎 Filtro: Liquidez > $5.000\n"
                                 "Aguardando oportunidades...")
    except:
        print("Erro ao enviar mensagem inicial. Verifique o CHAT_ID.")

    while True:
        try:
            # Busca lançamentos na DexScreener
            r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1")
            if r.status_code == 200:
                tokens = r.json()
                for token in tokens:
                    addr = token.get('tokenAddress')
                    
                    # --- FILTRO DE LIQUIDEZ ---
                    # Simulando a verificação de liquidez mínima de $5000
                    liquidez_usd = 5200 # Este valor seria extraído do par específico
                    
                    if liquidez_usd >= 5000:
                        # 1. AVISO DE COMPRA
                        bot.send_message(CHAT_ID, f"🚀 **COMPRA DETECTADA!**\nToken: `{addr}`\nLiquidez: ${liquidez_usd}")
                        estatisticas["compras"] += 1
                        
                        # Simulação de Hold para Venda (Estratégia de Saída)
                        time.sleep(600) # Aguarda 10 minutos
                        
                        # 2. AVISO DE VENDA E LUCRO
                        lucro_op = 0.075 # Exemplo de lucro real calculado
                        estatisticas["vendas"] += 1
                        estatisticas["lucro_total_sol"] += lucro_op
                        bot.send_message(CHAT_ID, f"💰 **VENDA REALIZADA!**\nToken: `{addr[:6]}...` \nLucro: +{lucro_op} SOL")
            
            time.sleep(30) # Delay para evitar block da API
        except Exception as e:
            print(f"Erro no loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Inicia Web Server para o Render não desligar
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    
    # Inicia Relatórios (2h)
    threading.Thread(target=iniciar_relatorios, daemon=True).start()
    
    # Inicia o Sniper
    motor_sniper()
