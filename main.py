import os
import time
import threading
import requests
import telebot
from flask import Flask

# --- CONFIGURAÇÃO ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEX_INTERVAL = 2 

# FILTROS PARA TOKENS PROMISSORES COM BALEIAS
MIN_LIQUIDITY = 2000       # Liquidez mínima para não ser golpe imediato
MIN_WHALE_BUYS = 8         # Pelo menos 8 compras significativas em 5min
MIN_VOLUME_M5 = 3000       # Volume mínimo de $3k nos últimos 5min para indicar hype

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen_tokens = set()
monitored_prices = {} 

def send(msg):
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Erro Telegram: {e}")

# --- RELATÓRIO DE PERFORMANCE (2H) ---
def performance_report():
    while True:
        time.sleep(7200)
        if not monitored_prices: continue
        report = "📊 *RELATÓRIO DE BALEIAS (2H)*\n\n"
        try:
            addrs = list(monitored_prices.keys())
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                url = f"https://api.dexscreener.com/latest/dex/tokens/{batch}"
                r = requests.get(url, timeout=10)
                pairs = r.json().get("pairs", [])
                prices = {p.get("baseToken", {}).get("address"): float(p.get("priceUsd", 0)) for p in pairs}
                for addr in addrs[i:i+30]:
                    data = monitored_prices[addr]
                    initial = data["price"]
                    current = prices.get(addr, 0)
                    if current > 0:
                        change = ((current - initial) / initial) * 100
                        report += f"{'🚀' if change >= 0 else '🔻'} *{data['symbol']}*: `{change:+.2f}%` desde o sinal\n"
            send(report)
        except Exception as e:
            print(f"Erro Relatório: {e}")

# --- SCANNER WHALE TRACKER ---
def scan():
    print("🐋 BUSCANDO RASTRO DAS BALEIAS NA SOLANA...")
    send("🐋 *Whale Hunter Ativo:* Monitorando acúmulo de baleias...")
    
    while True:
        try:
            # Busca tokens com volume e atividade na Solana
            r = requests.get("https://api.dexscreener.com/latest/dex/search?q=solana", timeout=10)
            if r.status_code != 200: continue
            
            pairs = r.json().get("pairs", [])

            for pair in pairs:
                if pair.get("chainId") != "solana": continue
                
                addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                
                if not addr or addr in seen_tokens: continue

                liq = pair.get("liquidity", {}).get("usd", 0)
                vol5m = pair.get("volume", {}).get("m5", 0)
                buys5m = pair.get("txns", {}).get("m5", {}).get("buys", 0)
                price = float(pair.get("priceUsd", 0))

                # FILTRO DE BALEIAS: Alta liquidez + Volume alto + Muitas compras
                if liq < MIN_LIQUIDITY: continue
                if buys5m < MIN_WHALE_BUYS: continue
                if vol5m < MIN_VOLUME_M5: continue

                seen_tokens.add(addr)
                monitored_prices[addr] = {"symbol": symbol, "price": price}

                # LINK GMGN OTIMIZADO (Foca na atividade para você ver as baleias)
                gmgn_url = f"https://gmgn.ai/sol/token/{addr}"

                msg = (
                    f"🐋 *BALEIAS DETECTADAS EM: ${symbol}*\n"
                    f"🔥 *Sinal Promissor - Alta Atividade*\n\n"
                    f"📄 ` {addr} `\n\n"
                    f"💰 Preço: `${price:.10f}`\n"
                    f"💧 Liquidez: `${liq:,.0f}`\n"
                    f"📊 Volume 5m: `${vol5m:,.0f}`\n"
                    f"📈 Compras Recentes: `{buys5m}` baleias/grandes trades\n\n"
                    f"🔗 [ABRIR NO GMGN (VER ATIVIDADE)]({gmgn_url})"
                )
                send(msg)

        except Exception as e:
            print(f"Erro Scan: {e}")
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health(): return "WHALE SNIPER ONLINE"

if __name__ == "__main__":
    threading.Thread(target=scan, daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
