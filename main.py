def iniciar_telegram():
    print("🧹 Iniciando protocolo de limpeza...")
    bot.remove_webhook()
    # Limpa mensagens acumuladas que podem estar travando o bot
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    time.sleep(10)  # Pausa maior para garantir que instâncias antigas desconectem
    
    print("📡 Conectando modo exclusivo...")
    while True:
        try:
            # interval=3 para evitar conflitos rápidos durante o deploy
            bot.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            if "409" in str(e):
                print("⚠️ Conflito detectado. Aguardando 15s para nova tentativa...")
                time.sleep(15)
            else:
                print(f"⚠️ Erro de Polling: {e}")
                time.sleep(5)
