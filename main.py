import time
import requests
import telebot
import base58
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ESSENCIAIS ===
TOKEN_TELEGRAM = "SEU_BOT_TOKEN"
CHAT_ID = "SEU_CHAT_ID"
# Chave privada da sua carteira Solana (Formato Base58/Phantom)
PRIVATE_KEY_B58 = "SUA_PRIVATE_KEY" 
# Use um RPC de qualidade (Ex: Helius, QuickNode ou o padrão abaixo)
RPC_URL = "https://api.mainnet-beta.solana.com"

# === PARÂMETROS DE TRADING ===
COMPRA_VALOR_SOL = 0.1  # Valor de cada entrada em SOL
TAKE_PROFIT_MULT = 2.0  # Vende em 2x (100% lucro)
STOP_LOSS_MULT = 0.5    # Vende se cair 50%

# Inicialização
bot = telebot.TeleBot(TOKEN_TELEGRAM)
solana_client = Client(RPC_URL)
payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
carteira_pubkey = str(payer.pubkey())

# Memória do Bot (Evita loops infinitos e gerencia saídas)
posicoes_abertas = {} # {token_address: {preco_entrada, quantidade}}
tokens_processados = set() # Evita comprar o mesmo token duas vezes no mesmo deploy

def get_quote_and_swap(input_mint, output_mint, amount_sol):
    """Integração real com a API da Jupiter para Swap Automático"""
    try:
        # 1. Converter SOL para Lamports (1 SOL = 10^9 Lamports)
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        # 2. Obter Rota (Quote)
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=1000"
        quote = requests.get(quote_url).json()
        
        # 3. Criar Transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": carteira_pubkey,
            "wrapAndUnwrapSol": True
        }
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        swap_transaction = tx_res['swapTransaction']
        
        # 4. Assinar e Enviar
        raw_transaction = VersionedTransaction.from_bytes(base58.b58decode(swap_transaction))
        signature = payer.sign_message(raw_transaction.message)
        signed_tx = VersionedTransaction.populate(raw_transaction.message, [signature])
        
        opts = {"skip_preflight": True, "max_retries": 3}
        result = solana_client.send_raw_transaction(bytes(signed_tx), opts=opts)
        return str(result.value)
    except Exception as e:
        print(f"Erro no Swap: {e}")
        return None

def monitorar_vendas():
    """Checa preços de tokens comprados e executa Take Profit ou Stop Loss"""
    for mint in list(posicoes_abertas.keys()):
        try:
            # Busca preço via DexScreener
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            res = requests.get(url).json()
            preco_atual = float(res['pairs'][0]['priceUsd'])
            
            entrada = posicoes_abertas[mint]['preco_entrada']
            performance = preco_atual / entrada
            
            if performance >= TAKE_PROFIT_MULT or performance <= STOP_LOSS_MULT:
                print(f"Alvo atingido para {mint}. Vendendo...")
                # Lógica de venda: Inverte Mints (Token -> SOL)
                sig = get_quote_and_swap(mint, "So11111111111111111111111111111111111111112", 0) # 0 para usar balanço total
                if sig:
                    bot.send_message(CHAT_ID, f"💰 **VENDA AUTOMÁTICA**\nLucro/Prejuízo: {performance:.2f}x\nTX: `{sig}`")
                    del posicoes_abertas[mint]
        except:
            continue

def hunter_loop():
    bot.send_message(CHAT_ID, "🤖 **BOT GMGN HUNTER V2 ATIVADO**\nMonitorando compras e vendas automáticas.")
    
    while True:
        try:
            # --- DETECÇÃO ---
            # Aqui você deve colocar a lógica que extrai o contrato do GMGN. 
            # Vou usar o contrato do seu log como exemplo de "novo token detectado"
            token_detectado = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df" 

            # --- COMPRA ---
            if token_detectado not in tokens_processados:
                print(f"Novo token detectado: {token_detectado}. Tentando compra...")
                
                # Executa Swap SOL -> TOKEN
                sig = get_quote_and_swap("So11111111111111111111111111111111111111112", token_detectado, COMPRA_VALOR_SOL)
                
                if sig:
                    # Registra preço de entrada para o monitoramento
                    res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_detectado}").json()
                    preco_in = float(res['pairs'][0]['priceUsd'])
                    
                    posicoes_abertas[token_detectado] = {'preco_entrada': preco_in}
                    tokens_processados.add(token_detectado)
                    
                    bot.send_message(CHAT_ID, f"✅ **COMPRA EXECUTADA**\nToken: `{token_detectado}`\nTX: `{sig}`")

            # --- MONITORAMENTO ---
            monitorar_vendas()
            
            time.sleep(10) # Pausa para evitar erros de conexão

        except Exception as e:
            print(f"Erro no Loop Principal: {e}")
            time.sleep(5)

if __name__ == "__main__":
    hunter_loop()
