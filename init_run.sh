#!/bin/bash

# # Configura o cron job
# echo "0 1 * * * root /usr/local/bin/python3 /app/src/detect_anomalies_cli.py >> /var/log/cron.log 2>&1 && /usr/local/bin/python3 /app/src/aqt_zscore_calculator_cli.py >> /var/log/cron.log 2>&1 && /usr/local/bin/python3 /app/src/frequency_zscore_calculator_cli.py >> /var/log/cron.log 2>&1" > /etc/cron.d/anomaly-job
# chmod +x /etc/cron.d/anomaly-job

# # Inicia o serviço cron em segundo plano
# service cron start

# # Mantém o cron log visível (opcional)
# touch /var/log/cron.log
# tail -f /var/log/cron.log &

echo "Iniciando aplicação Streamlit..."

# chmod +x /app/src/popula_zscore_freq.sh
# chmod +x /app/src/popula_zscore_brutas.sh
# chmod +x /app/src/popula_dados_anomalias.sh

# Roda o Streamlit (mantém o container ativo)
exec streamlit run src/app.py --server.port=80 --server.address=0.0.0.0