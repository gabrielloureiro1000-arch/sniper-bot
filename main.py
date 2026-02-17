import os
import time
import threading
import requests
import base58
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# --- CONFIGURAÇÕES ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID')
PRIVATE_KEY_STR = os.getenv('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)

# Configurações de Trade
COMPRA_VALOR_SOL = 0.05
TAKE_PROFIT = 1.5  # Vende com 50% de lucro
STOP_LOSS = 0.8    # Vende se cair 20%

# Banco de dados temporário
historico_trades = []
posicoes_ativas = {} # {addr: {'amount': x, 'price_buy': y}}

try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    pubkey = str(keypair.pubkey())
except Exception as e:
    print(f"Erro Chave: {e}")

# --- FILTROS GMGN-STYLE ---

def filtro_agressivo(token_addr):
    """Filtro focado em não perder oportunidades, mas evitando rug óbvio"""
    try:
        # Consulta rápida via RugCheck ou DexScreener
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
        pair = res.get('pairs', [{}])[0]
        
        liquidez = pair.get('liquidity', {}).get('usd', 0)
        volume_m5 = pair.get('volume', {}).get('m5', 0)
        
        # Filtro: Liquidez mínima de $5k e algum volume de negociação nascente
        if liquidez > 5000 and volume_m5 > 1000:
            return True
        return False
    except:
        return False

# --- LÓGICA DE COMPRA E VENDA ---

def executar_venda(token_mint, amount):
    """Executa a venda via Jupiter API"""
    sol_mint = "So11111111111111111111111111111111111111112"
    tx = executar_swap(token_mint, sol_mint, amount, is_sell=True)
    if tx:
        bot.send_message(MY_CHAT_ID, f"💰 **VENDA REALIZADA!**\nToken: `{token_mint}`\n[Tx](https://solscan.io/tx/{tx})", parse_mode="Markdown")
        return True
    return False

def monitor_precos():
    """Roda em paralelo checando se é hora de vender"""
    while True:
        for addr, dados in list(posicoes_ativas.items()):
            try:
                # Pega preço atual
                res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                price_now = float(res['pairs'][0]['priceUsd'])
                
                # Checa lucro/prejuízo
                target_win = dados['price_buy'] * TAKE_PROFIT
                target_loss = dados['price_buy'] * STOP_LOSS
                
                if price_now >= target_win or price_now <= target_loss:
                    if executar_venda(addr, dados['amount']):
                        historico_trades.append({'addr': addr, 'status': 'Vendido', 'lucro': price_now/dados['price_buy']})
                        del posicoes_ativas[addr]
            except: continue
        time.sleep(10)

# --- SNIPER GMGN ---

def sniper_loop():
    print("🎯 Sniper GMGN Mode ON...")
    sol_mint = "So11111111111111111111111111111111111111112"
    while True:
        try:
            # Pega os tokens mais recentes que ganharam perfil (indicador de hype)
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for t in resp:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_ativas:
                    if filtro_agressivo(addr):
                        tx = executar_swap(sol_mint, addr, COMPRA_VALOR_SOL)
                        if tx:
                            # Registra compra
                            res_p = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                            price = float(res_p['pairs'][0]['priceUsd'])
                            posicoes_ativas[addr] = {'amount': 'all', 'price_buy': price}
                            
                            bot.send_message(MY_CHAT_ID, f"🚀 **COMPRA EXECUTADA!**\nToken: `{addr}`\nValor: {COMPRA_VALOR_SOL} SOL\n[Tx](https://solscan.io/tx/{tx})", parse_mode="Markdown")
            time.sleep(20)
        except:
            time.sleep(10)

# --- RELATÓRIO 2H ---

def relatorio_periodico():
    while True:
        time.sleep(7200) # 2 horas
        msg = "📊 **RELATÓRIO DE DESEMPENHO (2H)**\n\n"
        if not historico_trades:
            msg += "Nenhuma operação encerrada no período."
        for trade in historico_trades[-10:]: # últimos 10
            msg += f"Token: `{trade['addr'][:6]}...` | Lucro: {(trade['lucro']-1)*100:.2f}%\n"
        
        msg += f"\n🔥 Posições abertas: {len(posicoes_ativas)}"
        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

# --- FLASK E INICIALIZAÇÃO ---

@app.route('/')
def health(): return "ACTIVE", 200

if __name__ == "__main__":
    threading.Thread(target=sniper_loop, daemon=True).start()
    threading.Thread(target=monitor_precos, daemon=True).start()
    threading.Thread(target=relatorio_periodico, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
