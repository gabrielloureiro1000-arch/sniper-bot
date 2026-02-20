import os
import time
import threading
import requests
import base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)

# --- PARÂMETROS ESTRATÉGICOS ---
ESTRATEGIA = {
    "valor_entrada_sol": 0.01,
    "take_profit": 1.50,      # Vende com 50% de lucro
    "stop_loss": 0.85,        # Vende se cair 15%
    "trailing_stop": True,    # Sobe o stop conforme o lucro aumenta
    "min_liquidez_usd": 8000,
    "min_volume_1h": 15000,
    "max_tokens_simultaneos": 1
}

# --- CONTROLE DE SESSÃO E RELATÓRIO ---
stats = {"compras": 0, "vendas": 0, "lucro_total": 0.0, "erros": 0}
start_time = time.time()
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "BOT SNIPER PRO ATIVO", 200

# --- FUNÇÕES CORE ---

def enviar_alerta(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(f"Erro Telegram: {msg}")

def gerar_relatorio():
    while True:
        time.sleep(7200) # 2 horas
        tempo_rodando = round((time.time() - start_time) / 3600, 2)
        relatorio = (
            f"📊 **RELATÓRIO DE PERFORMANCE (2H)**\n\n"
            f"⏳ Tempo Online: {tempo_rodando}h\n"
            f"🛒 Compras: {stats['compras']}\n"
            f"💰 Vendas: {stats['vendas']}\n"
            f"📈 Lucro Estimado: {stats['lucro_total']:.4f} SOL\n"
            f"⚠️ Erros reportados: {stats['erros']}"
        )
        enviar_alerta(relatorio)

def obter_quote_jupiter(input_mint, output_mint, amount_sol):
    url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_sol * 1e9)}&slippageBps=1500"
    try:
        res = session.get(url, timeout=10)
        return res.json()
    except Exception as e:
        stats["erros"] += 1
        return None

def executar_swap(quote_response):
    try:
        swap_data = {
            "quoteResponse": quote_response,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 2500000 # Taxa agressiva para não falhar
        }
        res = session.post("https://quote-api.jup.ag/v6/swap", json=swap_data, timeout=15).json()
        
        raw_tx = base64.b64decode(res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        signature = solana_client.send_raw_transaction(bytes(tx))
        return True, signature.value
    except Exception as e:
        enviar_alerta(f"❌ **ERRO NA TRANSAÇÃO:** {str(e)[:100]}")
        stats["erros"] += 1
        return False, None

def monitorar_venda(token_address, symbol, preco_entrada):
    """ Gerencia o melhor momento de saída (TP/SL) """
    max_preco_atingido = preco_entrada
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    while True:
        time.sleep(15)
        quote = obter_quote_jupiter(token_address, SOL_MINT, ESTRATEGIA["valor_entrada_sol"])
        
        if not quote or "outAmount" not in quote: continue
        
        preco_atual = int(quote["outAmount"]) / 1e9
        lucro_atual = preco_atual / ESTRATEGIA["valor_entrada_sol"]

        # Trailing Stop Loss
        if lucro_atual > max_preco_atingido:
            max_preco_atingido = lucro_atual

        # Lógica de Saída Inteligente
        deve_vender = False
        motivo = ""

        if lucro_atual >= ESTRATEGIA["take_profit"]:
            deve_vender, motivo = True, "🚀 TAKE PROFIT ALCANÇADO"
        elif lucro_atual <= ESTRATEGIA["stop_loss"]:
            deve_vender, motivo = True, "📉 STOP LOSS ATINGIDO"
        elif ESTRATEGIA["trailing_stop"] and lucro_atual < (max_preco_atingido * 0.90) and lucro_atual > 1.1:
            deve_vender, motivo = True, "🔄 TRAILING STOP (Proteção de Lucro)"

        if deve_vender:
            sucesso, tx = executar_swap(quote)
            if sucesso:
                stats["vendas"] += 1
                stats["lucro_total"] += (preco_atual - ESTRATEGIA["valor_entrada_sol"])
                enviar_alerta(f"💰 **VENDA EXECUTADA!**\nToken: {symbol}\nMotivo: {motivo}\nLucro: {((lucro_atual-1)*100):.2f}%")
                break

def sniper_pro():
    enviar_alerta("🚀 **BOT SNIPER PRO ONLINE**\nModo: Compra Real + Filtros Anti-Rug")
    SOL_MINT = "So11111111111111111111111111111111111111112"

    while True:
        try:
            # Busca tokens em tendência com filtros de volume
            url_dex = "https://api.dexscreener.com/latest/dex/search?q=SOL"
            r = session.get(url_dex, timeout=10).json()
            pairs = r.get('pairs', [])

            for pair in pairs:
                liq = pair.get('liquidity', {}).get('usd', 0)
                vol = pair.get('volume', {}).get('h1', 0)
                addr = pair.get('baseToken', {}).get('address')
                symbol = pair.get('baseToken', {}).get('symbol')
                
                # FILTROS DE ENTRADA OUSADA POREM SEGURA
                if pair.get('chainId') == 'solana' and liq > ESTRATEGIA["min_liquidez_usd"] and vol > ESTRATEGIA["min_volume_1h"]:
                    
                    # Evita comprar o que já subiu demais (evita topo)
                    change_1h = float(pair.get('priceChange', {}).get('h1', 0))
                    if change_1h > 150: continue # Ignora se subiu mais de 150% em 1h

                    enviar_alerta(f"🎯 **ALVO DETECTADO!**\nToken: {symbol}\nLiq: ${liq}\nVol 1h: ${vol}\nAnalisando entrada...")
                    
                    quote = obter_quote_jupiter(SOL_MINT, addr, ESTRATEGIA["valor_entrada_sol"])
                    if quote:
                        sucesso, tx = executar_swap(quote)
                        if sucesso:
                            stats["compras"] += 1
                            enviar_alerta(f"✅ **COMPRA REALIZADA!**\nToken: {symbol}\nTX: `https://solscan.io/tx/{tx}`\nMonitorando saída...")
                            monitorar_venda(addr, symbol, ESTRATEGIA["valor_entrada_sol"])
                            break 
            
            time.sleep(30)
        except Exception as e:
            print(f"Erro Loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=gerar_relatorio).start()
    sniper_pro()
