#!/usr/bin/env python3
"""
Automação de Lembretes de Pendente - Znuny -> Digisac
=====================================================
Busca chamados em "pending reminder" no Znuny, agrupa por cliente,
localiza o contato no Digisac e envia lembrete via WhatsApp.

Uso:
    python3 lembrete_pendente_automacao.py
"""

from typing import List, Dict, Any, Optional, Tuple
import os
import sys
import re
import json
import time
import requests # type: ignore
import urllib3 # type: ignore
import phonenumbers # type: ignore
from datetime import datetime
from dotenv import load_dotenv # type: ignore
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, wait_exponential, stop_after_attempt, RetryError # type: ignore

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# CONFIGURAÇÃO
# ============================================================
# Carrega o .env do próprio diretório do projeto
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

ZNUNY_URL    = os.getenv("ZNUNY_BASE_URL")
ZNUNY_USER   = os.getenv("ZNUNY_USER")
ZNUNY_PASS   = os.getenv("ZNUNY_PASS")
DIGISAC_URL  = os.getenv("DIGISAC_URL")
DIGISAC_TOKEN = os.getenv("DIGISAC_TOKEN")

# Validação: não inicia se faltar alguma variável
_required = {
    "ZNUNY_URL": ZNUNY_URL,
    "ZNUNY_USER": ZNUNY_USER,
    "ZNUNY_PASS": ZNUNY_PASS,
    "DIGISAC_URL": DIGISAC_URL,
    "DIGISAC_TOKEN": DIGISAC_TOKEN,
}
_missing = [k for k, v in _required.items() if not v]
if _missing:
    print(f"[ERRO] Variáveis de ambiente ausentes no .env: {', '.join(_missing)}")
    sys.exit(1)

digisac_headers = {
    "Authorization": f"Bearer {DIGISAC_TOKEN}",
    "Content-Type": "application/json"
}

