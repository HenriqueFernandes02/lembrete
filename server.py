#!/usr/bin/env python3
"""
Servidor FastAPI — Painel de Controle de Lembretes Znuny → Digisac
==================================================================
Expõe a lógica de lembrete_pendente_automacao.py como API REST
e serve o frontend estático.

Inclui:
- Re-verificação automática antes de cada envio
- Agendamento de envios com data/hora
"""

import os
import json
import time
import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import uvicorn # type: ignore
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks # type: ignore
from fastapi.staticfiles import StaticFiles # type: ignore
from fastapi.responses import FileResponse, JSONResponse # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler # type: ignore
from apscheduler.triggers.date import DateTrigger # type: ignore
from apscheduler.triggers.cron import CronTrigger # type: ignore

# Importa funções do script existente
from lembrete_pendente_automacao import ( # type: ignore
    get_pending_tickets,
    get_ticket_details,
    build_contact_cache,
    build_group_cache,
    send_whatsapp_message,
    extract_first_name,
    add_znuny_note,
    log,
    filter_and_process_tickets,
    escalate_ticket,
    GROUPS_CACHE_FILE,
)

# ============================================================
# APP
# ============================================================

# ============================================================
# LIFESPAN (substitui on_event depreciado)
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização e desligamento controlados da aplicação."""
    # Startup
    restore_pending_schedules()
    threading.Thread(target=refresh_data_sync, daemon=True).start()
    scheduler.add_job(refresh_data_sync, 'interval', minutes=5, id="auto_refresh_cache", replace_existing=True)
    yield
    # Shutdown
    scheduler.shutdown(wait=False)

app = FastAPI(title="Lembretes Znuny → Digisac", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Diretório para dados persistentes
DATA_DIR = Path(__file__).parent
HISTORY_FILE = DATA_DIR / "history.json"
SCHEDULES_FILE = DATA_DIR / "schedules.json"
REPORTS_FILE = DATA_DIR / "reports.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
ESCALATION_REPORTS_FILE = DATA_DIR / "escalation_reports.json"

DEFAULT_TEMPLATE = (
    "Olá, {nome}. "
    "Há {quantidade} chamado(s) em aberto aguardando o seu retorno. "
    "Para darmos prosseguimento às tratativas, precisamos do seu "
    "posicionamento. Poderia verificá-los?\n\n"
    "Chamados:\n{lista_chamados}"
)

DEFAULT_NOTE_TEMPLATE = (
    "Realizamos uma tentativa de contato com o cliente hoje, "
    "{data} às {hora}, para obter um retorno referente ao chamado."
)

# Cache em memória (renovado a cada chamada explícita)
_cache: Dict[str, Any] = {
    "tickets": [],
    "grouped": {},
    "contacts": {},
    "groups": {},
    "last_refresh": None,
}

# Trava para evitar sobreposição de execuções concorrentes na API
_send_lock = threading.Lock()

# Armazenamento em memória para progresso das Background Tasks
bg_tasks_status: Dict[str, Any] = {}

# ============================================================
# SCHEDULER
# ============================================================

scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
scheduler.start()


from database import ( # type: ignore
    load_history_legacy as load_history,
    save_history_legacy as save_history,
    load_settings_legacy as load_settings,
    save_settings_legacy as save_settings,
    load_schedules_legacy as load_schedules,
    save_schedules_legacy as save_schedules,
    load_reports_legacy as load_reports,
    load_escalation_reports_legacy as load_escalation_reports,
    save_escalation_reports_legacy as save_escalation_reports,
    add_report_legacy,
    add_escalation_entry
)

def save_reports(reports: list):
    # Compatibility interface since saving is now done cumulatively via add_report_legacy
    pass


def already_sent_today(customer_id: str, history_data: Optional[list] = None) -> bool:
    """Verifica se já enviou lembrete para este cliente hoje."""
    today = date.today().isoformat()
    entries = history_data if history_data is not None else load_history()
    for entry in entries:
        if entry.get("customer_id") == customer_id and entry.get("date") == today and entry.get("success"):
            return True
    return False


def build_message(contact_name: str, tickets: list) -> str:
    """Monta a mensagem de lembrete a partir do template configurado."""
    clean_name = extract_first_name(contact_name)
    qtd = len(tickets)
    
    settings = load_settings()
    template = settings.get("template", DEFAULT_TEMPLATE)
    
    lista = ""
    for t in tickets:
        lista += f"{t['TicketNumber']}: {t['Title']}\n"
        
    try:
        msg = template.format(
            nome=clean_name,
            quantidade=qtd,
            lista_chamados=lista
        )
    except Exception as e:
        log(f"   [ERRO] Falha ao formatar template: {e}. Usando padrão.")
        msg = DEFAULT_TEMPLATE.format(
            nome=clean_name,
            quantidade=qtd,
            lista_chamados=lista
        )
        
    return msg


def refresh_data_sync() -> Tuple[List[Any], Dict[str, List[Any]], Dict[str, Any]]:
    """
    Re-busca chamados no Znuny e contatos no Digisac.
    Atualiza o cache em memória. Retorna (tickets, grouped, contacts).
    """
    log("RE-VERIFICAÇÃO: Buscando chamados pendentes no Znuny...")
    ticket_ids = get_pending_tickets()

    if not ticket_ids:
        _cache["tickets"] = []
        _cache["grouped"] = {}
        _cache["last_refresh"] = datetime.now().isoformat()
        return [], {}, _cache.get("contacts", {})

    log(f"RE-VERIFICAÇÃO: {len(ticket_ids)} IDs encontrados. Carregando detalhes...")
    tickets = get_ticket_details(ticket_ids)

    # Enriquecer cada ticket com a contagem de interações do Znuny
    from lembrete_pendente_automacao import count_notification_notes  # type: ignore
    for t in tickets:
        count, sent_today = count_notification_notes(t)
        t["interaction_count"] = count
        t["sent_today"] = sent_today

    # Agrupar por CustomerID
    grouped = {}
    for t in tickets:
        cid = t.get("CustomerID", "UNKNOWN")
        if cid not in grouped:
            grouped[cid] = []
        grouped[cid].append(t)

    # Re-construir cache de contatos
    log("RE-VERIFICAÇÃO: Reconstruindo cache de contatos do Digisac...")
    contacts = build_contact_cache()

    log("RE-VERIFICAÇÃO: Reconstruindo cache de grupos do Digisac...")
    groups = build_group_cache()
    _cache["groups"] = groups

    _cache["tickets"] = tickets
    _cache["grouped"] = grouped
    _cache["contacts"] = contacts
    _cache["last_refresh"] = datetime.now().isoformat()

    log(f"RE-VERIFICAÇÃO: {len(tickets)} chamados, {len(grouped)} clientes, {len(contacts)} contatos, {len(groups)} cliente(s) com grupo.")
    return tickets, grouped, contacts


def execute_scheduled_send(schedule_id: str) -> None:
    """
    Executa o envio agendado: re-verifica chamados e envia.
    Chamado pelo APScheduler no horário agendado.
    """
    log(f"AGENDAMENTO [{schedule_id}]: Iniciando envio agendado...")

    with _send_lock:
        # Atualizar status do agendamento
        schedules = load_schedules()
        schedule = None
        for s in schedules:
            if s["id"] == schedule_id:
                schedule = s
                s["status"] = "executando"
                break

        if not schedule:
            log(f"AGENDAMENTO [{schedule_id}]: Não encontrado. Ignorando.")
            return

        save_schedules(schedules)

        try:
            # Re-verificar chamados (SEMPRE re-busca antes de enviar)
            tickets, grouped, contacts = refresh_data_sync()

            if not grouped:
                log(f"AGENDAMENTO [{schedule_id}]: Nenhum chamado pendente encontrado.")
                for s in schedules:
                    if s["id"] == schedule_id:
                        s["status"] = "concluido"
                        s["resultado"] = "Nenhum chamado pendente encontrado"
                        s["executado_em"] = datetime.now().isoformat()
                save_schedules(schedules)
                return

            # Enviar para todos
            results = {"sent": 0, "skipped": 0, "failed": 0, "not_found": 0}

            today_str = datetime.now().strftime("%Y-%m-%d")  # BUG FIX: deve ser só a data para compatibilidade com already_sent_today()
            history_in_mem = load_history()
            
            for customer_id, client_tickets in grouped.items():
                try:
                    if already_sent_today(customer_id, history_in_mem):
                        results["skipped"] += 1
                        continue

                    contact = contacts.get(customer_id)
                    if not contact:
                        results["not_found"] += 1
                        continue
                        
                    tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)
                    
                    for t in tickets_to_escalate:
                        try:
                            tid = str(t.get("TicketID"))
                            tn = str(t.get("TicketNumber"))
                            owner = load_settings().get("escalation_owner", "jean.figueiredo@sagenetworks.com.br")
                            if escalate_ticket(tid, owner):
                                add_escalation_entry({
                                    "ticket_id": tid,
                                    "ticket_number": tn,
                                    "customer_id": customer_id,
                                    "contact_name": contact["name"],
                                    "timestamp": datetime.now().isoformat(),
                                    "source": f"agendamento [{schedule_id}]"
                                })
                        except Exception as e_esc:
                            log(f"AGENDAMENTO [{schedule_id}]: [ERRO] Falha ao escalonar ticket {t.get('TicketNumber')}: {e_esc}")
                        
                    if not tickets_to_remind:
                        # pyre-ignore[16]
                        results["skipped"] = int(results["skipped"]) + 1
                        continue

                    msg = build_message(contact["name"], tickets_to_remind)
                    settings = load_settings()
                    
                    contacts_to_send = contact.get("all_contacts", [contact]) if settings.get("multi_contact") else [contact]
                    success = False
                    
                    for c in contacts_to_send:
                        try:
                            if settings.get("enable_whatsapp", True):
                                if send_whatsapp_message(str(c.get("id")), msg):
                                    success = True
                            else:
                                success = True
                                log(f"AGENDAMENTO [{schedule_id}]: Envio de WhatsApp desabilitado nas configurações para [{customer_id}] - {c.get('name')}")
                        except Exception as e_send:
                            log(f"AGENDAMENTO [{schedule_id}]: [ERRO] Falha WhatsApp para {c.get('name')} [{customer_id}]: {e_send}")

                    # Enviar para grupos do Digisac com o ID do cliente (se habilitado)
                    if settings.get("enable_group_send", False):
                        group_cache: Dict[str, Any] = _cache.get("groups") or {}
                        client_groups = group_cache.get(customer_id, [])
                        for grp in client_groups:
                            try:
                                if settings.get("enable_whatsapp", True):
                                    if send_whatsapp_message(str(grp["id"]), msg):
                                        log(f"AGENDAMENTO [{schedule_id}]: Mensagem enviada ao grupo '{grp['name']}' do cliente [{customer_id}].")
                                else:
                                    log(f"AGENDAMENTO [{schedule_id}]: Envio de WhatsApp desabilitado (grupo '{grp['name']}' ignorado).")
                            except Exception as e_grp:
                                log(f"AGENDAMENTO [{schedule_id}]: [ERRO] Falha ao enviar para grupo '{grp.get('name')}': {e_grp}")

                    entry = {
                        "customer_id": customer_id,
                        "contact_name": contact["name"] + (f" (+{len(contacts_to_send)-1})" if len(contacts_to_send) > 1 else ""),
                        "contact_id": contact["id"],
                        "tickets_count": len(tickets_to_remind),
                        "date": today_str,
                        "timestamp": datetime.now().isoformat(),
                        "success": success,
                        "source": "agendamento",
                        "schedule_id": schedule_id,
                    }
                    history_in_mem.insert(0, entry)
                    save_history(history_in_mem)

                    if success:
                        # pyre-ignore[16]
                        results["sent"] = int(results["sent"]) + 1 # type: ignore
                        # Registrar nota no Znuny para chamados lembrados
                        for t in tickets_to_remind:
                            tid_number = str(t.get("TicketNumber"))
                            tid = str(t.get("TicketID"))
                            
                            try:
                                if settings.get("enable_znuny_note", True):
                                    add_znuny_note(tid, settings.get("note_template", ""))
                            except Exception as e_note:
                                log(f"AGENDAMENTO [{schedule_id}]: [ERRO] Falha nota Znuny no ticket {tid_number}: {e_note}")
                    else:
                        # pyre-ignore[16]
                        results["failed"] = int(results["failed"]) + 1 # type: ignore

                except Exception as e_client:
                    log(f"AGENDAMENTO [{schedule_id}]: [ERRO GERAL] Falha ao processar cliente [{customer_id}]: {e_client}")
                    results["failed"] = int(results["failed"]) + 1

                time.sleep(1)

            # Salvar Relatório de Execução Completo
            report_entry = {
                "id": str(uuid.uuid4()).split("-")[0],
                "timestamp": datetime.now().isoformat(),
                "source": f"agendamento [{schedule_id}]",
                "sent": results["sent"],
                "skipped": results["skipped"],
                "not_found": results["not_found"],
                "failed": results["failed"],
                "total_processed": int(results["sent"]) + int(results["skipped"]) + int(results["not_found"]) + int(results["failed"])
            }
            add_report_legacy(report_entry)

            # Atualizar agendamento como concluído
            schedules = load_schedules()
            for s in schedules:
                if s["id"] == schedule_id:
                    if s.get("type") == "recorrente":
                        s["status"] = "pendente" # Volta pra pendente aguardando próxima execução
                    else:
                        s["status"] = "concluido"
                        
                    s["resultado"] = (
                        f"Enviados: {results['sent']}, "
                        f"Ignorados: {results['skipped']}, "
                        f"Não encontrados: {results['not_found']}, "
                        f"Falhas: {results['failed']}"
                    )
                    s["executado_em"] = datetime.now().isoformat()
            save_schedules(schedules)

            log(f"AGENDAMENTO [{schedule_id}]: Concluído. {results}")

        except Exception as e:
            log(f"AGENDAMENTO [{schedule_id}]: Erro inesperado: {e}")
            schedules = load_schedules()
            for s in schedules:
                if s["id"] == schedule_id:
                    if s.get("type") == "recorrente":
                        s["status"] = "pendente"
                    else:
                        s["status"] = "falhou"
                    s["resultado"] = f"Erro na execução: {e}"
                    s["executado_em"] = datetime.now().isoformat()
            save_schedules(schedules)

# ============================================================
# RESTAURAR AGENDAMENTOS PENDENTES (ao iniciar o servidor)
# ============================================================

def restore_pending_schedules():
    """Restaura agendamentos pendentes ao iniciar o servidor."""
    schedules = load_schedules()
    now = datetime.now()

    for s in schedules:
        if s.get("status") not in ["pendente", "atrasado_executando"]:
            continue
            
        # Trata recorrentes (CronTrigger)
        if s.get("type") == "recorrente":
            log(f"Restaurando agendamento recorrente [{s['id']}] para os dias: {s.get('weekdays', [])} às {s.get('time', '09:00')}...")
            days_str = ",".join(s.get("weekdays", []))
            hour, minute = s.get("time", "09:00").split(":")
            
            try:
                scheduler.add_job(
                    execute_scheduled_send,
                    trigger=CronTrigger(day_of_week=days_str, hour=hour, minute=minute),
                    id=s["id"],
                    args=[s["id"]],
                    replace_existing=True,
                )
            except Exception as e:
                log(f"Erro ao restaurar agendamento recorrente [{s['id']}]: {e}")
                
        # Trata unicos (DateTrigger)
        else:
            scheduled_dt = datetime.fromisoformat(s["scheduled_for"])

            if scheduled_dt <= now:
                # Já passou do horário — executar imediatamente
                log(f"Restaurando agendamento atrasado [{s['id']}]...")
                s["status"] = "atrasado_executando"
                save_schedules(schedules)
                threading.Thread(
                    target=execute_scheduled_send,
                    args=(s["id"],),
                    daemon=True,
                ).start()
            else:
                # Ainda no futuro — re-agendar
                log(f"Restaurando agendamento futuro [{s['id']}] para {s['scheduled_for']}...")
                scheduler.add_job(
                    execute_scheduled_send,
                    trigger=DateTrigger(run_date=scheduled_dt),
                    id=s["id"],
                    args=[s["id"]],
                    replace_existing=True,
                )


# ============================================================
# ENDPOINTS ADICIONAIS
# ============================================================

@app.get("/api/settings")
async def api_get_settings():
    return load_settings()

@app.post("/api/settings")
async def api_post_settings(payload: dict):
    save_settings(payload)
    return {"success": True}

@app.get("/api/metrics")
async def api_get_metrics():
    history = load_history()
    reports = load_reports()
    
    # Métricas dos últimos 7 dias
    today = date.today()
    days = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        days.append(day.isoformat())
        
    daily_sent = {d: 0 for d in days}
    for entry in history:
        d = entry.get("date")
        if d in daily_sent and entry.get("success"):
            daily_sent[d] = int(daily_sent[d]) + 1
            
    # Total de escalonamentos (baseado nos relatórios de escalonamento)
    esc_reports = load_escalation_reports()
    total_escalated: int = 0
    for esc in esc_reports:
        try:
            # Tenta tratar diferentes formatos de timestamp (ISO ou YYYY-MM-DD)
            ts = esc.get("timestamp", "")
            if "T" in ts:
                dt = datetime.fromisoformat(ts).date()
            else:
                dt = date.fromisoformat(ts)
                
            if (today - dt).days <= 7:
                total_escalated += 1
        except Exception as e_metric:
            log(f"Erro ao processar métrica de escalonamento: {e_metric}")
            continue
            
    return {
        "success": True,
        "daily_sent": daily_sent,
        "total_escalated_week": total_escalated,
        "labels": days
    }

# ============================================================
# API: STATUS E DADOS
# ============================================================

@app.get("/api/status")
async def api_status():
    """Health check e status das APIs."""
    pending_schedules = [s for s in load_schedules() if s.get("status") == "pendente"]
    return {
        "status": "online",
        "server_time": datetime.now().isoformat(),
        "last_refresh": _cache["last_refresh"],
        "tickets_cached": len(_cache["tickets"]),
        "contacts_cached": len(_cache["contacts"]),
        "pending_schedules": len(pending_schedules),
    }


@app.get("/api/tickets")
async def api_tickets():
    """Retorna os chamados pendentes com base no cache local (Instantâneo)."""
    grouped: Dict[str, Any] = _cache.get("grouped") or {}
    tickets: List[Any] = _cache.get("tickets") or []
    
    if not grouped:
        # Se vazio, indica que ainda não carregou ou não há.
        return {"tickets": [], "grouped": {}, "interactions": {}, "total": 0, "clients": 0}

    log(f"API (/tickets): Servindo {len(tickets)} chamados do cache instantaneamente.")
    
    return {
        "success": True,
        "tickets": tickets,
        "grouped": grouped,
        "interactions": {},
        "total": len(tickets),
        "clients": len(grouped),
    }

@app.post("/api/refresh")
async def api_refresh():
    """Força um recarregamento da base do Znuny em Background."""
    threading.Thread(target=refresh_data_sync, daemon=True).start()
    return {"success": True, "message": "Sincronização iniciada em segundo plano. Os dados atualizarão em breve."}

@app.get("/api/contacts/cache")
async def api_contacts_cache():
    """Constrói e retorna o cache de contatos e grupos do Digisac."""
    log("API: Construindo cache de contatos do Digisac...")
    contacts = build_contact_cache()
    _cache["contacts"] = contacts
    log(f"API: {len(contacts)} contatos indexados.")

    log("API: Construindo cache de grupos do Digisac...")
    groups = build_group_cache()
    _cache["groups"] = groups
    total_groups = sum(len(v) for v in groups.values())
    log(f"API: {total_groups} grupo(s) indexados para {len(groups)} cliente(s).")

    return {"contacts": contacts, "groups": groups, "total": len(contacts)}


@app.post("/api/preview")
async def api_preview(payload: dict):
    """
    Pré-visualiza a mensagem de um cliente (sem enviar).
    """
    customer_id = str(payload.get("customer_id"))
    
    grouped: Dict[str, Any] = _cache.get("grouped") or {}
    contacts: Dict[str, Any] = _cache.get("contacts") or {}

    client_tickets = grouped.get(customer_id)
    if not client_tickets:
        raise HTTPException(status_code=404, detail=f"Nenhum chamado para [{customer_id}].")

    contact = contacts.get(customer_id)
    if not contact:
        raise HTTPException(status_code=404, detail=f"Contato [{customer_id}] não encontrado no Digisac.")

    tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)

    contact_name = str(contact.get("name", ""))
    msg = build_message(contact_name, tickets_to_remind)
    # BUG FIX: frontend espera o campo already_sent_today
    sent_today = already_sent_today(customer_id)

    return {
        "success": True,
        "customer_id": customer_id,
        "contact": contact,
        "contact_name": contact_name,
        "message_preview": msg,
        "tickets_count": len(tickets_to_remind),
        "escalated_count": len(tickets_to_escalate),
        "already_sent_today": sent_today,
    }


@app.post("/api/send-all/preview")
async def api_send_all_preview():
    """
    Retorna a lista completa de clientes que receberão lembretes,
    com detalhes do contato. Usado para a tela de confirmação.
    Re-busca os dados para garantir que estão atualizados.
    """
    log("API PREVIEW: Re-verificando chamados antes de gerar preview...")

    # Re-buscar dados atualizados
    ticket_ids = get_pending_tickets()
    if not ticket_ids:
        return {"recipients": [], "total_tickets": 0, "total_clients": 0, "will_send": 0, "will_skip": 0, "not_found": 0}

    tickets = get_ticket_details(ticket_ids)
    grouped: Dict[str, List[Any]] = {}
    for t in tickets:
        cid = t.get("CustomerID", "UNKNOWN")
        if cid not in grouped:
            grouped[cid] = []
        grouped[cid].append(t)

    contacts: Dict[str, Any] = build_contact_cache()

    # Atualizar cache
    _cache["tickets"] = tickets
    _cache["grouped"] = grouped
    _cache["contacts"] = contacts
    _cache["last_refresh"] = datetime.now().isoformat()

    # Montar lista de destinatários
    recipients: List[Dict[str, Any]] = []
    will_send: int = int(0)
    will_skip: int = int(0)
    not_found: int = int(0)

    for cid, client_tickets in grouped.items():
        contact = contacts.get(cid)
        sent_today = already_sent_today(cid)
        
        tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)

        recipient = {
            "customer_id": cid,
            "tickets_count": len(tickets_to_remind),
            "tickets": [{"number": t.get("TicketNumber", ""), "title": t.get("Title", ""), "interaction_count": t.get("interaction_count", 0)} for t in tickets_to_remind],
            "escalated_count": len(tickets_to_escalate),
            "contact_found": contact is not None,
            "contact_name": contact["name"] if contact else None,
            "contact_id": contact["id"] if contact else None,
            "already_sent_today": sent_today,
        }

        if sent_today:
            recipient["status"] = "skip"
            will_skip = int(will_skip) + 1 # type: ignore
        elif not contact:
            recipient["status"] = "not_found"
            not_found = int(not_found) + 1 # type: ignore
        elif not tickets_to_remind:
            recipient["status"] = "escalated"
            will_skip = int(will_skip) + 1 # type: ignore
        else:
            recipient["status"] = "ready"
            will_send = int(will_send) + 1 # type: ignore

        recipients.append(recipient)

    # Ordenar: prontos primeiro, depois ignorados, depois não encontrados
    order = {"ready": 0, "skip": 1, "escalated": 2, "not_found": 3}
    recipients.sort(key=lambda r: order.get(r["status"], 9))

    return {
        "recipients": recipients,
        "total_tickets": len(tickets),
        "total_clients": len(grouped),
        "will_send": will_send,
        "will_skip": will_skip,
        "not_found": not_found,
        "refreshed_at": _cache["last_refresh"],
    }


@app.post("/api/send/{customer_id}")
async def api_send(customer_id: str):
    """Envia lembrete para um cliente específico."""
    with _send_lock:
        history_in_mem = load_history()
        # Verificar duplicidade
        if already_sent_today(customer_id, history_in_mem):
            raise HTTPException(
                status_code=409,
                detail=f"Lembrete já enviado para [{customer_id}] hoje."
            )

        # Verificar se temos dados no cache
        client_tickets = _cache["grouped"].get(customer_id)
        if not client_tickets:
            raise HTTPException(status_code=404, detail=f"Nenhum chamado para [{customer_id}]. Atualize os dados primeiro.")

        contact = _cache["contacts"].get(customer_id)
        if not contact:
            raise HTTPException(status_code=404, detail=f"Contato [{customer_id}] não encontrado no Digisac.")

        tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)
    
        today_str = datetime.now().strftime("%Y-%m-%d")  # BUG FIX: formato compatível com already_sent_today()
        escalated_records = []

        for t in tickets_to_escalate:
            try:
                tid = str(t.get("TicketID"))
                tn = str(t.get("TicketNumber"))
                owner = load_settings().get("escalation_owner", "jean.figueiredo@sagenetworks.com.br")
                if escalate_ticket(tid, owner):
                    add_escalation_entry({
                        "ticket_id": tid,
                        "ticket_number": tn,
                        "customer_id": customer_id,
                        "contact_name": contact["name"],
                        "timestamp": datetime.now().isoformat(),
                        "source": "manual_single"
                    })
            except Exception as e_esc:
                log(f"API SEND: [ERRO] Falha ao escalonar ticket {t.get('TicketNumber')}: {e_esc}")
            
        if not tickets_to_remind:
            raise HTTPException(
                status_code=400,
                detail=f"Não há chamados pendentes para lembrete (já foram escalonados)."
            )

        msg = build_message(contact["name"], tickets_to_remind)
        settings = load_settings()
        
        # Obter lista de contatos para envio
        contacts_to_send = contact.get("all_contacts", [contact]) if settings.get("multi_contact") else [contact]
        
        success = False
        for c in contacts_to_send:
            try:
                if settings.get("enable_whatsapp", True):
                    if send_whatsapp_message(c["id"], msg):
                        success = True
                else:
                    success = True # Simulamos sucesso se o envio estiver desabilitado explicitamente
                    log(f"API: Envio de WhatsApp desabilitado nas configurações para [{customer_id}] - {c.get('name')}")
            except Exception as e_send:
                log(f"API SEND: [ERRO] Falha ao enviar WhatsApp para {c.get('name')} [{customer_id}]: {e_send}")

        # Enviar para grupos do Digisac com o ID do cliente (se habilitado)
        if settings.get("enable_group_send", False):
            group_cache: Dict[str, Any] = _cache.get("groups") or {}
            client_groups = group_cache.get(customer_id, [])
            for grp in client_groups:
                try:
                    if settings.get("enable_whatsapp", True):
                        if send_whatsapp_message(str(grp["id"]), msg):
                            log(f"API: Mensagem enviada ao grupo '{grp['name']}' do cliente [{customer_id}].")
                    else:
                        log(f"API: Envio desabilitado (grupo '{grp['name']}' ignorado).")
                except Exception as e_grp:
                    log(f"API SEND: [ERRO] Falha ao enviar para grupo '{grp.get('name')}': {e_grp}")

        # Registrar no histórico apenas 1 entrada por cliente (agrupada)
        today_str = datetime.now().strftime("%Y-%m-%d")
        entry = {
            "customer_id": customer_id,
            "contact_name": contact["name"] + (f" (+{len(contacts_to_send)-1})" if len(contacts_to_send) > 1 else ""),
            "contact_id": contact["id"],
            "tickets_count": len(tickets_to_remind),
            "date": today_str,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "source": "manual",
        }
        history_in_mem.insert(0, entry)
        save_history(history_in_mem)

        if success:
            log(f"API: Lembrete processado para [{customer_id}] - {contact['name']}")
            # Registrar notas no Znuny
            for t in tickets_to_remind:
                tid_number = str(t.get("TicketNumber"))
                tid = str(t.get("TicketID"))
                
                # Só anota se a configuração permitir
                try:
                    if settings.get("enable_znuny_note", True):
                        note_success = add_znuny_note(tid, settings.get("note_template", ""))
                    else:
                        note_success = True # Simula sucesso para avançar a esteira
                except Exception as e_note:
                    log(f"API SEND: [ERRO] Falha ao adicionar nota Znuny no ticket {tid_number}: {e_note}")
                    
            return {"success": True, "customer_id": customer_id, "contact_name": contact["name"]}
        else:
            raise HTTPException(status_code=500, detail=f"Falha ao enviar para [{customer_id}]")


@app.post("/api/send-all")
async def api_send_all(background_tasks: BackgroundTasks):
    """
    Envia lembretes para todos os clientes pendentes.
    Inicia uma Background Task e retorna um task_id imediatamente.
    """
    task_id = str(uuid.uuid4())
    bg_tasks_status[task_id] = {
        "status": "processing", 
        "progress": 0, 
        "total": 0, 
        "results": {"sent": [], "skipped": [], "failed": [], "not_found": []}
    }
    background_tasks.add_task(process_send_all_bg, task_id)
    return {"message": "Envio em lote iniciado em background", "task_id": task_id}

@app.get("/api/send-all/status/{task_id}")
async def get_send_all_status(task_id: str):
    """
    Retorna o status atual da Background Task de envio.
    """
    if task_id not in bg_tasks_status:
        raise HTTPException(status_code=404, detail="Task not found")
    return bg_tasks_status[task_id]


def process_send_all_bg(task_id: str):
    log(f"API SEND-ALL [Task {task_id}]: Re-verificando chamados antes de enviar...")

    # Re-buscar dados atualizados
    tickets, grouped, contacts = refresh_data_sync()

    if not grouped:
        bg_tasks_status[task_id] = {"status": "completed", "progress": 0, "total": 0, "results": {"sent": [], "skipped": [], "failed": [], "not_found": []}}
        log("API SEND-ALL: Nenhum chamado pendente encontrado.")
        return

    total_customers = len(grouped)
    bg_tasks_status[task_id]["total"] = total_customers
    current_progress = 0

    with _send_lock:
        results: Dict[str, List[Any]] = {"sent": [], "skipped": [], "failed": [], "not_found": []}
        today_str = datetime.now().strftime("%Y-%m-%d")  # BUG FIX: formato compatível com already_sent_today()
        history_in_mem = load_history()
        
        all_escalated_records = []

        for customer_id, client_tickets in grouped.items():
            current_progress += 1
            bg_tasks_status[task_id]["progress"] = current_progress
            
            try:
                # Verificar duplicidade
                if already_sent_today(customer_id, history_in_mem):
                    results["skipped"].append({"customer_id": customer_id, "reason": "já enviado hoje"})
                    bg_tasks_status[task_id]["results"] = results
                    continue

                contact = contacts.get(customer_id)
                if not contact:
                    results["not_found"].append(customer_id)
                    continue
                    
                tickets_to_remind, tickets_to_escalate = filter_and_process_tickets(client_tickets)
                
                for t in tickets_to_escalate:
                    try:
                        tid = str(t.get("TicketID"))
                        tn = str(t.get("TicketNumber"))
                        owner = load_settings().get("escalation_owner", "jean.figueiredo@sagenetworks.com.br")
                        if escalate_ticket(tid, owner):
                            add_escalation_entry({
                                "ticket_id": tid,
                                "ticket_number": tn,
                                "customer_id": customer_id,
                                "contact_name": contact["name"],
                                "timestamp": datetime.now().isoformat(),
                                "source": "manual_all"
                            })
                    except Exception as e_esc:
                        log(f"API SEND-ALL: [ERRO] Falha ao escalonar ticket {t.get('TicketNumber')} do cliente [{customer_id}]: {e_esc}")
                    
                if not tickets_to_remind:
                    # pyre-ignore[16]
                    results["skipped"].append({"customer_id": customer_id, "reason": "escalados"})
                    continue

                contact_name = str(contact.get("name", ""))
                msg = build_message(contact_name, tickets_to_remind)
                settings = load_settings()
                
                contacts_to_send = contact.get("all_contacts", [contact]) if settings.get("multi_contact") else [contact]
                success = False
                
                for c in contacts_to_send:
                    try:
                        if settings.get("enable_whatsapp", True):
                            if send_whatsapp_message(str(c.get("id")), msg):
                                success = True
                        else:
                            success = True
                            log(f"API: Envio de WhatsApp desabilitado nas configurações para [{customer_id}] - {c.get('name')}")
                    except Exception as e_send:
                        log(f"API SEND-ALL: [ERRO] Falha ao enviar WhatsApp para contato {c.get('name')} [{customer_id}]: {e_send}")

                # Enviar para grupos do Digisac com o ID do cliente (se habilitado)
                if settings.get("enable_group_send", False):
                    group_cache_all: Dict[str, Any] = _cache.get("groups") or {}
                    client_groups_all = group_cache_all.get(customer_id, [])
                    for grp in client_groups_all:
                        try:
                            if settings.get("enable_whatsapp", True):
                                if send_whatsapp_message(str(grp["id"]), msg):
                                    log(f"API SEND-ALL: Mensagem enviada ao grupo '{grp['name']}' do cliente [{customer_id}].")
                            else:
                                log(f"API SEND-ALL: Envio desabilitado (grupo '{grp['name']}' ignorado).")
                        except Exception as e_grp:
                            log(f"API SEND-ALL: [ERRO] Falha ao enviar para grupo '{grp.get('name')}' [{customer_id}]: {e_grp}")

                entry = {
                    "customer_id": customer_id,
                    "contact_name": contact_name + (f" (+{len(contacts_to_send)-1})" if len(contacts_to_send) > 1 else ""),
                    "contact_id": str(contact.get("id")),
                    "tickets_count": len(tickets_to_remind),
                    "date": today_str,
                    "timestamp": datetime.now().isoformat(),
                    "success": success,
                    "source": "manual_all",
                }
                history_in_mem.insert(0, entry)
                save_history(history_in_mem)

                if success:
                    # pyre-ignore[16]
                    results["sent"].append({"customer_id": customer_id, "contact_name": contact["name"]})
                    # Registrar notas no Znuny
                    for t in tickets_to_remind:
                        tid_number = str(t.get("TicketNumber"))
                        tid = str(t.get("TicketID"))
                        
                        try:
                            if settings.get("enable_znuny_note", True):
                                note_success = add_znuny_note(tid, settings.get("note_template", ""))
                            else:
                                note_success = True
                        except Exception as e_note:
                            log(f"API SEND-ALL: [ERRO] Falha ao adicionar nota Znuny no ticket {tid_number}: {e_note}")
                else:
                    # pyre-ignore[16]
                    results["failed"].append(customer_id)

            except Exception as e_client:
                log(f"API SEND-ALL: [ERRO GERAL] Falha inesperada ao processar cliente [{customer_id}]: {e_client}")
                results["failed"].append(customer_id)

            bg_tasks_status[task_id]["results"] = results
            # Rate limit
            time.sleep(1)
        # Notas: all_escalated_records removido pois agora usamos add_escalation_entry diretamente no loop

    bg_tasks_status[task_id]["status"] = "completed"
    bg_tasks_status[task_id]["results"] = results
    log(f"API SEND-ALL [Task {task_id}]: Finalizado com sucesso.")


# ============================================================
# AGENDAMENTO
# ============================================================

@app.post("/api/schedule")
async def api_schedule(payload: dict):
    """
    Agenda envios únicos ou recorrentes.
    Body (único): { "type": "unico", "scheduled_for": "2026-02-22T09:00:00" }
    Body (recorrente): { "type": "recorrente", "weekdays": ["mon", "wed"], "time": "09:00" }
    """
    schedule_type = str(payload.get("type", "unico"))
    # Use split instead of slice to avoid indexing lint error or just wrap in str again
    schedule_id = str(uuid.uuid4()).split("-")[0]
    schedule_entry: Dict[str, Any] = {
        "id": schedule_id,
        "type": schedule_type,
        "created_at": datetime.now().isoformat(),
        "status": "pendente",
        "resultado": None,
        "executado_em": None,
    }

    if schedule_type == "unico":
        scheduled_for = payload.get("scheduled_for")
        if not scheduled_for:
            raise HTTPException(status_code=400, detail="'scheduled_for' é obrigatório")

        try:
            scheduled_dt = datetime.fromisoformat(scheduled_for)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use ISO: 2026-02-22T09:00:00")

        if scheduled_dt <= datetime.now():
            raise HTTPException(status_code=400, detail="A data/hora deve ser no futuro.")

        schedule_entry["scheduled_for"] = scheduled_dt.isoformat()

        scheduler.add_job(
            execute_scheduled_send,
            trigger=DateTrigger(run_date=scheduled_dt),
            id=schedule_id,
            args=[schedule_id],
            replace_existing=True,
        )
        msg_resp = f"Envio único agendado para {scheduled_dt.strftime('%d/%m/%Y às %H:%M')}"
        log(f"API: Agendamento único criado [{schedule_id}]")

    elif schedule_type == "recorrente":
        weekdays = payload.get("weekdays")
        time_str = str(payload.get("time")) # formato "HH:MM"
        
        if not weekdays or not isinstance(weekdays, list) or len(weekdays) == 0:
             raise HTTPException(status_code=400, detail="'weekdays' deve ser uma lista válida de dias")
        if not time_str or ":" not in time_str:
             raise HTTPException(status_code=400, detail="'time' é obrigatório no formato HH:MM")
             
        hour, minute = str(time_str).split(":")
        
        # Garante que weekdays seja uma lista iterável de strings
        safe_weekdays: List[str] = [str(w) for w in weekdays] if weekdays else []
        days_str = ",".join(safe_weekdays)
        
        schedule_entry["weekdays"] = safe_weekdays
        schedule_entry["time"] = time_str

        scheduler.add_job(
            execute_scheduled_send,
            trigger=CronTrigger(day_of_week=days_str, hour=hour, minute=minute),
            id=schedule_id,
            args=[schedule_id],
            replace_existing=True,
        )
        msg_resp = f"Envio recorrente agendado para dias: {', '.join(safe_weekdays)} às {time_str}"
        log(f"API: Agendamento recorrente criado [{schedule_id}]")

    else:
        raise HTTPException(status_code=400, detail="Tipo de agendamento inválido")

    # Salvar
    schedules = load_schedules()
    schedules.insert(0, schedule_entry)
    save_schedules(schedules)

    return {
        "success": True,
        "schedule": schedule_entry,
        "message": msg_resp,
    }


@app.get("/api/schedules")
async def api_schedules():
    """Retorna a lista de agendamentos."""
    schedules = load_schedules()
    return {"schedules": schedules, "total": len(schedules)}

@app.delete("/api/schedules/{schedule_id}")
async def api_cancel_schedule(schedule_id: str):
    """Cancela um agendamento pendente."""
    schedules = load_schedules()
    found = False
    
    for s in schedules:
        if s["id"] == schedule_id:
            s["status"] = "cancelado"
            s["executado_em"] = datetime.now().isoformat()
            found = True
            break
            
    if not found:
        raise HTTPException(status_code=404, detail=f"Agendamento [{schedule_id}] não encontrado.")
        
    save_schedules(schedules)
    
    # Remover do APScheduler
    try:
        scheduler.remove_job(schedule_id)
    except Exception:
        pass
        
    log(f"API: Agendamento [{schedule_id}] cancelado.")
    return {"success": True, "message": f"Agendamento [{schedule_id}] cancelado."}

@app.delete("/api/schedules/{schedule_id}/hard")
async def api_delete_schedule(schedule_id: str):
    """Apaga completamente um agendamento do banco."""
    schedules = load_schedules()
    new_schedules = [s for s in schedules if s["id"] != schedule_id]
    
    if len(schedules) == len(new_schedules):
        raise HTTPException(status_code=404, detail=f"Agendamento [{schedule_id}] não encontrado.")
        
    save_schedules(new_schedules)
    
    # Remover do APScheduler
    try:
        scheduler.remove_job(schedule_id)
    except Exception:
        pass
        
    log(f"API: Agendamento [{schedule_id}] apagado permanentemente.")
    return {"success": True, "message": f"Agendamento [{schedule_id}] apagado."}


# ============================================================
# HISTÓRICO
# ============================================================

@app.get("/api/reports")
async def api_reports():
    """Retorna os relatórios de execuções gerados."""
    reports = load_reports()
    return {"reports": reports, "total": len(reports)}


@app.get("/api/reports/escalations")
async def api_escalation_reports():
    """Retorna os registros de chamados escalonados gerados."""
    reports = load_escalation_reports()
    return {"reports": reports, "total": len(reports)}


@app.delete("/api/reports/escalations")
async def api_clear_escalation_reports():
    """Limpa o histórico de escalonados."""
    save_escalation_reports([])
    return {"message": "Histórico de escalonamentos limpo."}


@app.get("/api/history")
async def api_history():
    """Retorna histórico de envios."""
    history = load_history()
    return {"history": history, "total": len(history)}


@app.delete("/api/history")
async def api_clear_history():
    """Limpa o histórico de envios."""
    save_history([])
    return {"message": "Histórico limpo."}


# ============================================================
# FRONTEND ESTÁTICO
# ============================================================

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "Frontend não encontrado. Acesse /docs para a API."})


# ============================================================
# STARTUP / SHUTDOWN
# ============================================================

# on_event depreciado — substituído pelo lifespan acima


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Painel de Lembretes Znuny → Digisac  v2.0")
    print("  http://localhost:8000")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
