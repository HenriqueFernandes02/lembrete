import json
from lembrete_pendente_automacao import get_pending_tickets, get_ticket_details

tickets = get_pending_tickets()
if tickets:
    t_id = tickets[0]
    print(f"Buscando ticket ID {t_id}")
    details = get_ticket_details([t_id])
    if details:
        print(json.dumps(details[0], indent=2))
else:
    print("Zero tickets")