def log(msg: str) -> None:
    """Exibe mensagens no console com timestamp."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    sys.stdout.flush()




CONTACTS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contacts_cache.json")
GROUPS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "groups_cache.json")
DISABLE_WHATSAPP_TODAY = False  # Define se o WhatsApp deve ser bloqueado hoje

from database import load_db_legacy as load_db, save_db_legacy as save_db, add_escalation_entry # type: ignore

# ============================================================
# 1. ZNUNY: BUSCAR CHAMADOS PENDENTES
# ============================================================

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def get_pending_tickets() -> List[str]:
    """Retorna a lista de IDs dos chamados em 'pending reminder'."""
    url = f"{ZNUNY_URL}/TicketSearch"
    payload = {
        "UserLogin": ZNUNY_USER,
        "Password": ZNUNY_PASS,
        "States": ["pending reminder"],
        "Result": "ARRAY"
    }
    try:
        r = requests.post(url, json=payload, verify=False, timeout=30)
        r.raise_for_status()
        return r.json().get("TicketID", [])
    except Exception as e:
        log(f"   [ERRO] Falha ao buscar tickets no Znuny: {e}")
        raise e

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def fetch_one(t_id: str) -> Optional[Dict[str, Any]]:
    """Busca detalhes de um único ticket com retry."""
    url = f"{ZNUNY_URL}/Ticket/{t_id}"
    params: Dict[str, str] = {
        "UserLogin": str(ZNUNY_USER), 
        "Password": str(ZNUNY_PASS),
        "AllArticles": "1"
    }
    try:
        r = requests.get(url, params=params, verify=False, timeout=15)
        r.raise_for_status()
        data = r.json()
        ticket_list = data.get("Ticket", [])
        for t in ticket_list:
            return {
                "TicketID": str(t_id),
                "TicketNumber": t.get("TicketNumber"),
                "Title": t.get("Title"),
                "CustomerID": t.get("CustomerID"),
                "CustomerUserID": t.get("CustomerUserID"),
                "Articles": t.get("Article", [])
            }
    except Exception as e:
        log(f"   [ERRO] Chamado {t_id}: {e}")
        raise e
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def escalate_ticket(ticket_id: str, new_owner: Optional[str] = None) -> bool:
    """Altera o atendente (Owner) e o estado do chamado."""
    if not new_owner:
        try:
            from database import load_settings_legacy # type: ignore
            settings = load_settings_legacy()
            new_owner = settings.get("escalation_owner", "jean.figueiredo@sagenetworks.com.br")
        except Exception:
            new_owner = "jean.figueiredo@sagenetworks.com.br"
            
    url = f"{ZNUNY_URL}/Ticket/{ticket_id}"
    payload = {
        "UserLogin": str(ZNUNY_USER),
        "Password": str(ZNUNY_PASS),
        "Ticket": {
            "Owner": new_owner,
            "State": "Pendente com o cliente"
        }
    }
    try:
        r = requests.patch(url, json=payload, verify=False, timeout=15)
        log(f"   [DEBUG] Resposta do Patch de Escalamento {ticket_id}: {r.status_code} - {r.text}")
        if r.status_code in [200, 201]:
            data = r.json()
            if "Error" in data:
                log(f"   [ERRO] Znuny rejeitou escalonamento: {data['Error'].get('ErrorMessage')}")
                return False
            return True
        log(f"   [ERRO] Falha HTTP ao escalonar chamado {ticket_id}: {r.status_code} - {r.text}")
        raise Exception(f"HTTP {r.status_code}")
    except Exception as e:
        log(f"   [ERRO] Exceção ao escalonar chamado {ticket_id}: {e}")
        raise e

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def add_znuny_note(ticket_id: str, note_template: str = "") -> bool:
    """Adiciona uma nota interna no chamado informando a tentativa de contato."""
    url = f"{ZNUNY_URL}/Ticket/{ticket_id}"
    
    now = datetime.now()
    date_str = now.strftime("%d/%m/%Y")
    hour_str = now.strftime("%H:%M")
    
    if not note_template:
        note_template = (
            "Realizamos uma tentativa de contato com o cliente hoje, "
            "{data} às {hora}, para obter um retorno referente ao chamado."
        )
        
    try:
        note_text = note_template.format(data=date_str, hora=hour_str)
    except Exception as e:
        log(f"   [ERRO] Falha ao formatar template da nota: {e}")
        note_text = f"Tentativa de contato automática em {date_str} {hour_str}."
    
    payload = {
        "UserLogin": str(ZNUNY_USER),
        "Password": str(ZNUNY_PASS),
        "Article": {
            "CommunicationChannel": "Internal",
            "IsVisibleForCustomer": 0,
            "SenderType": "agent",
            "Subject": "Tentativa de Contato Automática (WhatsApp)",
            "Body": note_text,
            "ContentType": "text/plain; charset=utf8",
            "TimeUnit": 1
        }
    }
    
    try:
        r = requests.patch(url, json=payload, verify=False, timeout=15)
        if r.status_code in [200, 201]:
            return True
        log(f"   [ERRO] Falha ao adicionar nota no chamado {ticket_id}: {r.status_code} - {r.text}")
        raise Exception(f"HTTP {r.status_code}")
    except Exception as e:
        log(f"   [ERRO] Exceção ao adicionar nota no chamado {ticket_id}: {e}")
        raise e


def get_ticket_details(ticket_ids: List[str]) -> List[Dict[str, Any]]:
    """Busca Título, Número e CustomerID de cada chamado."""
    if not ticket_ids:
        return []

    details: List[Dict[str, Any]] = []

    # Limitando workers a 5 para não criar picos na rede/servidor Znuny
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Passamos a função global fetch_one com type ignore para o executor
        future_to_tid = {executor.submit(fetch_one, str(tid)): tid for tid in ticket_ids} # type: ignore
        for future in as_completed(future_to_tid):
            try:
                res = future.result()
                if res:
                    details.append(res)
            except Exception:
                pass

    return details


# ============================================================
# FUNÇÕES — DIGISAC
# ============================================================

def build_contact_cache() -> Dict[str, Dict[str, Any]]:
    """
    Busca todos os contatos no Digisac paginados via /contacts.
    Retorna dicionário: { "ID_CLIENTE": { "id": "uuid", "name": "Nome", "internalName": "Nome Interno", "all_contacts": [...] } }
    Usa cache local de 12 horas para evitar lentidão.
    """
    # 1. Tentar carregar do cache local
    if os.path.exists(CONTACTS_CACHE_FILE):
        try:
            mtime = os.path.getmtime(CONTACTS_CACHE_FILE)
            age_hours = (time.time() - mtime) / 3600
            if age_hours < 12:
                with open(CONTACTS_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    log(f"   [CACHE] Usando cache de contatos (idade: {age_hours:.1f}h, {len(cached_data)} contatos).")
                    return cached_data
        except Exception as e:
            log(f"   [AVISO] Erro ao ler cache de contatos: {e}")

    # 2. Se não houver cache ou estiver expirado, buscar do Digisac
    url = f"{DIGISAC_URL}/contacts"
    page: int = 1
    cache: Dict[str, Dict[str, Any]] = {}

    log("   [DIGISAC] Cache expirado ou ausente. Buscando contatos do Digisac (Isso pode demorar)...")

    try:
        from database import load_settings_legacy # type: ignore
        settings = load_settings_legacy()
        blocked_str = settings.get("blocked_contacts", "")
        blocked_list = [b.strip().lower() for b in blocked_str.split(",") if b.strip()]
    except Exception:
        blocked_list = []

    while int(page) <= 150:
        params = {"page": page, "limit": 100}
        try:
            r = requests.get(url, headers=digisac_headers, params=params, timeout=15)
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                break

            for c in data:
                name: str = str(c.get("name") or "")
                int_name: str = str(c.get("internalName") or "")
                c_id: str = str(c.get("id") or "")
                
                # Digisac pode retornar o número em algum campo (ex: 'number' ou dentro de contatos/devices)
                # Vamos extrair como string se estiver na raiz do objeto de forma simples
                c_number: str = str(c.get("number") or c.get("phone") or "")
                
                # Check blocklist
                is_blocked = False
                for b in blocked_list:
                    # Exigimos match EXATO para o nome (para não bater 'João' e bloquear todo mundo que chama João)
                    # Para ID ou Número, permitimos que seja substring
                    if b == name.lower() or b == int_name.lower() or b == c_id or (b and b in c_number):
                        is_blocked = True
                        break
                        
                if is_blocked:
                    log(f"   [BLOQUEADO] Contato ignorado: {name} ({int_name})")
                    continue
                
                # Procura por padrão [XXXX] no nome ou nome interno
                for field in [int_name, name]:
                    if not field: continue
                    clean_str = str(field).replace(" ", "").upper()
                    
                    match = re.search(r'\[([^\]]+)\]', clean_str)
                    if match:
                        cid = match.group(1)
                        contact_entry: Dict[str, Any] = {
                            "id": str(c.get("id")),
                            "name": name,
                            "internalName": int_name,
                        }
                        if cid and cid not in cache:
                            cache[cid] = {
                                "id": contact_entry["id"],
                                "name": contact_entry["name"],
                                "internalName": contact_entry["internalName"],
                                "all_contacts": [contact_entry],
                            }
                        elif cid and cid in cache:
                            # Evitar duplicatas pelo id
                            # pyre-ignore[16]
                            existing_ids = [ec["id"] for ec in cache[cid].get("all_contacts", [])]
                            if contact_entry["id"] not in existing_ids:
                                # pyre-ignore[16]
                                cache[cid]["all_contacts"].append(contact_entry)
            # pyre-ignore
            page += 1

        except Exception as e:
            log(f"   [ERRO] Página {page} do Digisac: {e}")
            break

    # 3. Salvar no cache local
    if cache:
        try:
            with open(CONTACTS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
        except Exception as e:
            log(f"   [ERRO] Falha ao salvar cache de contatos: {e}")

    log(f"   [DIGISAC] Busca finalizada. {len(cache)} contatos indexados e salvos em cache.")
    return cache


def build_group_cache() -> Dict[str, List[Dict[str, Any]]]:
    """
    Busca todos os grupos no Digisac paginados via /contacts?type=group.
    Retorna dicionário: { "ID_CLIENTE": [ { "id": "uuid", "name": "Nome" }, ...] }
    Usa cache local de 12 horas.
    """
    # 1. Tentar carregar do cache local
    if os.path.exists(GROUPS_CACHE_FILE):
        try:
            mtime = os.path.getmtime(GROUPS_CACHE_FILE)
            age_hours = (time.time() - mtime) / 3600
            if age_hours < 12:
                with open(GROUPS_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    total = sum(len(v) for v in cached_data.values())
                    log(f"   [CACHE] Usando cache de grupos (idade: {age_hours:.1f}h, {total} grupo(s)).")
                    return cached_data
        except Exception as e:
            log(f"   [AVISO] Erro ao ler cache de grupos: {e}")

    # 2. Buscar do Digisac — grupos são contatos do tipo "group"
    url = f"{DIGISAC_URL}/contacts"
    page: int = 1
    cache: Dict[str, List[Dict[str, Any]]] = {}

    log("   [DIGISAC] Buscando grupos do Digisac...")

    while int(page) <= 50:
        params = {"page": page, "limit": 100, "type": "group"}
        try:
            r = requests.get(url, headers=digisac_headers, params=params, timeout=15)
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                break

            for g in data:
                name: str = g.get("name") or ""
                int_name: str = g.get("internalName") or ""

                for field in [int_name, name]:
                    if not field:
                        continue
                    clean_str = str(field).replace(" ", "").upper()
                    match = re.search(r'\[([^\]]+)\]', clean_str)
                    if match:
                        cid = match.group(1)
                        group_entry: Dict[str, Any] = {
                            "id": str(g.get("id")),
                            "name": name,
                            "type": "group",
                        }
                        if cid not in cache:
                            cache[cid] = []
                        # Evitar duplicatas
                        # pyre-ignore[16]
                        existing_ids = [eg["id"] for eg in cache.get(cid, [])]
                        if group_entry["id"] not in existing_ids:
                            # pyre-ignore[16]
                            cache[cid].append(group_entry)
            # pyre-ignore[58]
            page = int(page) + 1

        except Exception as e:
            log(f"   [ERRO] Página {page} de grupos do Digisac: {e}")
            break

    # 3. Salvar no cache local
    if cache:
        try:
            with open(GROUPS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
        except Exception as e:
            log(f"   [ERRO] Falha ao salvar cache de grupos: {e}")

    total_groups = sum(len(v) for v in cache.values())
    log(f"   [DIGISAC] {total_groups} grupo(s) de {len(cache)} cliente(s) indexados.")
    return cache


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=False)
def send_whatsapp_message(contact_id: str, text: str) -> bool:
    """Envia uma mensagem de texto para o contato via Digisac com Retry."""
    if DISABLE_WHATSAPP_TODAY:
        log(f"   [WHATSAPP DESABILITADO] Simulando envio com sucesso (não faturado).")
        return True
        
    url = f"{DIGISAC_URL}/messages"
    payload = {
        "contactId": contact_id,
        "text": text,
        "type": "chat",
        "dontOpenTicket": True
    }
    try:
        r = requests.post(url, headers=digisac_headers, json=payload, timeout=15)
        if r.status_code in [200, 201]:
            return True
        log(f"   [ERRO] Digisac retornou {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}")
    except Exception as e:
        log(f"   [ERRO] Falha no envio: {e}")
        raise e


# ============================================================
# UTILITÁRIO
# ============================================================


def extract_first_name(full_name: str) -> str:
    """
    Extrai apenas o primeiro nome do contato para a saudação.
    Ex: 'Wilgner Vale - WF Telecom [J9M3]' -> 'Wilgner'
    Ex: 'Daniel Menezes - Sebratel'        -> 'Daniel'
    """
    # Primeiro limpamos possíveis hífens ou colchetes que podem estar grudados
    name = full_name.split("-")[0].split("[")[0].strip()
    # Retornamos apenas a primeira palavra
    return name.split(" ")[0].strip()


def count_notification_notes(ticket: Dict[str, Any]) -> Tuple[int, bool]:
    """
    Analisa os artigos (histórico) do chamado retornado pelo Znuny para contar
    quantas notas o robô já enviou, e se já enviou uma hoje.
    
    NOTA: A API do Znuny não retorna o campo CommunicationChannel nos artigos,
    então identificamos as notas do robô pelo Subject contendo 'Tentativa de Contato'
    e pelo SenderType 'agent'.
    """
    articles = ticket.get("Articles", [])
    if not articles:
        return 0, False
        
    count: int = 0
    sent_today = False
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for article in articles:
        sender = str(article.get("SenderType", ""))
        subject = str(article.get("Subject", ""))
        
        # Identifica notas da automação pelo Subject e SenderType
        if sender == "agent" and "Tentativa de Contato" in subject:
            count = count + 1
            # Tenta verificar a data do artigo (vem no formato YYYY-MM-DD HH:MM:SS)
            created = str(article.get("CreateTime", ""))
            if created.startswith(today_str):
                sent_today = True
                    
    return count, sent_today


def cleanup_interactions_db(interactions_db: Dict[str, Any], active_tickets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """[DEPRECADO] Remove do banco de dados chamados que não estão mais ativos no Znuny."""
    # Mantido apenas para não quebrar referências antigas caso existam, mas não mais utilizado.
    return interactions_db

# ============================================================
# ROTINA PRINCIPAL
# ============================================================

def filter_and_process_tickets(client_tickets: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filtra tickets disponíveis garantindo o limite de interações e evitando envios no mesmo dia.
    Também enriquece cada ticket com 'interaction_count' e 'sent_today' para exibição no painel."""
    tickets_to_escalate = []
    tickets_to_remind = []

    for t in client_tickets:
        count, sent_today = count_notification_notes(t)
        
        # Enriquecer o ticket com a contagem para o frontend
        t["interaction_count"] = count
        t["sent_today"] = sent_today
        
        # Se já bateu 3 interações (3 notas do robô), vai para escalonamento
        if count >= 3:
            tickets_to_escalate.append(t)
        else:
            # Apenas lembra se não enviou nota HOJE
            if not sent_today:
                tickets_to_remind.append(t)
                
    return tickets_to_remind, tickets_to_escalate

