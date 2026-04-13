# Manual de Uso: Lembrete de Pendentes (Znuny + Digisac)

Este documento descreve como iniciar, acessar e operar o sistema de lembretes automatizados.

---

## 🚀 1. Como Iniciar o Sistema (Via Terminal)

O sistema foi construído usando **Python** e servidor web **FastAPI**.

### Pré-requisitos
Certifique-se de estar dentro da pasta do projeto (`/home/sage/Projetos/lembrete de pendente `) e que todas as dependências do `requirements.txt` estão instaladas.
Caso falte alguma, execute:
```bash
python3 -m pip install -r requirements.txt --break-system-packages
```

### Ligando o Servidor
Para iniciar a aplicação, abra seu terminal e execute o seguinte comando:

```bash
python3 server.py
```

Você verá no terminal uma mensagem indicando que o servidor está rodando na porta `8000`, e logando que começou a buscar dados no Znuny.
*Dica: Deixe este terminal aberto. Fechar a janela derrubará o sistema.*

---

## 🖥️ 2. Como Usar o Sistema (Via Web - Navegador)

Com o servidor rodando, abra o seu navegador de internet e acesse:
👉 **[http://localhost:8000](http://localhost:8000)**

### Funcionalidades do Painel Web

1. **Dashboard Inicial**
   - Ao abrir a página, o sistema carregará instantaneamente (via Cache rápido).
   - Você verá cards de resumo indicando: *Total de Chamados*, *Clientes Únicos*, e *Envios Hoje*.
   - A lista detalha todos os clientes com tickets aguardando retorno (status `pendente lembrete`).

2. **Realizar Envios Manuais**
   - Na lista, você pode clicar no botão **"Pré-visualizar & Enviar"** ao lado de um nome para ver a mensagem exata antes da aprovação e enviá-la imediatamente para aquele cliente específico.
   - Para enviar avisos para todos de uma vez, clique no botão azul **"Enviar para Todos (Lote)"** no topo.

3. **Agendamento de Envios Automáticos**
   - Clique em **"Agendar Envio"** no topo.
   - Você pode escolher duas modalidades:
     - **Envio Único:** Define uma data e hora específicas do futuro.
     - **Toda Semana:** Escolha (selecionando as caixas) os dias exatos e um horário (ex: Segundas, Quartas e Sextas, às 09:00).
   - O sistema criará o agendamento salvo com persistência.

4. **Botão de Atualizar/Sincronizar Manual**
   - Os dados do Znuny + Digisac com a lista de pendentes ficam sincronizando de forma transparente **a cada 5 minutos**. 
   - Se desejar ver a versão mais atualizada imediatamente (logo depois de alterar algo no próprio Znuny), você pode re-sincronizar clicando no botão **↻ Recarregar**, e ele forçará um *fetch* de plano de fundo.

5. **Aba Relatórios & Histórico**
   - Pelo botão **Histórico**, você tem o registro individual de clientes que receberam mensagens com sucesso ou relataram falhas.
   - Pelo botão **Relatórios**, você tem um resumo generalizado dos ciclos de disparos em lote/agendados. Pode baixar no formato `.txt` para manter na sua máquina um relatório limpo de performance diária!

---

## ⚡ Confiabilidade & Automação de Fundo
Lembre-se: O servidor reiniciará automaticamente os agendamentos **pendentes** ou **atrasados** sempre que for ligado novamente (graças à persistência do arquivo JSON local). Não é preciso reagendar caso o computador desligue.
