import os
import telebot
import requests
from flask import Flask
from threading import Thread

TOKEN = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

@app.route('/')
def index(): return "Sniper Bot Ativo"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "🚀 **Monitor Sniper Pro Ativo**\nEnvie o contrato ou link da GMGN/DexScreener para análise rigorosa.")

@bot.message_handler(func=lambda message: True)
def analyze_token(message):
    raw_text = message.text.strip()
    # Extrai contrato de links ou texto puro
    contract = raw_text.split('/')[-1].split('?')[0]
    
    msg_wait = bot.reply_to(message, f"🔍 **Iniciando auditoria no contrato:** `{contract}`...")

    try:
        # Busca dados na DexScreener
        url = f"https://api.dexscreener.com/latest/dex/tokens/{contract}"
        data = requests.get(url).json()

        if not data.get('pairs'):
            bot.edit_message_text("❌ Token sem liquidez ou não encontrado.", message.chat.id, msg_wait.message_id)
            return

        pair = sorted(data['pairs'], key=lambda x: x.get('liquidity', {}).get('usd', 0), reverse=True)[0]
        
        # --- FILTROS DE ELITE (LÓGICA DE GANHO) ---
        liquidity = pair.get('liquidity', {}).get('usd', 0)
        mcap = pair.get('fdv', 0)
        buys = pair.get('txns', {}).get('h24', {}).get('buys', 0)
        sells = pair.get('txns', {}).get('h24', {}).get('sells', 0)
        
        # Cálculo de Volume/Pressão de Compra
        ratio = (buys / (buys + sells)) * 100 if (buys + sells) > 0 else 0
        
        # Alertas de Segurança Simples
        is_safe = "✅ SEGURO" if liquidity > 50000 and mcap > 100000 else "⚠️ RISCO ALTO"
        if liquidity < 10000: is_safe = "🚫 RUGPULL PROVÁVEL (Liquidez Baixa)"

        report = (
            f"📊 **RELATÓRIO DE MERCADO**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💎 **Status:** {is_safe}\n"
            f"🌐 **Rede:** {pair['chainId'].upper()}\n\n"
            f"💰 **Price:** `${pair['priceUsd']}`\n"
            f"📈 **Market Cap:** `${mcap:,.0f}`\n"
            f"💧 **Liquidez:** `${liquidity:,.0f}`\n\n"
            f"📊 **Pressão de Compra:** `{ratio:.1f}%`\n"
            f"🔄 **Transações (24h):** 🟢 {buys} | 🔴 {sells}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 [GMGN.ai](https://gmgn.ai/sol/token/{contract}) | [DexScreener]({pair['url']})\n"
            f"💡 *Dica: Se a liquidez for < 10% do MCap, cuidado!*"
        )

        bot.edit_message_text(report, message.chat.id, msg_wait.message_id, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        bot.edit_message_text(f"⚠️ Erro na análise: {str(e)}", message.chat.id, msg_wait.message_id)

if __name__ == "__main__":
    Thread(target=run).start()
    bot.infinity_polling()
