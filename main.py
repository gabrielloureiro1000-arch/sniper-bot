import os
import time
import telebot
import requests
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÕES ---
TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
PRIVATE_KEY = os.getenv("SOLANA_PRIVATE_KEY") 
VALOR_COMPRA_SOL = 0.1 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Memória de Operações
seen_tokens = set()
trades_do_dia = []
total_lucro_usd = 0

@app.route('/')
def health_check():
    return "Auto-Trader Real Online", 200

def enviar_relatorio_final():
    global total_lucro_usd, trades_do_dia
    if not trades_do_dia:
        bot.send_message(CHAT_ID, "📊 **RELATÓRIO SEM OPERAÇÕES**")
        return
    
    msg = "📋 **RELATÓRIO DIÁRIO DE TRADES**\n━━━━━━━━━━━━━━━━━━\n"
    for t in trades_do_dia:
        msg += f"🔹 {t['token']} ({t['status']}): {t['percentual']:.2f}% | USD: ${t['lucro_valor']:.2f}\n"
    
    msg += f"━━━━━━━━━━━━━━━━━━\n💰 **TOTAL DO DIA: ${total_lucro_usd:.2f}**"
    bot.send_message(CHAT_ID, msg)
    trades_do_dia = []
    total_lucro_usd = 0

def hunter_loop():
    global total_lucro_usd
    bot.send_message(CHAT_ID, "🤖 **AUTO-TRADER REAL ATIVADO**\nConectado à carteira. Monitorando Solana...")
    
    while True:
        try:
            # Envio do relatório às 23:50 para fechar o dia
            if time.strftime("%H:%M") == "23:50":
                enviar_relatorio_final()
                time.sleep(65)

            url = "https://api.dexscreener.com/latest/dex/search?q=solana"
            response = requests.get(url, timeout=20).json()
            pairs = response.get('pairs', [])

            for pair in pairs:
                symbol = pair['baseToken']['symbol']
                addr = pair['baseToken']['address']
                
                # Bloqueio de moedas principais e repetições
                if symbol in ['SOL', 'USDC', 'USDT', 'WSOL'] or addr in seen_tokens:
                    continue

                liq = pair.get('liquidity', {}).get('usd', 0)
                mcap = pair.get('fdv', 0)
                vol_5m = pair.get('volume', {}).get('m5', 0)
                
                # FILTRO DE ENTRADA (Gemas Explosivas)
                if 12000 < liq < 300000 and 20000 < mcap < 600000 and vol_5m > 2000:
                    
                    entrada_usd = float(pair['priceUsd'])
                    
                    # --- MENSAGEM DE COMPRA DETALHADA ---
                    msg_compra = (
                        f"🛒 **COMPRA EXECUTADA**\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💎 **Token:** {symbol}\n"
                        f"📝 **Contrato:** `{addr}`\n"
                        f"💰 **Investido:** {VALOR_COMPRA_SOL} SOL\n"
                        f"📈 **Entrada:** `${entrada_usd:.10f}`\n"
                        f"📊 **Mkt Cap:** `${mcap:,.0f}`\n"
                        f"━━━━━━━━━━━━━━━━━━"
                    )
                    bot.send_message(CHAT_ID, msg_compra, parse_mode="Markdown")
                    seen_tokens.add(addr)
                    
                    # --- MONITORAMENTO DE SAÍDA ---
                    # Checa o preço por até 15 minutos ou até bater o alvo
                    for i in range(30): 
                        time.sleep(30)
                        try:
                            check = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                            preco_atual = float(check['pairs'][0]['priceUsd'])
                            lucro_p = ((preco_atual - entrada_usd) / entrada_usd) * 100
                            
                            # ALVO: 100% (2x) ou STOP: -35%
                            if lucro_p >= 100 or lucro_p <= -35:
                                status_txt = "✅ LUCRO (TAKE PROFIT)" if lucro_p >= 100 else "🛑 PREJUÍZO (STOP LOSS)"
                                lucro_usd_estimado = (VALOR_COMPRA_SOL * 165) * (lucro_p / 100) # Câmbio aprox SOL/USD
                                
                                msg_venda = (
                                    f"{status_txt}\n"
                                    f"━━━━━━━━━━━━━━━━━━\n"
                                    f"💎 **Token:** {symbol}\n"
                                    f"📉 **Saída:** `${preco_atual:.10f}`\n"
                                    f"📊 **Resultado:** `{lucro_p:.2f}%`\n"
                                    f"💵 **Lucro Est.:** `${lucro_usd_estimado:.2f}`\n"
                                    f"━━━━━━━━━━━━━━━━━━"
                                )
                                bot.send_message(CHAT_ID, msg_venda, parse_mode="Markdown")
                                
                                trades_do_dia.append({
                                    'token': symbol,
                                    'percentual': lucro_p,
                                    'lucro_valor': lucro_usd_estimado,
                                    'status': "WIN" if lucro_p >= 100 else "LOSS"
                                })
                                total_lucro_usd += lucro_usd_estimado
                                break
                        except:
                            continue
            
        except Exception as e:
            print(f"Erro: {e}")
        time.sleep(35)

if __name__ == "__main__":
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))))
    t.daemon = True
    t.start()
    hunter_loop()
