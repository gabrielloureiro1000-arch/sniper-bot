import telebot
import time
import sys
from telebot import apihelper
from requests.exceptions import ConnectionError, ReadTimeout

# --- CONFIGURAÇÕES ---
TOKEN = "SEU_TOKEN_AQUI"
CHAT_ID = "SEU_CHAT_ID_AQUI"
SOL_AMOUNT = 0.1

bot = telebot.TeleBot(TOKEN)
apihelper.RETRY_ON_HTTP_ERROR = True

# Conjunto para evitar compras duplicadas do mesmo contrato no mesmo ciclo
comprados = set()

def safe_send_message(text):
    """Envia mensagem com tratamento de erro para não derrubar o bot"""
    try:
        bot.send_message(CHAT_ID, text, parse_mode='Markdown')
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")

def executar_buy(contrato):
    """Lógica de compra com trava de duplicidade"""
    if contrato in comprados:
        return
    
    try:
        print(f"Executando buy para {contrato}")
        # INSIRA AQUI SUA LÓGICA DE INTEGRAÇÃO COM A API GMGN / SOLANA
        # Exemplo fictício: gmg_api.swap(token_in="SOL", token_out=contrato, amount=SOL_AMOUNT)
        
        safe_send_message(f"✅ **COMPRA EXECUTADA**\nContrato: `{contrato}`\nValor: {SOL_AMOUNT} SOL")
        comprados.add(contrato)
    except Exception as e:
        print(f"Falha na transação: {e}")
        safe_send_message(f"⚠️ **ERRO NA COMPRA**: {contrato}")

def hunter_loop():
    """Loop principal com proteção contra queda de conexão"""
    safe_send_message("🤖 **AUTO-TRADER GMGN ATIVADO**\nMonitorando oportunidades...")
    
    while True:
        try:
            # 1. Simulação de busca de tokens (Substitua pela sua lógica de scan)
            # contrato_detectado = gmg_api.get_new_high_potential_tokens()
            contrato_detectado = "0x873301F2B4B83FeaFF04121B68eC9231B29Ce0df" # Exemplo do seu log

            # 2. Executa a compra
            executar_buy(contrato_detectado)

            # 3. Delay crucial para evitar Rate Limit e Connection Reset
            time.sleep(10) 

        except (ConnectionError, ReadTimeout) as e:
            print(f"Erro de conexão detectado: {e}. Reiniciando loop em 5s...")
            time.sleep(5)
            continue
        except Exception as e:
            print(f"Erro inesperado: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Inicia o hunter dentro de um bloco que impede o crash final
    while True:
        try:
            hunter_loop()
        except KeyboardInterrupt:
            print("Bot parado manualmente.")
            sys.exit()
        except Exception as e:
            print(f"Crash crítico no sistema: {e}. Reiniciando aplicação completa...")
            time.sleep(5)
