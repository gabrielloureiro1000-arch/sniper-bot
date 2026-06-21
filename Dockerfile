# ============================================================
# Dockerfile para WHALE HUNTER com GMGN CLI
# ============================================================

# 1. Imagem base do Python
FROM python:3.10

# 2. Instala Node.js e npm (necessário para o GMGN CLI)
RUN apt-get update && apt-get install -y curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 3. Define o diretório de trabalho
WORKDIR /code

# 4. Copia os arquivos do projeto
COPY . .

# 5. Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# 6. Instala o GMGN CLI globalmente
RUN npm install -g gmgn-cli

# 7. Configura variáveis de ambiente para forçar IPv4 (resolve o erro de DNS)
ENV PYTHONUNBUFFERED=1
ENV NODE_OPTIONS="--dns-result-order=ipv4first"

# 8. Comando para rodar o bot
CMD ["python", "main.py"]
