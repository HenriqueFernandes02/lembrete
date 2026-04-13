import os
import json
import shutil
from database import (
    save_db_legacy, save_history_legacy, save_settings_legacy,
    save_schedules_legacy, add_report_legacy, save_escalation_reports_legacy
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILES_TO_MIGRATE = {
    "interactions_db.json": save_db_legacy,
    "history.json": save_history_legacy,
    "settings.json": save_settings_legacy,
    "schedules.json": save_schedules_legacy,
    "escalation_reports.json": save_escalation_reports_legacy,
}

def migrate():
    print("Iniciando migração de JSON para SQLite...")
    
    for filename, save_func in FILES_TO_MIGRATE.items():
        filepath = os.path.join(BASE_DIR, filename)
        if os.path.exists(filepath):
            print(f"Migrando {filename}...")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                save_func(data)
                
                # Backup and remove
                backup_path = f"{filepath}.old"
                shutil.move(filepath, backup_path)
                print(f"  OK. Renomeado para {filename}.old")
            except Exception as e:
                print(f"  ERRO ao migrar {filename}: {e}")
        else:
            print(f"Arquivo {filename} não encontrado. Ignorando.")
            
    # Reports requires special handling due to `add_report_legacy` being row-by-row
    rep_path = os.path.join(BASE_DIR, "reports.json")
    if os.path.exists(rep_path):
        print(f"Migrando reports.json...")
        try:
            with open(rep_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # data is a list
            for r in data:
                add_report_legacy(r)
            shutil.move(rep_path, f"{rep_path}.old")
            print(f"  OK. Renomeado para reports.json.old")
        except Exception as e:
            print(f"  ERRO ao migrar reports.json: {e}")

    print("Migração concluída.")

if __name__ == "__main__":
    migrate()
