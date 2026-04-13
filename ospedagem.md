Para hospedar esse sistema em uma Máquina Virtual (VM) Linux (como Ubuntu ou Debian) e deixá-lo rodando de forma profissional 24 por dia, 7 dias por semana, o ideal é usar o Systemd para gerenciar o processo em segundo plano (background).

Aqui está o passo a passo completo, do zero ao sistema rodando na VM:

Passo 1: Preparar a VM e Instalar o Python
Acesse a sua VM via SSH e certifique-se de ter o Python 3 instalado.

bash
# Atualize os repositórios da VM
sudo apt update && sudo apt upgrade -y
# Instale o Python, gerenciador de pacotes e ambientes virtuais
sudo apt install python3 python3-pip python3-venv git -y

Passo 2: Transferir o Projeto para a VM
Você pode copiar os arquivos localmente usando FTP/SCP ou clonar via Git. Vamos considerar que você colocou a pasta no diretório /opt/lembrete_pendente.

bash
# Crie o diretório para a aplicação
sudo mkdir -p /opt/lembrete_pendente
sudo chown -R $USER:$USER /opt/lembrete_pendente
# (Transfira os arquivos do seu computador para essa pasta na VM)

Certifique-se de que a estrutura esteja assim: /opt/lembrete_pendente/server.py /opt/lembrete_pendente/lembrete_pendente_automacao.py /opt/lembrete_pendente/static/...

Passo 3: Criar um Ambiente Virtual e Instalar Dependências
É uma boa prática rodar aplicações Python isoladas.

bash
cd /opt/lembrete_pendente
# Cria o ambiente virtual
python3 -m venv venv
# Ativa o ambiente
source venv/bin/activate
# Instala as dependências necessárias (FastAPI, Uvicorn, Requests)
pip install fastapi uvicorn requests

Passo 4: Testar a Aplicação Manualmente
Antes de colocar para rodar automaticamente, vamos testar se o servidor sobe corretamente.

bash
# Garanta que o ambiente virtual ainda está ativado
uvicorn server:app --host 0.0.0.0 --port 8000

Se não houver erros no terminal, você já conseguirá acessar pelo navegador no IP da sua VM: http://IP_DA_SUA_VM:8000. Aperte CTRL + C para parar o teste.

Passo 5: Criar um Serviço Systemd (Para rodar para sempre)
Para garantir que o painel ligue sozinho se a VM reiniciar e rode em segundo plano sem travar o seu terminal, nós criamos um Serviço no Linux.

Crie um novo arquivo de serviço:

bash
sudo nano /etc/systemd/system/lembrete-pendente.service

Cole este conteúdo (ajuste o usuário root se preferir rodar com outro usuário, mas certifique-se das permissões):

ini
[Unit]
Description=Lembrete Pendente - Znuny/Digisac
After=network.target
[Service]
User=root
# O diretório onde colocamos os arquivos
WorkingDirectory=/opt/lembrete_pendente
# Caminho completo do uvicorn dentro do ambiente virtual
ExecStart=/opt/lembrete_pendente/venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
# Se o sistema falhar/crachar, ele reinicia sozinho após 5 segundos
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target

Salve e feche o arquivo (CTRL+O, Enter, CTRL+X).

Passo 6: Ativar e Iniciar o Serviço
Agora avise o sistema operacional sobre este novo arquivo e inicie ele:

bash
# Recarrega a lista de serviços do Linux
sudo systemctl daemon-reload
# Ativa o serviço para iniciar sempre que a VM ligar
sudo systemctl enable lembrete-pendente
# Inicia o serviço agora (roda em background!)
sudo systemctl start lembrete-pendente

Passo 7: Como Monitorar o Robô?
Pronto! Seu servidor já está no ar. Você pode verificar os logs do que ele está fazendo (os "prints" no terminal) a qualquer momento rodando:

bash
# Ver os logs em tempo real
sudo journalctl -u lembrete-pendente -f

💡 (Opcional) Firewall e Segurança
Se a sua VM tiver um firewall ativo (como o ufw), lembre-se de abrir a porta 8000 para acesso web externo:

bash
sudo ufw allow 8000/tcp

Após seguir os 6 passos acima, a aplicação com painel frontend ficará ativa e autônoma, e seus logs de histórico não se perderão desde que você os mantenha persistidos no mesmo diretório (como programamos no .json).

