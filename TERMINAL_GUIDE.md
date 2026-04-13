# Guia de Uso: Execução via Terminal 🖥️

Este documento detalha como rodar a automação de lembretes diretamente pelo terminal, sem depender da interface web.

## 🚀 Passo a Passo para Execução

### 1. Preparação do Ambiente
Certifique-se de estar na pasta do projeto e com o ambiente virtual (opcional, mas recomendado) ativado.

```bash
cd "/home/sage/Projetos/lembrete de pendente "
# Se houver venv: source venv/bin/activate
```

### 2. Comando de Execução
Para disparar o envio imediato, execute o "motor" da automação:

```bash
python3 lembrete_pendente_automacao.py
```

---

## 🧐 O que acontece durante a execução?

Ao rodar o comando acima, o robô seguirá este fluxo visual no terminal:

### Etapa 1: Início e Conexão
O terminal exibirá o cabeçalho e iniciará a contrução do cache de contatos do Digisac.
```text
[2026-02-23 10:55:01] ============================================================
[2026-02-23 10:55:01] INICIANDO AUTOMAÇÃO DE LEMBRETES DE PENDENTE
[2026-02-23 10:55:01] ============================================================
[2026-02-23 10:55:01] Iniciando rotina automática de lembretes...
[2026-02-23 10:55:01]    Construindo cache de contatos do Digisac...
[2026-02-23 10:55:03]    Cache construído: 450 contatos indexados.
```

### Etapa 2: Busca no Znuny
Ele buscará os IDs de chamados em "pending reminder" e carregará os detalhes.
```text
[2026-02-23 10:55:04]    -> 15 chamados encontrados.
[2026-02-23 10:55:04] Etapa 2/4 — Obtendo detalhes (título, cliente) de cada chamado...
[2026-02-23 10:55:06]    -> 15 detalhes carregados com sucesso.
```

### Etapa 3: Agrupamento
Ele agrupará os chamados por cliente.
```text
[2026-02-23 10:55:06] Etapa 3/4 — Agrupando chamados por cliente...
[2026-02-23 10:55:06]    -> 8 clientes únicos com chamados pendentes.
```

### Etapa 4: Envio no WhatsApp
O robô percorrerá a lista de clientes e enviará as mensagens.
```text
[2026-02-23 10:55:06] Etapa 4/4 — Localizando contatos no Digisac e enviando lembretes...

--- Cliente [JS8E] — 3 chamado(s) ---
[2026-02-23 10:55:07]    [OK] Contato: Daniel Menezes (ID: uuid-xxxx-xxxx)
[2026-02-23 10:55:08]    [ENVIADO] Lembrete enviado para Daniel.
[2026-02-23 10:55:08]       [NOTA] Registro adicionado no chamado 2033071.
[2026-02-23 10:55:09]       [NOTA] Registro adicionado no chamado 2033072.
[2026-02-23 10:55:09]       [NOTA] Registro adicionado no chamado 2033073.

--- Cliente [ABCD] — 1 chamado(s) ---
[2026-02-23 10:55:10]    [!] Contato [ABCD] NÃO encontrado no Digisac. Pulando.
```

### Etapa 5: Resumo Final
Um relatório simplificado aparecerá ao término.
```text
[2026-02-23 10:55:15] ============================================================
[2026-02-23 10:55:15] RESUMO DO ENVIO:
[2026-02-23 10:55:15]  - Clientes Notificados: 7
[2026-02-23 10:55:15]  - Clientes Não Encontrados: 1
[2026-02-23 10:55:15]  - Falhas de Envio: 0
[2026-02-23 10:55:15] ============================================================
```

---

## 💡 Dicas Importantes:
- **Pausa entre envios**: O sistema espera 1 segundo entre cada cliente para evitar bloqueios do Digisac.
- **Registro no Znuny**: Assim que o lembrete é enviado no WhatsApp, o sistema adiciona automaticamente uma nota interna do tipo `Article` no próprio ticket no Znuny informando a data e hora do contato.
- **Vincular Contatos**: Lembre-se que o robô só encontra o contato se o nome ou "Nome Interno" no Digisac contiver o ID do cliente entre colchetes, por exemplo: `Daniel Menezes [JS8E]`.
- **Modo Silencioso**: Toda a execução via terminal é documentada automaticamente na aba de **Histórico** da interface Web também!
