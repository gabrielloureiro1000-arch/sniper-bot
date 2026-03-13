import os
import time
import threading
import requests
import telebot
from flask import Flask

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEX_INTERVAL = 3  # Mais rápido para não perder o timing

# Filtros para Tokens Promissores (Agressivo)
MIN_LIQUIDITY = 1000
MIN_VOLUME_M5 = 2000
MIN_BUYS_M5 = 5

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen_tokens = set()
monitored_prices = {} # {addr: {"symbol": symbol, "price": price}}
alerts_count = 0

def send(msg):
    global alerts_count
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts_count += 1
    except Exception as e:
        print(f"Erro Telegram: {e}")

# --- RELATÓRIO DE PERFORMANCE A CADA 2 HORAS ---
def performance_report():
    while True:
        time.sleep(7200) # 2 Horas
        if not monitored_prices:
            continue

        report = "📊 *RELATÓRIO DE VALORIZAÇÃO (2H)*\n\n"
        
        # Consultar preços atuais para todos os monitorados
        addresses = ",".join(monitored_prices.keys())
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses}"
            r = requests.get(url, timeout=10)
            pairs = r.json().get("pairs", [])
            
            # Mapear preços atuais
            current_prices = {p.get("baseToken", {}).get("address"): float(p.get("priceUsd", 0)) for p in pairs}

            for addr, data in list(monitored_prices.items()):
                initial_p = data["price"]
                symbol = data["symbol"]
                current_p = current_prices.get(addr)

                if current_p:
                    change = ((current_p - initial_p) / initial_p) * 100
                    emoji = "🚀" if change >= 0 else "🔻"
                    report += f"{emoji} *{symbol}*: `{change:+.2f}%` desde o alerta\n"
            
            send(report)
        except Exception as e:
            print(f"Erro no Relatório: {e}")

# --- SCANNER EM TEMPO REAL ---
def scan():
    print("🔥 SCANNER AGRESSIVO INICIADO")
    while True:
        try:
            # Busca tokens da Solana com atividade recente
            url = "https://api.dexscreener.com/latest/dex/search?q=sol"
            r = requests.get(url, timeout=10)
            if r.status_code != 200: continue
            
            pairs = r.json().get("pairs", [])

            for pair in pairs:
                addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                
                if not addr or addr in seen_tokens: continue

                liq = pair.get("liquidity", {}).get("usd", 0)
                vol5m = pair.get("volume", {}).get("m5", 0)
                buys5m = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                price = float(pair.get("priceUsd", 0))

                # FILTROS DE ENTRADA (Promissores)
                if liq < MIN_LIQUIDITY or vol5m < MIN_VOLUME_M5 or buys5m < MIN_BUYS_M5:
                    continue

                # Salvar para monitoramento e relatório
                seen_tokens.add(addr)
                monitored_prices[addr] = {"symbol": symbol, "price": price}

                # --- SOLUÇÃO DO LINK (BUSCA POR CONTRATO) ---
                # Esse link não abre o gráfico direto, ele joga o contrato na busca do GMGN.
                # É a forma mais garantida de NÃO dar erro de rede.
                gmgn_fix = f"https://gmgn.ai/sol/token/{addr}"

                msg = (
                    f"🚀 *TOKEN PROMISSOR DETECTADO*\n\n"
                    f"💎 *Ativo:* {symbol}\n"
                    f"📝 *Contrato (Toque para copiar):*\n`{addr}`\n\n"
                    f"💰 Preço: `${price:.8f}`\n"
                    f"💧 Liquidez: `${liq:,.0f}`\n"
                    f"📊 Volume 5m: `${vol5m:,.0f}`\n"
                    f"🔥 Compras 5m: `{buys5m}`\n\n"
                    f"🔗 [ABRIR NO GMGN (LINK DIRETO)]({gmgn_fix})"
                )
                send(msg)

        except Exception as e:
            print(f"Erro Scan: {e}")
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health(): return "BOT ATIVO"

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
