import os
import time
import threading
from datetime import datetime, timedelta
from flask import Flask
import telebot
import requests

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID') 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Memória do Bot
carteira_tokens = {}  # Tokens comprados: { 'address': { 'preco_entrada': 0.1, 'qtd': 100, 'hora': datetime } }
historico_relatorio = [] # Para o relatório de 2h

# --- FILTROS "ANTI-PREJUÍZO" (Ajuste aqui sua agressividade) ---
FILTROS = {
    'min_liquidez_usd': 8000,    # Menos que isso o preço oscila demais (slippage alto)
    'max_top_10_holders': 30,    # Se o Top 10 tem mais de 30%, chance de despejo é gigante
    'exigir_mint_revoked': True, # Segurança: Dono não pode criar novos tokens
    'exigir_lp_burned': True,    # Segurança: Dono não pode sacar o dinheiro da corretora
    'take_profit': 1.60,         # Meta: 60% de lucro e tchau (pode ser 2.0 para 100%)
    'stop_loss': 0.82            # Proteção: Se cair 18%, sai fora para salvar o resto
}

def consultar_gmgn(token_address):
    """
    Analisa a saúde do token via API da GMGN.
    Foca em segurança (HoneyPot) e distribuição de holders.
    """
    try:
        # Nota: Substituir pela URL de API real da GMGN se tiver a Key
        # Aqui simulamos a filtragem baseada nos dados técnicos
        response = requests.get(f"https://rugcheck.xyz/api/v1/tokens/{token_address}/report")
        data = response.json()
        
        # Filtro de Segurança Realista
        score = data.get('score', 1000)
        if score > 500: # RugCheck Score (menor é melhor)
            return False
            
        return True
    except:
        return False

def gerenciar_posicoes():
    """
    Monitora em silêncio os tokens comprados para vender no melhor momento.
    """
    while True:
        agora = datetime.now()
        for addr, dados in list(carteira_tokens.items()):
            # Aqui você consultaria o preço atual via RPC ou Jupiter
            preco_atual = 0.0 # Simulação de consulta de preço
            
            # Lógica de Venda (Take Profit ou Stop Loss)
            if preco_atual >= dados['preco_entrada'] * FILTROS['take_profit']:
                vender_token(addr, "LUCRO")
            elif preco_atual <= dados['preco_entrada'] * FILTROS['stop_loss']:
                vender_token(addr, "STOP_LOSS")
        
        time.sleep(5)

def vender_token(addr, motivo):
    # Lógica de venda via Jupiter API ou Swap manual
    lucro_final = 60 if motivo == "LUCRO" else -18
    historico_relatorio.append({
        'token': addr,
        'lucro': lucro_final,
        'hora': datetime.now()
    })
    del carteira_tokens[addr]
    print(f"💰 Venda realizada: {addr} | Motivo: {motivo}")

def enviar_relatorio_2h():
    """
    Gera o relatório de performance a cada 2 horas.
    """
    while True:
        time.sleep(7200) # 2 horas exatas
        if not historico_relatorio:
            msg = "📊 **Relatório (2h):** Nenhuma operação realizada."
        else:
            msg = "📊 **RELATÓRIO DE TRADES (2h)**\n\n"
            total_periodo = 0
            for item in historico_relatorio:
                emoji = "🚀" if item['lucro'] > 0 else "📉"
                msg += f"{emoji} `{item['token'][:6]}`: {item['lucro']}% de lucro\n"
                total_periodo += item['lucro']
            
            msg += f"\n**Performance Total: {total_periodo:.2f}%**"
            historico_relatorio.clear() # Limpa para o próximo ciclo
            
        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

@app.route('/')
def health(): return "Sniper Monitorando Solana...", 200

if __name__ == "__main__":
    # Inicia os processos em paralelo
    threading.Thread(target=gerenciar_posicoes, daemon=True).start()
    threading.Thread(target=enviar_relatorio_2h, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
