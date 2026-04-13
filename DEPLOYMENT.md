# Guia de Deploy e Hospedagem (Produção) 🚀

Este documento detalha as etapas recomendadas para **hospedar** o sistema "Lembrete de Pendente" de forma definitiva em um servidor Linux (ex: Ubuntu/Debian), garantindo que ele rode sempre em segundo plano, reinicie automaticamente em caso de falhas e ligue junto com o sistema operacional.

---

## 🛠️ 1. Preparação do Ambiente

1. **Acesse seu servidor Linux** e instale o Python e o gerenciador de pacotes, se não os tiver:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv
   ```

2. **Clone ou mova a pasta do projeto** para um diretório seguro no servidor. O padrão recomendado é `/opt/lembrete_pendente` ou deixar na pasta do usuário (ex: `/home/sage/Projetos/lembrete de pendente `).
   
3. **Configure as dependências**:
   Navegue até a pasta do projeto e instale as bibliotecas:
   ```bash
   cd "/caminho/para/lembrete de pendente "
   
   # Opcional (recomendado): Criar ambiente virtual
   python3 -m venv venv
   source venv/bin/activate
   
   # Instale as dependências
   pip install -r requirements.txt
   ```

4. **Variáveis de Ambiente**:
   Confirme se o arquivo `.env` está configurado corretamente com as credenciais do Znuny e do Digisac na raiz do projeto.

---

## ⚙️ 2. Criando o Serviço do Sistema (Systemd)

Para que você não precise deixar um terminal aberto, transformaremos o script em um serviço do Linux.

1. **Crie o arquivo de serviço**:
   ```bash
   sudo nano /etc/systemd/system/lembrete_pendente.service
   ```

2. **Cole a configuração abaixo**:
   *(Lembre-se de substituir `/home/sage/Projetos/lembrete de pendente ` pelo caminho real do projeto no seu servidor e o `User` pelo seu usuário)*

   ```ini
   [Unit]
   Description=Lembrete de Pendentes API (Znuny + Digisac)
   After=network.target

   [Service]
   User=sage
   Group=sage
   WorkingDirectory=/home/sage/Projetos/lembrete de pendente 
   
   # Se usou ambiente virtual (venv), aponte pro python dele:
   # ExecStart=/home/sage/Projetos/lembrete de pendente /venv/bin/python3 server.py
   
   # Se não usou venv, use o python3 global:
   ExecStart=/usr/bin/python3 server.py

   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. **Salve o arquivo** (`Ctrl+O`, `Enter`, `Ctrl+X`).

4. **Ative e inicie o serviço**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable lembrete_pendente
   sudo systemctl start lembrete_pendente
   ```

5. **Verifique se está rodando**:
   ```bash
   sudo systemctl status lembrete_pendente
   ```
   *(Se aparecer "active (running)", deu certo! O site já deve estar acessível pelo `localhost:8000`)*

---

## 🌐 3. Expondo na Internet (Nginx Proxy Reverso) - Opcional

Por padrão, a aplicação roda na porta `8000` no seu servidor. Para expor isso na internet de forma mais profissional (na porta 80 ou com HTTPS usando um domínio), use o Nginx.

1. **Instale o Nginx**:
   ```bash
   sudo apt install nginx
   ```

2. **Configure o bloco de servidor**:
   ```bash
   sudo nano /etc/nginx/sites-available/lembrete_pendente
   ```

3. **Cole a configuração abaixo** (se tiver domínio, troque `_` pelo seu domínio):
   ```nginx
   server {
       listen 80;
       server_name _; # Ou coloque seu dominio ex: lembretes.suaempresa.com.br

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }
   }
   ```

4. **Ative o site e reinicie o Nginx**:
   ```bash
   sudo ln -s /etc/nginx/sites-available/lembrete_pendente /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

Pronto! Agora seu painel pode ser acessado pelo IP do servidor diretamente no navegador (ex: `http://IP_DO_SERVIDOR`), 24 horas por dia.

---

## 📚 4. Como Usar

Com o deploy feito, use o sistema acessando a URL configurada (Web) ou diretamente pelo terminal se desejar executar disparos paralelos:

- **Manual do Usuário (Painel Web)**: Leia o arquivo `MANUAL.md` para entender como usar a ferramenta pela interface gráfica (agendamentos semanais etc).
- **Manual do Terminal**: Leia o arquivo `TERMINAL_GUIDE.md` para rodar o robô diretamente (`python3 lembrete_pendente_automacao.py`).

## 🔍 Como ver os Logs de Erro
Caso algo pare de funcionar, você pode ver os logs em tempo real do sistema escutando o serviço:
```bash
journalctl -u lembrete_pendente -f
```
