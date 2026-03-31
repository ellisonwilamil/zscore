# Use a imagem base oficial do Streamlit
FROM python:3.12-slim

ENV TZ=America/Sao_Paulo
RUN apt-get update && apt-get install -y tzdata && \
    ln -fs /usr/share/zoneinfo/${TZ} /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*

# # Instala o cron e dependências necessárias
# RUN apt-get update && apt-get install -y cron && \
#     rm -rf /var/lib/apt/lists/*  # Limpa o cache para reduzir o tamanho da imagem

# Defina o diretório de trabalho
WORKDIR /app

COPY . /app

RUN pip install --upgrade pip

RUN pip install -r requirements.txt

EXPOSE 80

# Dá permissão de execução ao entrypoint
RUN chmod +x init_run.sh
RUN chmod +x src/popula_dados_zscore_freq.sh

# Comando para rodar a aplicação Streamlit
CMD ["./init_run.sh"]






