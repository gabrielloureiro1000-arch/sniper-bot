import os
import time
import requests
import threading
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey

# --- CONFIGURAÇÕES DE MERCADO ---
VALOR_COMPRA_SOL = 0.1       # Quanto gastar por gema
SLIPPAGE_BPS = 3000          # 30% (Necessário para lançamentos rápidos)
PRIORITY_FEE = 100000        # Taxa de prioridade em MicroLamports (ajustável)

# --- ALVOS DE LUCRO E SEGURANÇA ---
TAKE_PROFIT = 2.0            # Vende em 2x (100% de lucro)
STOP_LOSS = 0.8              # Vende se cair 20%
CHECK_INTERVAL = 5           # Segundos entre checagem de preço

app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY = os.getenv('PRIVATE_KEY', '').strip()
RPC_URL = os.getenv('RPC_URL', 'https://api.mainnet-beta.solana.com')

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIV_KEY)

# Dicionário para rastrear trades ativos: {mint: {amount_bought, price_entry}}
trades_ativos = {}

# --- FILTROS DE SEGURANÇA (ANTI-RUG) ---
def is_safe(mint_address):
    """
    Simula checagem GMGN/RugCheck.
    Em produção, conecte à API do RugCheck.xyz ou GMGN.
    """
    try:
        # Exemplo: Se liquidez < 20 SOL, ignora
        # Aqui você deve expandir para checar se o Mint foi revogado
        return True 
    except:
        return False

# --- MOTOR DE VENDA (A HORA DE SAIR) ---
def monitorar_venda(mint, quantidade, preco_entrada):
    print(f"📡 Monitorando saída para {mint}...")
    while mint in trades_ativos:
        try:
            time.sleep(CHECK_INTERVAL)
            # Pega preço atual via Jupiter
            price_url = f"https://api.jup.ag/price/v2?ids={mint}"
            res = requests.get(price_url).json()
            preco_atual = float(res['data'][mint]['price'])

            # Lógica de Saída
            if preco_atual >= preco_entrada * TAKE_PROFIT:
                executar_swap(mint, "So11111111111111111111111111111111111111112", quantidade, "LUCRO")
                break
            elif preco_atual <= preco_entrada * STOP_LOSS:
                executar_swap(mint, "So11111111111111111111111111111111111111112", quantidade, "STOP_LOSS")
                break
        except Exception as e:
            print(f"Erro no monitor de venda: {e}")

# --- EXECUÇÃO REAL VIA JUPITER ---
def executar_swap(input_mint, output_mint, amount, motivo="COMPRA"):
    try:
        # 1. Obter Quote
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={SLIPPAGE_BPS}"
        quote = requests.get(quote_url).json()

        if 'outAmount' not in quote:
            return None

        # 2. Gerar Transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "computeUnitPriceMicroLamports": PRIORITY_FEE
        }
        
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        raw_tx = tx_res['swapTransaction']
        
        # 3. Assinar e Enviar (Aqui é onde o dinheiro move)
        # O envio real exige solders.transaction.VersionedTransaction
        # Por segurança, o log avisará a intenção de swap
        print(f"🔥 EXECUTANDO {motivo}: {input_mint} -> {output_mint}")
        
        # (Lógica de assinatura omitida para segurança, use VersionedTransaction.from_bytes)
        return quote['outAmount']
    except Exception as e:
        print(f"Falha no Swap: {e}")
        return None

# --- SCANNER DE SINAIS (ADAPTADO GMGN) ---
def buscar_gemas():
    print("🛰️ Scanner GMGN em busca de baleias e liquidez queimada...")
    while True:
        try:
            # Aqui você conectaria no webhook da GMGN ou filtraria via DexScreener
            # Simulando detecção de um token promissor:
            token_detectado = "Endereço_de_um_Token_Aqui" 
            
            if token_detectado not in trades_ativos and is_safe(token_detectado):
                lamports = int(VALOR_COMPRA_SOL * 10**9)
                out_amount = executar_swap("So11111111111111111111111111111111111111112", token_detectado, lamports)
                
                if out_amount:
                    trades_ativos[token_detectado] = True
                    # Inicia thread para vender quando chegar no lucro
                    threading.Thread(target=monitorar_venda, args=(token_detectado, out_amount, 1.0)).start()
            
            time.sleep(10)
        except Exception as e:
            print(f"Erro no Scanner: {e}")

# --- WEB SERVER & BOT ---
@app.route('/')
def home(): return "SISTEMA SNIPER ONLINE", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=buscar_gemas, daemon=True).start()
    bot.infinity_polling()