def process_reminders() -> Dict[str, int]:
    """
    Função principal de orquestração.
    Pode ser rodada no terminal solta ou cron.
    """
    log("=" * 60)
    log("INICIANDO AUTOMAÇÃO DE LEMBRETES DE PENDENTE")
    log("=" * 60)

    log("Iniciando rotina automática de lembretes...")
    
    contacts = build_contact_cache()
    if not contacts:
        log("Parando: Não foi possível carregar contatos do Digisac.")
        return {"sent": 0, "skipped": 0, "not_found": 0, "failed": 0}

    try:
        ticket_ids = get_pending_tickets()
    except Exception as exc_api:
        log(f"Parando: Falha extrema ao acessar o Znuny após retentativas: {exc_api}")
        return {"sent": 0, "skipped": 0, "not_found": 0, "failed": 0}
        
    if not ticket_ids:
        log("Nenhum chamado em pending reminder encontrado. Finalizando.")
        return {"sent": 0, "skipped": 0, "not_found": 0, "failed": 0}
        
    tickets = get_ticket_details(ticket_ids)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in tickets:
        cid = t.get("CustomerID") or "UNKNOWN"
        if cid not in grouped:
            grouped[cid] = []
        grouped[cid].append(t)

    results: Dict[str, int] = {"sent": 0, "skipped": 0, "not_found": 0, "failed": 0}

    log(f"   -> {len(ticket_ids)} chamados encontrados.")

    # 2. Obter detalhes de cada chamado
    log("Etapa 2/4 — Obtendo detalhes (título, cliente) de cada chamado...")
    log(f"   -> {len(tickets)} detalhes carregados com sucesso.")

    # 3. Agrupar por cliente
    log("Etapa 3/4 — Agrupando chamados por cliente...")
    log(f"   -> {len(grouped)} clientes únicos com chamados pendentes.")

    # 4. Construir cache de contatos do Digisac (uma só vez)
    log("Etapa 4/4 — Localizando contatos no Digisac e enviando lembretes...")
    contact_cache = contacts # Use the already built cache

    for cid, client_tickets in grouped.items():
        log(f"\n--- Cliente [{cid}] — {len(client_tickets)} chamado(s) ---")

        # Localizar contato
        contact = contact_cache.get(cid)
        if not contact:
            log(f"   [!] Contato [{cid}] NÃO encontrado no Digisac. Pulando.")
            results["not_found"] += 1
            continue

        log(f"   [OK] Contato: {contact['name']} (ID: {contact['id']})")

        # Escalonamento e verificação diária por interações lendo direto do Znuny
        tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Formatar mensagem APENAS com chamados a lembrar
        clean_name = extract_first_name(str(contact["name"]))
        qtd = len(tickets_to_remind)

        msg: str = (
            f"Olá, {clean_name}. "
            f"Há {qtd} chamado(s) em aberto aguardando o seu retorno. "
            f"Para darmos prosseguimento às tratativas, precisamos do seu "
            f"posicionamento. Poderia verificá-los?\n\n"
            f"Chamados:\n"
        )
        for t in tickets_to_remind:
            msg += f"{t.get('TicketNumber')}: {t.get('Title')}\n"
        
        # Enviar WhatsApp apenas se tivermos tickets para lembrar
        success = False
        if tickets_to_remind:
            try:
                success = send_whatsapp_message(str(contact["id"]), msg)
                if success:
                    log(f"   [ENVIADO] Lembrete enviado para {clean_name}.")
                    results["sent"] += 1
                    
                    # Adicionar nota nos chamados lembrados
                    for t in tickets_to_remind:
                        tid_number = str(t.get("TicketNumber"))
                        tid = str(t.get("TicketID"))
                        try:
                            if add_znuny_note(tid):
                                log(f"      [NOTA] Registro adicionado no chamado {tid_number}.")
                        except Exception as exc_note:
                            log(f"      [!] Falha ao registrar nota no chamado {tid_number}: {exc_note}")
            except Exception as exc_wpp:
                log(f"   [FALHA EXTREMA] Não foi possível enviar para [{cid}]: {exc_wpp}")
                results["failed"] += 1
        else:
            log(f"   [ESCALONADO] Nenhum lembrete enviado. Todos os chamados já atingiram 3 interações.")
            results["skipped"] += 1

        # Tratar tickets escalonados
        for t in tickets_to_escalate:
            tid = str(t.get("TicketID"))
            tid_number = str(t.get("TicketNumber"))
            log(f"   [ESCALONANDO] Chamado {tid_number} atingiu >= 3 interações.")
            try:
                if escalate_ticket(tid):
                    log(f"      [OK] Chamado {tid_number} atribuído e escalonado.")
                    # Registro no banco de dados para contabilização
                    try:
                        add_escalation_entry({
                            "ticket_id": tid,
                            "ticket_number": tid_number,
                            "customer_id": cid,
                            "contact_name": contact["name"],
                            "timestamp": datetime.now().isoformat(),
                            "source": "automacao_cron"
                        })
                    except Exception as e_db:
                        log(f"      [ERRO] Falha ao registrar escalonamento no banco: {e_db}")
            except Exception as e:
                log(f"      [ERRO] Falha ao escalonar chamado {tid_number}: {e}")

        # Pausa entre envios para não estourar rate limit do Digisac
        time.sleep(1)

    log("=" * 60)
    log(f"RESUMO DO ENVIO:")
    log(f" - Clientes Notificados: {results['sent']}")
    log(f" - Clientes Ignorados (Escalonados): {results['skipped']}")
    log(f" - Clientes Não Encontrados: {results['not_found']}")
    log(f" - Falhas de Envio: {results['failed']}")
    log("=" * 60)
    
    return results

if __name__ == "__main__":
    process_reminders()
