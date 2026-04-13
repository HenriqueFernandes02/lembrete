#!/bin/bash

# Script de Setup Automático - Lembrete de Pendente v2.0
# Rode na sua VM: chmod +x setup.sh && ./setup.sh

echo "=============================================="
echo "   Iniciando Setup do Lembrete de Pendente    "
echo "=============================================="

# 1. Instalar dependências de sistema
echo "[1/5] Instalandos dependências de sistema..."
sudo apt update
sudo apt install -y python3-pip python3-venv git

# 2. Configurar Ambiente Virtual
echo "[2/5] Criando ambiente virtual Python..."
python3 -m venv venv
source venv/bin/activate

# 3. Instalar bibliotecas Python
echo "[3/5] Instalandos dependências do projeto..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Criar arquivo .env se não existir
if [ ! -f .env ]; then
    echo "[4/5] Criando arquivo .env base (preencha com seus dados)..."
    cat <<EOF > .env
ZNUNY_BASE_URL=seu_url_znuny
ZNUNY_USER=seu_usuario
ZNUNY_PASS=sua_senha
DIGISAC_URL=seu_url_digisac
DIGISAC_TOKEN=seu_token_digisac
EOF
    echo "(!) Alerta: Edite o arquivo .env com suas credenciais reais."
else
    echo "[4/5] Arquivo .env já existe. Pulando..."
fi

# 5. Criar script de execução em background
echo "[5/5] Criando script de inicialização (start.sh)..."
cat <<EOF > start.sh
#!/bin/bash
source venv/bin/activate
nohup python3 server.py > server.log 2>&1 &
echo "Servidor iniciado em background (veja server.log)"
EOF
chmod +x start.sh

echo "=============================================="
echo "   Setup concluído com sucesso!              "
echo "   Acesse a pasta e rode: ./start.sh         "
echo "=============================================="
