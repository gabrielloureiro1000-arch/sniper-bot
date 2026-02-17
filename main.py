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

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID') 
PRIVATE_KEY_STR = os.getenv('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)

# Configurações de Trade
COMPRA_VALOR_SOL = 0.05
TAKE_PROFIT = 1.50  # 50% de lucro
STOP_LOSS = 0.80    # 20% de prejuízo
SOL_MINT = "So11111111111111111111111111111111111111112"

# Memória do Bot
historico_trades = []
posicoes_ativas = {} # {token_addr: {'amount': x, 'price_buy': y}}

try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    pubkey = str(keypair.pubkey())
    print(f"✅ Carteira carregada: {pubkey}")
except Exception as e:
    print(f"❌ Erro na Private Key: {e}")

# --- MOTOR DE EXECUÇÃO (JUPITER V6) ---

def executar_swap(mint_entrada, mint_saida, amount_sol, is_sell=False):
    try:
        # Converter SOL para Lamports
        amount = int(amount_sol * 10**9)
        
        # 1. Pegar Cotação (Slippage de 10% para garantir execução em hype)
        quote_res = requests.get(
            f"https://quote-api.jup.ag/v6/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount}&slippageBps=1000",
            timeout=10
        ).json()

        if 'error' in quote_res: return None

        # 2. Gerar Transação
        payload = {
            "quoteResponse": quote_res,
            "userPublicKey": pubkey,
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 1000000 # Taxa de prioridade (0.001 SOL)
        }
        tx_data = requests.post("https://quote-api.jup.ag/v6/swap", json=payload, timeout=10).json()
        
        # 3. Assinar e Enviar
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_data['swapTransaction']))
        signature = keypair.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        result = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(result.value)
    except Exception as e:
        print(f"❌ Erro Swap: {e}")
        return None

# --- FILTROS E MONITORAMENTO ---

def filtro_gmgn(token_addr):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
        pair = res.get('pairs', [{}])[0]
        
        liquidez = pair.get('liquidity', {}).get('usd', 0)
        vol_m5 = pair.get('volume', {}).get('m5', 0)
        
        # Filtro: Liquidez > $5k e Volume nos últimos 5 min > $1k
        if liquidez > 5000 and vol_m5 > 1000:
            return True, float(pair.get('priceUsd', 0))
        return False, 0
    except:
        return False, 0

def monitor_venda():
    while True:
        for addr, dados in list(posicoes_ativas.items()):
            try:
                res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                price_now = float(res['pairs'][0]['priceUsd'])
                
                if price_now >= (dados['price_buy'] * TAKE_PROFIT) or price_now <= (dados['price_buy'] * STOP_LOSS):
                    tx = executar_swap(addr, SOL_MINT, COMPRA_VALOR_SOL, is_sell=True)
                    if tx:
                        lucro_final = (price_now / dados['price_buy']) - 1
                        bot.send_message(MY_CHAT_ID, f"💰 **VENDA!**\nLucro: {lucro_final*100:.2f}%\n[Tx](https://solscan.io/tx/{tx})", parse_mode="Markdown")
                        historico_trades.append({'addr': addr, 'pnl': lucro_final})
                        del posicoes_ativas[addr]
            except: continue
        time.sleep(15)

def sniper_loop():
    print("🎯 Sniper Iniciado...")
    while True:
        try:
            # Monitora novos perfis de tokens (Hype inicial)
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for t in resp:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_ativas:
                    passou, preco_compra = filtro_gmgn(addr)
                    if passou:
                        tx = executar_swap(SOL_MINT, addr, COMPRA_VALOR_SOL)
                        if tx:
                            posicoes_ativas[addr] = {'price_buy': preco_compra}
                            bot.send_message(MY_CHAT_ID, f"🚀 **COMPRA!**\nToken: `{addr}`\n[Tx](https://solscan.io/tx/{tx})", parse_mode="Markdown")
            time.sleep(20)
        except: time.sleep(10)

# --- RELATÓRIOS E COMANDOS ---

@bot.message_handler(commands=['relatorio', 'status'])
def report_command(message):
    msg = f"📊 **Status Atual**\nPosições abertas: {len(posicoes_ativas)}\nTrades hoje: {len(historico_trades)}"
    bot.reply_to(message, msg, parse_mode="Markdown")

def loop_relatorio_2h():
    while True:
        time.sleep(7200)
        pnl_total = sum(t['pnl'] for t in historico_trades)
        msg = f"📈 **Relatório 2h**\nTotal Trades: {len(historico_trades)}\nPnL Acumulado: {pnl_total*100:.2f}%"
        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

def iniciar_telegram():
    bot.remove_webhook()
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    time.sleep(2)
    while True:
        try:
            bot.polling(none_stop=True, interval=2)
        except: time.sleep(10)

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    threading.Thread(target=sniper_loop, daemon=True).start()
    threading.Thread(target=monitor_venda, daemon=True).start()
    threading.Thread(target=loop_relatorio_2h, daemon=True).start()
    threading.Thread(target=iniciar_telegram, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
