1. Montando o ambiente para usar sem interface grafica

sudo apt install -y python3-pip python3-venv libpq-dev build-essential


# Navegue até a pasta do seu projeto
cd /caminho/do/projeto

# Crie o ambiente virtual
python3 -m venv venv

# Ative o ambiente
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

DB_ADDRESS=localhost
DB_PORT=5432
DB_NAME=industrial_db
DB_USERNAME=analytics_worker
DB_PASSWORD=aqtech_password




Se quiser agendar o disparo dos scritps sem depender de ferramentas externas:
crontab -e
# Adicione a linha para rodar todo dia às 03:00 AM
00 03 * * * /caminho/do/projeto/venv/bin/python /caminho/do/projeto/detect_anomalies_cli.py

