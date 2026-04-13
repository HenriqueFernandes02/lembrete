import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_data.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Interaction(Base):
    __tablename__ = "interactions"
    ticket_number = Column(String, primary_key=True, index=True)
    history_json = Column(Text, default="[]")  # Armazena lista de datas como JSON
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class History(Base):
    __tablename__ = "history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String, index=True)
    contact_name = Column(String)
    contact_id = Column(String)
    tickets_count = Column(Integer)
    date = Column(String, index=True)
    timestamp = Column(String)
    success = Column(Boolean)
    source = Column(String)
    schedule_id = Column(String, nullable=True)

class Report(Base):
    __tablename__ = "reports"
    id = Column(String, primary_key=True)
    timestamp = Column(String)
    source = Column(String)
    sent = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    not_found = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    total_processed = Column(Integer, default=0)

class Escalation(Base):
    __tablename__ = "escalations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String)
    ticket_number = Column(String, index=True)
    customer_id = Column(String)
    contact_name = Column(String)
    timestamp = Column(String)
    source = Column(String)

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(String, primary_key=True)
    type = Column(String)
    created_at = Column(String)
    status = Column(String)
    resultado = Column(Text, nullable=True)
    executado_em = Column(String, nullable=True)
    scheduled_for = Column(String, nullable=True)
    weekdays_json = Column(Text, nullable=True)
    time = Column(String, nullable=True)

class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value_json = Column(Text)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helpers estruturais para facilitar a transição do código legado

def load_db_legacy() -> Dict[str, Any]:
    with SessionLocal() as db:
        items = db.query(Interaction).all()
        return {item.ticket_number: json.loads(item.history_json) for item in items}

def save_db_legacy(data: Dict[str, Any]):
    with SessionLocal() as db:
        for ticket_number, history in data.items():
            existing = db.query(Interaction).filter(Interaction.ticket_number == ticket_number).first()
            if existing:
                existing.history_json = json.dumps(history)
            else:
                new_item = Interaction(ticket_number=ticket_number, history_json=json.dumps(history))
                db.add(new_item)
        db.commit()

def load_history_legacy() -> list:
    with SessionLocal() as db:
        items = db.query(History).order_by(History.id.desc()).all()
        return [{
            "customer_id": i.customer_id,
            "contact_name": i.contact_name,
            "contact_id": i.contact_id,
            "tickets_count": i.tickets_count,
            "date": i.date,
            "timestamp": i.timestamp,
            "success": i.success,
            "source": i.source,
            "schedule_id": i.schedule_id
        } for i in items]

def save_history_legacy(history: list):
    with SessionLocal() as db:
        db.query(History).delete()
        for i in reversed(history): # reverta para manter a ordem decrescente na insercao se history vem formatado assim
            db.add(History(**i))
        db.commit()

def add_history_entry(entry: dict):
    with SessionLocal() as db:
        new_entry = History(**entry)
        db.add(new_entry)
        db.commit()

def load_settings_legacy() -> Dict[str, Any]:
    with SessionLocal() as db:
        items = db.query(Setting).all()
        settings = {i.key: json.loads(i.value_json) for i in items}
    
    defaults = {
        "template": "Olá, {nome}. Há {quantidade} chamado(s) em aberto aguardando retorno...\n{lista_chamados}",
        "note_template": "Realizamos tentativa de contato {data} às {hora}.",
        "enable_whatsapp": True,
        "enable_znuny_note": True,
        "multi_contact": False,
        "enable_group_send": False,
        "escalation_owner": "jean.figueiredo",
        "blocked_contacts": ""
    }
    for k, v in defaults.items():
        if k not in settings:
            settings[k] = v
    return settings

def save_settings_legacy(settings: Dict[str, Any]):
    with SessionLocal() as db:
        for k, v in settings.items():
            existing = db.query(Setting).filter(Setting.key == k).first()
            if existing:
                existing.value_json = json.dumps(v)
            else:
                db.add(Setting(key=k, value_json=json.dumps(v)))
        db.commit()

def load_schedules_legacy() -> list:
    with SessionLocal() as db:
        items = db.query(Schedule).order_by(Schedule.created_at.desc()).all()
        return [{
            "id": i.id,
            "type": i.type,
            "created_at": i.created_at,
            "status": i.status,
            "resultado": i.resultado,
            "executado_em": i.executado_em,
            "scheduled_for": i.scheduled_for,
            "weekdays": json.loads(i.weekdays_json) if i.weekdays_json else None,
            "time": i.time
        } for i in items]

def save_schedules_legacy(schedules: list):
    with SessionLocal() as db:
        db.query(Schedule).delete()
        for s in schedules:
            db.add(Schedule(
                id=s["id"],
                type=s["type"],
                created_at=s.get("created_at"),
                status=s["status"],
                resultado=s.get("resultado"),
                executado_em=s.get("executado_em"),
                scheduled_for=s.get("scheduled_for"),
                weekdays_json=json.dumps(s.get("weekdays")) if s.get("weekdays") else None,
                time=s.get("time")
            ))
        db.commit()

def load_reports_legacy() -> list:
    with SessionLocal() as db:
        items = db.query(Report).order_by(Report.timestamp.desc()).all()
        return [{
            "id": i.id,
            "timestamp": i.timestamp,
            "source": i.source,
            "sent": i.sent,
            "skipped": i.skipped,
            "not_found": i.not_found,
            "failed": i.failed,
            "total_processed": i.total_processed
        } for i in items]

def add_report_legacy(report: dict):
    with SessionLocal() as db:
        db.add(Report(**report))
        db.commit()

def load_escalation_reports_legacy() -> list:
    with SessionLocal() as db:
        items = db.query(Escalation).order_by(Escalation.timestamp.desc()).all()
        return [{
            "ticket_id": i.ticket_id,
            "ticket_number": i.ticket_number,
            "customer_id": i.customer_id,
            "contact_name": i.contact_name,
            "timestamp": i.timestamp,
            "source": i.source
        } for i in items]

def save_escalation_reports_legacy(reports: list):
    with SessionLocal() as db:
        db.query(Escalation).delete()
        for r in reports:
            db.add(Escalation(**r))
        db.commit()

def add_escalation_entry(entry: dict):
    with SessionLocal() as db:
        new_entry = Escalation(**entry)
        db.add(new_entry)
        db.commit()
