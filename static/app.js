/**
 * Lembretes Pendentes — Znuny → Digisac
 * Frontend App v2.0 (Vanilla JS)
 * 
 * Inclui: Confirmação visual, agendamento, re-verificação.
 */

const API = '';  // Mesmo host

// ============================================================
// STATE
// ============================================================

let state = {
    tickets: [],
    grouped: {},
    contacts: {},
    history: [],
    reports: [],
    schedules: [],
    settings: { template: '' },
    currentPreview: null,
    confirmPreviewData: null,
    activeTab: 'dashboard',
    searchClients: '',
    searchHistory: '',
    sentChart: null,
};

// ============================================================
// API CALLS
// ============================================================

async function apiGet(path) {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
}

async function apiPost(path, body = {}) {
    const res = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
}

async function apiDelete(path) {
    const res = await fetch(`${API}${path}`, { method: 'DELETE' });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Erro ${res.status}`);
    }
    return res.json();
}

// ============================================================
// CORE ACTIONS
// ============================================================

async function refreshAll() {
    const btn = document.getElementById('btn-refresh');
    btn.classList.add('loading');
    showLoading('Buscando chamados no Znuny...');

    try {
        // 1. Buscar tickets
        updateLoadingText('Etapa 1/4 — Buscando chamados pendentes no Znuny...');
        const ticketData = await apiGet('/api/tickets');
        state.tickets = ticketData.tickets;
        state.grouped = ticketData.grouped;

        document.getElementById('total-tickets').textContent = ticketData.total;
        document.getElementById('total-clients').textContent = ticketData.clients;

        state.interactions = ticketData.interactions || {};

        // 2. Buscar contatos Digisac
        updateLoadingText('Etapa 2/4 — Construindo cache de contatos do Digisac...');
        const contactData = await apiGet('/api/contacts/cache');
        state.contacts = contactData.contacts;

        // 3. Buscar histórico
        updateLoadingText('Etapa 3/5 — Carregando histórico de envios...');
        const historyData = await apiGet('/api/history');
        state.history = historyData.history;

        // 4. Buscar agendamentos
        updateLoadingText('Etapa 4/5 — Carregando agendamentos...');
        const scheduleData = await apiGet('/api/schedules');
        state.schedules = scheduleData.schedules;

        // 5. Buscar reletórios
        updateLoadingText('Etapa 5/5 — Carregando relatórios de execução...');
        const reportData = await apiGet('/api/reports');
        state.reports = reportData.reports;

        // Contagem de envios hoje
        const today = new Date().toISOString().split('T')[0];
        const sentToday = state.history.filter(h => h.date === today && h.success).length;
        document.getElementById('total-sent-today').textContent = sentToday;

        // Contagem de agendamentos pendentes
        const pendingSchedules = state.schedules.filter(s => s.status === 'pendente').length;
        document.getElementById('total-scheduled').textContent = pendingSchedules;

        // Status badges
        setBadge('badge-znuny', 'online');
        setBadge('badge-digisac', 'online');

        // Último update
        document.getElementById('last-update').textContent =
            `Atualizado: ${new Date().toLocaleTimeString('pt-BR')}`;

        // Habilitar botão "Enviar Todos"
        document.getElementById('btn-send-all').disabled = ticketData.clients === 0;

        // Renderizar
        renderClients();
        renderHistory();
        renderSchedules();
        renderReports();

        // Carregar Métricas e Configurações
        await loadMetrics();
        await loadSettings();

        hideLoading();
        showToast('success', `${ticketData.total} chamados de ${ticketData.clients} clientes carregados.`);
    } catch (err) {
        hideLoading();
        setBadge('badge-znuny', 'error');
        showToast('error', `Erro: ${err.message}`);
    }

    btn.classList.remove('loading');
}

// ============================================================
// RENDERING
// ============================================================

const COLORS = [
    'linear-gradient(135deg, #3b82f6, #2563eb)',
    'linear-gradient(135deg, #8b5cf6, #7c3aed)',
    'linear-gradient(135deg, #f59e0b, #d97706)',
    'linear-gradient(135deg, #ef4444, #dc2626)',
    'linear-gradient(135deg, #10b981, #059669)',
    'linear-gradient(135deg, #ec4899, #db2777)',
    'linear-gradient(135deg, #06b6d4, #0891b2)',
    'linear-gradient(135deg, #f97316, #ea580c)',
];

function getColor(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    return COLORS[Math.abs(hash) % COLORS.length];
}

function renderClients() {
    const grid = document.getElementById('clients-grid');
    const section = document.getElementById('tickets-section');
    const badge = document.getElementById('section-badge');

    const customerIds = Object.keys(state.grouped);

    if (customerIds.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    badge.textContent = `${customerIds.length} cliente${customerIds.length > 1 ? 's' : ''}`;

    // Sort by number of tickets (descending)
    customerIds.sort((a, b) => state.grouped[b].length - state.grouped[a].length);

    grid.innerHTML = customerIds
        .filter(cid => {
            const contact = state.contacts[cid];
            const search = state.searchClients.toUpperCase();
            if (!search) return true;
            return cid.toUpperCase().includes(search) ||
                (contact && contact.name.toUpperCase().includes(search)) ||
                (contact && contact.internalName && contact.internalName.toUpperCase().includes(search));
        })
        .map(cid => {
            const tickets = state.grouped[cid];
            const contact = state.contacts[cid];
            const contactName = contact ? contact.name : `Desconhecido`;
            const initials = cid.substring(0, 2).toUpperCase();

            // Check if already sent today
            const today = new Date().toISOString().split('T')[0];
            const alreadySent = state.history.some(h => h.customer_id === cid && h.date === today && h.success);

            const contactStatusHtml = contact
                ? `<span class="contact-status found">✓ ${escapeHtml(contact.name)}</span>`
                : `<span class="contact-status not-found">✗ Contato não encontrado</span>`;

            const ticketRows = tickets.map(t => {
                const tNum = String(t.TicketNumber);
                const count = t.interaction_count || 0;
                const badgeHtml = count > 0 ? `<span class="badge-interaction">${count} envios</span>` : '<span class="badge-interaction empty">0 envios</span>';

                return `
            <div class="ticket-row">
                <div style="display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 0;">
                    <span class="ticket-number">#${escapeHtml(tNum)}</span>
                    <span class="ticket-title">${escapeHtml(t.Title || 'Sem título')}</span>
                </div>
                ${badgeHtml}
            </div>
            `;
            }).join('');

            return `
            <div class="client-card" data-cid="${escapeHtml(cid)}">
                <div class="client-card-header">
                    <div class="client-info">
                        <div class="client-avatar" style="background: ${getColor(cid)}">
                            ${initials}
                        </div>
                        <div>
                            <div class="client-name">${escapeHtml(contactName)}</div>
                            <div class="client-id">[${escapeHtml(cid)}] · ${tickets.length} chamado${tickets.length > 1 ? 's' : ''}</div>
                        </div>
                    </div>
                    <div class="client-actions">
                        <button class="btn-icon" onclick="previewMessage('${escapeHtml(cid)}')" title="Preview da mensagem">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                                <circle cx="12" cy="12" r="3"/>
                            </svg>
                        </button>
                        <button class="btn-icon ${alreadySent ? 'sent' : ''}" onclick="sendSingle('${escapeHtml(cid)}')" title="${alreadySent ? 'Já enviado hoje' : 'Enviar lembrete'}" ${!contact ? 'disabled' : ''}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                ${alreadySent
                    ? '<polyline points="20 6 9 17 4 12"/>'
                    : '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'
                }
                            </svg>
                        </button>
                    </div>
                </div>
                <div class="client-card-body">
                    ${ticketRows}
                </div>
                <div class="client-footer">
                    ${contactStatusHtml}
                </div>
            </div>
        `;
        }).join('');
}

function renderHistory() {
    const list = document.getElementById('history-list');

    if (state.history.length === 0) {
        list.innerHTML = '<p class="empty-state">Nenhum envio registrado.</p>';
        return;
    }

    list.innerHTML = [...state.history].reverse()
        .filter(h => {
            const search = state.searchHistory.toUpperCase();
            if (!search) return true;
            return h.customer_id.toUpperCase().includes(search) ||
                (h.contact_name && h.contact_name.toUpperCase().includes(search));
        })
        .slice(0, 50).map(h => {
            const icon = h.success ? '✓' : '✗';
            const iconClass = h.success ? 'success' : 'fail';
            const time = new Date(h.timestamp).toLocaleString('pt-BR');
            const sourceLabel = h.source === 'agendamento' ? '⏰' : h.source === 'manual_all' ? '📨' : '✉️';

            return `
            <div class="history-item">
                <div class="history-left">
                    <div class="history-icon ${iconClass}">${icon}</div>
                    <div>
                        <div class="history-name">${escapeHtml(h.contact_name || h.customer_id)}</div>
                        <div class="history-meta">[${escapeHtml(h.customer_id)}] · ${h.tickets_count} chamado${h.tickets_count > 1 ? 's' : ''} ${sourceLabel}</div>
                    </div>
                </div>
                <div class="history-right">
                    <div class="history-time">${time}</div>
                </div>
            </div>
        `;
        }).join('');
}

function renderSchedules() {
    const list = document.getElementById('schedules-list');
    const badge = document.getElementById('schedules-badge');

    if (state.schedules.length === 0) {
        list.innerHTML = '<p class="empty-state">Nenhum agendamento registrado.</p>';
        badge.textContent = '0 agendamentos';
        return;
    }

    const pending = state.schedules.filter(s => s.status === 'pendente').length;
    badge.textContent = `${pending} pendente${pending !== 1 ? 's' : ''}`;

    list.innerHTML = state.schedules.map(s => {
        let scheduledForDisplay = '';
        if (s.type === 'recorrente') {
            const dayMap = { 'mon': 'Seg', 'tue': 'Ter', 'wed': 'Qua', 'thu': 'Qui', 'fri': 'Sex', 'sat': 'Sáb', 'sun': 'Dom' };
            const days = (s.weekdays || []).map(d => dayMap[d] || d).join(', ');
            scheduledForDisplay = `Toda(o) ${days} às ${s.time}`;
        } else {
            scheduledForDisplay = s.scheduled_for ? new Date(s.scheduled_for).toLocaleString('pt-BR') : 'Data não definida';
        }
        const createdAt = new Date(s.created_at).toLocaleString('pt-BR');

        const statusMap = {
            'pendente': { icon: '⏳', label: 'Pendente', cls: 'pending' },
            'executando': { icon: '🔄', label: 'Executando...', cls: 'running' },
            'concluido': { icon: '✅', label: 'Concluído', cls: 'done' },
            'cancelado': { icon: '❌', label: 'Cancelado', cls: 'cancelled' },
            'atrasado_executando': { icon: '⚡', label: 'Exec. Atrasada', cls: 'running' },
        };

        const st = statusMap[s.status] || { icon: '❓', label: s.status, cls: '' };

        return `
            <div class="schedule-item ${st.cls}">
                <div class="schedule-left">
                    <div class="schedule-icon">${st.icon}</div>
                    <div>
                        <div class="schedule-datetime">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
                                <line x1="16" y1="2" x2="16" y2="6"/>
                                <line x1="8" y1="2" x2="8" y2="6"/>
                                <line x1="3" y1="10" x2="21" y2="10"/>
                            </svg>
                            ${scheduledForDisplay}
                        </div>
                        <div class="schedule-meta">
                            Criado em ${createdAt} · ID: ${escapeHtml(s.id)}
                        </div>
                        ${s.resultado ? `<div class="schedule-result">${escapeHtml(s.resultado)}</div>` : ''}
                    </div>
                </div>
                <div class="schedule-right">
                    <span class="schedule-status ${st.cls}">${st.label}</span>
                    <div style="display: flex; gap: 0.5rem; margin-top: 5px;">
                        ${s.status === 'pendente' ? `
                            <button class="btn-icon cancel-btn" onclick="cancelSchedule('${escapeHtml(s.id)}')" title="Cancelar agendamento">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="18" y1="6" x2="6" y2="18"/>
                                    <line x1="6" y1="6" x2="18" y2="18"/>
                                </svg>
                            </button>
                        ` : ''}
                        <button class="btn-icon cancel-btn" style="color: var(--accent-red);" onclick="deleteSchedule('${escapeHtml(s.id)}')" title="Apagar permanentemente">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function deleteSchedule(scheduleId) {
    if (!confirm('Deseja apagar permanentemente este agendamento? Ele não poderá ser recuperado.')) return;
    try {
        await apiDelete(`/api/schedules/${scheduleId}/hard`);
        showToast('info', 'Agendamento apagado com sucesso.');

        const data = await apiGet('/api/schedules');
        state.schedules = data.schedules;
        renderSchedules();

        const pendingSchedules = state.schedules.filter(s => s.status === 'pendente').length;
        document.getElementById('total-scheduled').textContent = pendingSchedules;
    } catch (err) {
        showToast('error', `Erro: ${err.message}`);
    }
}

// ============================================================
// CONFIRMATION MODAL (Enviar Todos)
// ============================================================

async function showConfirmationModal() {
    const overlay = document.getElementById('confirm-overlay');
    const loading = document.getElementById('confirm-loading');
    const list = document.getElementById('confirm-recipients-list');
    const sendBtn = document.getElementById('btn-confirm-send');

    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    loading.style.display = 'flex';
    list.innerHTML = '';
    sendBtn.disabled = true;

    try {
        // Buscar preview com re-verificação
        const data = await apiPost('/api/send-all/preview');
        state.confirmPreviewData = data;

        loading.style.display = 'none';

        // Atualizar contadores
        document.getElementById('confirm-will-send').textContent = data.will_send;
        document.getElementById('confirm-will-skip').textContent = data.will_skip;
        document.getElementById('confirm-not-found').textContent = data.not_found;

        // Atualizar dados do cache local também
        document.getElementById('total-tickets').textContent = data.total_tickets;
        document.getElementById('total-clients').textContent = data.total_clients;
        document.getElementById('last-update').textContent =
            `Atualizado: ${new Date().toLocaleTimeString('pt-BR')}`;

        // Renderizar lista de destinatários
        if (data.recipients.length === 0) {
            list.innerHTML = '<p class="empty-state">Nenhum chamado pendente encontrado.</p>';
        } else {
            list.innerHTML = data.recipients.map(r => {
                const statusIcons = {
                    'ready': '✅',
                    'skip': '⏩',
                    'not_found': '❌',
                    'escalated': '⏭️',
                };
                const statusLabels = {
                    'ready': 'Pronto',
                    'skip': 'Já enviado',
                    'not_found': 'Sem contato',
                    'escalated': 'Escalonado',
                };
                const statusClasses = {
                    'ready': 'recipient-ready',
                    'skip': 'recipient-skip',
                    'not_found': 'recipient-not-found',
                    'escalated': 'recipient-skip',
                };

                const ticketsList = r.tickets.map(t =>
                    `<span class="recipient-ticket">#${escapeHtml(t.number)} <span class="interaction-badge" title="Interações já feitas">${t.interaction_count || 0}x</span></span>`
                ).join(' ');

                return `
                    <div class="recipient-row ${statusClasses[r.status] || ''}">
                        <div class="recipient-info">
                            <span class="recipient-status-icon">${statusIcons[r.status] || '❓'}</span>
                            <div>
                                <div class="recipient-name">
                                    ${r.contact_name ? escapeHtml(r.contact_name) : `[${escapeHtml(r.customer_id)}]`}
                                </div>
                                <div class="recipient-details">
                                    [${escapeHtml(r.customer_id)}] · ${r.tickets_count} p/ lembrar${r.escalated_count > 0 ? ` · ${r.escalated_count} escalonado(s)` : ''}
                                </div>
                                <div class="recipient-tickets">${ticketsList}</div>
                            </div>
                        </div>
                        <div class="recipient-badge ${r.status}">${statusLabels[r.status]}</div>
                    </div>
                `;
            }).join('');
        }

        sendBtn.disabled = data.will_send === 0;

    } catch (err) {
        loading.style.display = 'none';
        list.innerHTML = `<p class="empty-state" style="color: var(--accent-red)">Erro: ${escapeHtml(err.message)}</p>`;
    }
}

function closeConfirmModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('confirm-overlay').style.display = 'none';
    document.body.style.overflow = '';
    state.confirmPreviewData = null;
}

async function confirmSendAll() {
    closeConfirmModal();

    const btn = document.getElementById('btn-send-all');
    btn.classList.add('loading');
    btn.disabled = true;

    const originalHTML = btn.innerHTML;
    try {
        showToast('info', 'Iniciando envio em lote (Isso pode demorar)...');
        const startResult = await apiPost('/api/send-all');
        const taskId = startResult.task_id;

        let statusData = { status: 'processing' };

        while (statusData.status === 'processing') {
            await new Promise(r => setTimeout(r, 2000));
            try {
                statusData = await apiGet(`/api/send-all/status/${taskId}`);
                if (statusData.total > 0) {
                    btn.innerHTML = `Enviando... ${statusData.progress || 0}/${statusData.total}`;
                } else {
                    btn.innerHTML = `Preparando Envios...`;
                }
            } catch (pollErr) {
                console.warn("Polling error:", pollErr);
            }
        }

        const res = statusData.results || { sent: [], skipped: [], failed: [], not_found: [] };
        let msg = `Concluído! `;
        if (res.sent.length) msg += `✓ ${res.sent.length} enviado(s). `;
        if (res.skipped.length) msg += `⏩ ${res.skipped.length} ignorado(s). `;
        if (res.not_found.length) msg += `❌ ${res.not_found.length} não encontrado(s). `;
        if (res.failed.length) msg += `⚠️ ${res.failed.length} falha(s). `;

        showToast('success', msg);

        // Refresh data
        await refreshPostSend();
    } catch (err) {
        showToast('error', `Erro no envio em lote: ${err.message}`);
    }

    btn.classList.remove('loading');
    btn.innerHTML = originalHTML;
    btn.disabled = false;
}

// ============================================================
// SCHEDULE MODAL
// ============================================================

function openScheduleModal() {
    closeConfirmModal();

    const overlay = document.getElementById('schedule-overlay');
    overlay.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    // Set default date to tomorrow
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    document.getElementById('schedule-date').value = tomorrow.toISOString().split('T')[0];
    document.getElementById('schedule-time').value = '09:00';

    // Reset radios e checkboxes
    document.querySelector('input[name="schedule-type"][value="unico"]').checked = true;
    toggleScheduleType();

    const checkboxes = document.querySelectorAll('input[name="weekday"]');
    checkboxes.forEach(cb => cb.checked = false);

    updateSchedulePreview();
}

function toggleScheduleType() {
    const type = document.querySelector('input[name="schedule-type"]:checked').value;
    const groupDate = document.getElementById('group-date');
    const groupWeekdays = document.getElementById('group-weekdays');

    if (type === 'unico') {
        groupDate.style.display = 'block';
        groupWeekdays.style.display = 'none';
    } else {
        groupDate.style.display = 'none';
        groupWeekdays.style.display = 'block';
    }

    updateSchedulePreview();
}

function closeScheduleModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('schedule-overlay').style.display = 'none';
    document.body.style.overflow = '';
}

function updateSchedulePreview() {
    const dateVal = document.getElementById('schedule-date').value;
    const timeVal = document.getElementById('schedule-time').value;
    const preview = document.getElementById('schedule-preview');

    if (dateVal && timeVal) {
        const dt = new Date(`${dateVal}T${timeVal}`);
        const dayNames = ['Domingo', 'Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado'];
        const dayName = dayNames[dt.getDay()];
        const formatted = dt.toLocaleString('pt-BR', {
            day: '2-digit', month: 'long', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
        });
        preview.innerHTML = `
            <div class="schedule-preview-content">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
                <span>${dayName}, ${formatted}</span>
            </div>
        `;
    }
}

// Add event listeners for schedule inputs
document.addEventListener('DOMContentLoaded', () => {
    const dateInput = document.getElementById('schedule-date');
    const timeInput = document.getElementById('schedule-time');
    const typeInputs = document.querySelectorAll('input[name="schedule-type"]');
    const weekdayInputs = document.querySelectorAll('input[name="weekday"]');

    if (dateInput) dateInput.addEventListener('change', updateSchedulePreview);
    if (timeInput) timeInput.addEventListener('change', updateSchedulePreview);
    typeInputs.forEach(i => i.addEventListener('change', updateSchedulePreview));
    weekdayInputs.forEach(i => i.addEventListener('change', updateSchedulePreview));
});

async function confirmSchedule() {
    const type = document.querySelector('input[name="schedule-type"]:checked').value;
    const timeVal = document.getElementById('schedule-time').value;

    if (!timeVal) {
        showToast('error', 'Selecione a hora para o agendamento.');
        return;
    }

    let payload = { type: type, time: timeVal };

    if (type === 'unico') {
        const dateVal = document.getElementById('schedule-date').value;
        if (!dateVal) {
            showToast('error', 'Selecione uma data para o agendamento único.');
            return;
        }
        const scheduledFor = `${dateVal}T${timeVal}:00`;
        const scheduledDt = new Date(scheduledFor);

        if (scheduledDt <= new Date()) {
            showToast('error', 'A data/hora deve ser no futuro.');
            return;
        }
        payload.scheduled_for = scheduledFor;

    } else {
        const checkboxes = document.querySelectorAll('input[name="weekday"]:checked');
        const weekdays = Array.from(checkboxes).map(cb => cb.value);

        if (weekdays.length === 0) {
            showToast('error', 'Selecione pelo menos um dia da semana.');
            return;
        }
        payload.weekdays = weekdays;
    }

    try {
        const result = await apiPost('/api/schedule', payload);
        closeScheduleModal();
        showToast('success', result.message);

        // Refresh schedules
        const scheduleData = await apiGet('/api/schedules');
        state.schedules = scheduleData.schedules;
        renderSchedules();

        const pendingSchedules = state.schedules.filter(s => s.status === 'pendente').length;
        document.getElementById('total-scheduled').textContent = pendingSchedules;
    } catch (err) {
        showToast('error', `Erro ao agendar: ${err.message}`);
    }
}

// ============================================================
// SCHEDULES SECTION
// ============================================================

// Navegação para aba de agendamentos feita via switchTab('schedules')

async function refreshSchedules() {
    try {
        const data = await apiGet('/api/schedules');
        state.schedules = data.schedules;
        renderSchedules();
    } catch (err) {
        showToast('error', `Erro ao carregar agendamentos: ${err.message}`);
    }
}

async function cancelSchedule(scheduleId) {
    if (!confirm('Cancelar este agendamento?')) return;

    try {
        await apiDelete(`/api/schedules/${scheduleId}`);
        showToast('info', 'Agendamento cancelado.');

        const data = await apiGet('/api/schedules');
        state.schedules = data.schedules;
        renderSchedules();

        const pendingSchedules = state.schedules.filter(s => s.status === 'pendente').length;
        document.getElementById('total-scheduled').textContent = pendingSchedules;
    } catch (err) {
        showToast('error', `Erro: ${err.message}`);
    }
}

// ============================================================
// REPORTS SECTION
// ============================================================

// Navegação para aba de relatórios feita via switchTab('reports')

async function refreshReports() {
    try {
        const data = await apiGet('/api/reports');
        state.reports = data.reports;
        renderReports();
    } catch (err) {
        showToast('error', `Erro ao carregar relatórios: ${err.message}`);
    }
}

function renderReports() {
    const list = document.getElementById('reports-list');

    if (state.reports.length === 0) {
        list.innerHTML = '<p class="empty-state" style="margin-top:20px;">Nenhum relatório de execução consolidada registrado ainda.</p>';
        return;
    }

    list.innerHTML = state.reports.map(r => {
        const time = new Date(r.timestamp).toLocaleString('pt-BR');

        return `
            <div class="history-item">
                <div class="history-left">
                    <div class="history-icon" style="background: rgba(59, 130, 246, 0.12); color: var(--accent-blue);">📊</div>
                    <div>
                        <div class="history-name">Relatório: ${time}</div>
                        <div class="history-meta">Fonte: ${escapeHtml(r.source)} · Total Processado: ${r.total_processed}</div>
                        <div style="font-size:0.75rem; margin-top:5px; color:var(--text-secondary)">
                            <span style="color:var(--accent-green)">Enviados: ${r.sent}</span> | 
                            <span>Skipped: ${r.skipped}</span> | 
                            <span style="color:var(--accent-amber)">Sem Contato: ${r.not_found}</span> | 
                            <span style="color:var(--accent-red)">Falhas: ${r.failed}</span> 
                        </div>
                    </div>
                </div>
                <div class="history-right">
                    <button class="btn btn-ghost btn-sm" onclick="downloadReport('${r.id}')">Baixar TXT</button>
                </div>
            </div>
        `;
    }).join('');
}

function downloadReport(reportId) {
    const report = state.reports.find(r => r.id === reportId);
    if (!report) return;

    // Geração do arquivo texto em memória
    let content = `========================================================\n`;
    content += `RELATÓRIO DE EXECUÇÃO DE LEMBRETES - ZNUNY/DIGISAC\n`;
    content += `========================================================\n\n`;
    content += `Data/Hora: ${new Date(report.timestamp).toLocaleString('pt-BR')}\n`;
    content += `Origem: ${report.source}\n`;
    content += `\n--- RESUMO ---\n`;
    content += `Total Encontrado/Processado: ${report.total_processed}\n`;
    content += `Enviados com Sucesso: ${report.sent}\n`;
    content += `Ignorados (Já enviados): ${report.skipped}\n`;
    content += `Contatos não encontrados: ${report.not_found}\n`;
    content += `Falhas de Envio: ${report.failed}\n\n`;
    content += `Este arquivo é um registro para auditoria gerado pelo painel.\n`;

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `relatorio_lembretes_${reportId}_${new Date(report.timestamp).toISOString().split('T')[0]}.txt`;
    a.click();
    window.URL.revokeObjectURL(url);
}

async function downloadEscalationReportCSV() {
    try {
        showToast('info', 'Gerando relatório de escalonados, aguarde...');
        const response = await apiGet('/api/reports/escalations');

        if (!response || !response.reports || response.reports.length === 0) {
            showToast('warning', 'Ainda não há chamados escalonados.');
            return;
        }

        // CSV Header
        let csvContent = "Ticket ID,Numero do Chamado,ID do Cliente Digisac,Nome do Cliente,Data,Origem\n";

        // Loop records
        response.reports.forEach(r => {
            const ticketId = `"${r.ticket_id || ''}"`;
            const ticketNumber = `"${r.ticket_number || ''}"`;
            const customerId = `"${r.customer_id || ''}"`;
            const contactName = `"${(r.contact_name || '').replace(/"/g, '""')}"`;
            const timestamp = `"${r.timestamp || ''}"`;
            const source = `"${r.source || ''}"`;

            csvContent += `${ticketId},${ticketNumber},${customerId},${contactName},${timestamp},${source}\n`;
        });

        const blob = new Blob(["\uFEFF" + csvContent], { type: 'text/csv;charset=utf-8' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `relatorio_escalonados_z_d_${new Date().toISOString().split('T')[0]}.csv`;
        a.click();
        window.URL.revokeObjectURL(url);

        showToast('success', 'Relatório de escalonados baixado com sucesso!');
    } catch (err) {
        showToast('error', `Erro ao buscar escalonados: ${err.message}`);
    }
}

// ============================================================
// PREVIEW & SEND (Individual)
// ============================================================

async function previewMessage(customerId) {
    try {
        const data = await apiPost('/api/preview', { customer_id: customerId });
        state.currentPreview = customerId;

        const contactInfo = document.getElementById('modal-contact-info');
        const messageDiv = document.getElementById('modal-message');
        const warning = document.getElementById('modal-warning');
        const sendBtn = document.getElementById('modal-send-btn');

        if (data.contact) {
            contactInfo.innerHTML = `
                <strong>Contato:</strong> ${escapeHtml(data.contact.name)}<br>
                <strong>ID:</strong> ${escapeHtml(data.contact.id)}<br>
                <strong>Chamados p/ Lembrar:</strong> ${data.tickets_count}<br>
                <strong>Chamados Escalonados:</strong> ${data.escalated_count}
            `;
        } else {
            contactInfo.innerHTML = `<strong>Cliente:</strong> [${escapeHtml(customerId)}] — Contato não encontrado no Digisac`;
        }

        messageDiv.textContent = data.message_preview;

        if (data.already_sent_today) {
            warning.textContent = "Lembrete já enviado hoje.";
            warning.style.display = 'block';
            sendBtn.disabled = true;
        } else if (data.tickets_count === 0) {
            warning.textContent = "Todos os chamados já atingiram o limite e foram escalonados.";
            warning.style.display = 'block';
            sendBtn.disabled = true;
        } else {
            warning.style.display = 'none';
            sendBtn.disabled = !data.contact;
        }

        openModal();
    } catch (err) {
        showToast('error', `Erro ao gerar preview: ${err.message}`);
    }
}

async function sendFromModal() {
    if (!state.currentPreview) return;
    closeModal();
    await sendSingle(state.currentPreview);
}

async function sendSingle(customerId) {
    try {
        showToast('info', `Enviando lembrete para [${customerId}]...`);
        const data = await apiPost(`/api/send/${customerId}`);
        showToast('success', `✓ Lembrete enviado para ${data.contact_name}`);

        await refreshPostSend();
    } catch (err) {
        showToast('error', `Falha: ${err.message}`);
    }
}

async function refreshPostSend() {
    // Refresh history and counts
    const historyData = await apiGet('/api/history');
    state.history = historyData.history;

    const today = new Date().toISOString().split('T')[0];
    const sentToday = state.history.filter(h => h.date === today && h.success).length;
    document.getElementById('total-sent-today').textContent = sentToday;

    renderClients();
    renderHistory();
}

// ============================================================
// HISTORY
// ============================================================

// Navegação para aba de histórico feita via switchTab('history')

async function clearHistory() {
    if (!confirm('Limpar todo o histórico de envios?')) return;
    try {
        await apiDelete('/api/history');
        state.history = [];
        document.getElementById('total-sent-today').textContent = '0';
        renderHistory();
        renderClients();
        showToast('info', 'Histórico limpo.');
    } catch (err) {
        showToast('error', `Erro: ${err.message}`);
    }
}

// ============================================================
// MODAL (individual preview)
// ============================================================

function openModal() {
    document.getElementById('modal-overlay').style.display = 'flex';
    document.body.style.overflow = 'hidden';
}

function closeModal(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('modal-overlay').style.display = 'none';
    document.body.style.overflow = '';
    state.currentPreview = null;
}

// ESC to close any modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal();
        closeConfirmModal();
        closeScheduleModal();
    }
});

// ============================================================
// UI HELPERS
// ============================================================

function setBadge(id, status) {
    const el = document.getElementById(id);
    el.className = `badge ${status}`;
}

function showLoading(text) {
    const el = document.getElementById('loading');
    el.style.display = 'flex';
    document.getElementById('loading-text').textContent = text || 'Carregando dados...';
    document.getElementById('tickets-section').style.display = 'none';
}

function updateLoadingText(text) {
    document.getElementById('loading-text').textContent = text;
}

function hideLoading() {
    document.getElementById('loading').style.display = 'none';
}

function showToast(type, message) {
    const container = document.getElementById('toast-container');
    const icons = { success: '✅', error: '❌', info: 'ℹ️' };

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <span>${escapeHtml(message)}</span>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ============================================================
// PHASE 2: TABS & NAVIGATION
// ============================================================

function switchTab(tabId) {
    state.activeTab = tabId;

    // Update nav buttons
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    // Show/hide tab contents
    document.querySelectorAll('.tab-content').forEach(section => {
        section.style.display = section.id === `tab-${tabId}` ? 'block' : 'none';
    });

    // Specific tab loads
    if (tabId === 'dashboard') loadMetrics();
    if (tabId === 'settings') loadSettings();
    if (tabId === 'clients') renderClients();
    if (tabId === 'history') renderHistory();
    if (tabId === 'schedules') renderSchedules();
}

// ============================================================
// PHASE 2: FILTERS
// ============================================================

function filterClients() {
    state.searchClients = document.getElementById('search-clients').value;
    renderClients();
}

function filterHistory() {
    state.searchHistory = document.getElementById('search-history').value;
    renderHistory();
}

// ============================================================
// PHASE 2: METRICS & CHART
// ============================================================

async function loadMetrics() {
    try {
        const data = await apiGet('/api/metrics');
        document.getElementById('metric-escalated-week').textContent = data.total_escalated_week;

        renderChart(data.labels, Object.values(data.daily_sent));
    } catch (err) {
        console.error('Erro ao carregar métricas:', err);
    }
}

function renderChart(labels, values) {
    const ctx = document.getElementById('sentChart').getContext('2d');

    if (state.sentChart) {
        state.sentChart.destroy();
    }

    state.sentChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Lembretes Enviados',
                data: values,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: 4,
                pointBackgroundColor: '#3b82f6'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });
}

// ============================================================
// PHASE 2: SETTINGS
// ============================================================

async function loadSettings() {
    try {
        const settings = await apiGet('/api/settings');
        state.settings = settings;
        const textarea = document.getElementById('template-text');
        if (textarea) textarea.value = settings.template || '';

        const noteTextarea = document.getElementById('note-template-text');
        if (noteTextarea) noteTextarea.value = settings.note_template || '';

        const tWpp = document.getElementById('toggle-whatsapp');
        if (tWpp) tWpp.checked = settings.enable_whatsapp !== false;

        const tZnuny = document.getElementById('toggle-znuny');
        if (tZnuny) tZnuny.checked = settings.enable_znuny_note !== false;

        const tMulti = document.getElementById('toggle-multi');
        if (tMulti) tMulti.checked = settings.multi_contact === true;

        const tGroupSend = document.getElementById('toggle-group-send');
        if (tGroupSend) tGroupSend.checked = settings.enable_group_send === true;

        const ownerInput = document.getElementById('escalation-owner');
        if (ownerInput) ownerInput.value = settings.escalation_owner || 'jean.figueiredo';

        const blockedInput = document.getElementById('blocked-contacts');
        if (blockedInput) blockedInput.value = settings.blocked_contacts || '';
    } catch (err) {
        showToast('error', 'Erro ao carregar configurações.');
    }
}

async function saveSettings() {
    const template = document.getElementById('template-text').value;
    const note_template = document.getElementById('note-template-text').value;

    const enable_whatsapp = document.getElementById('toggle-whatsapp').checked;
    const enable_znuny_note = document.getElementById('toggle-znuny').checked;
    const multi_contact = document.getElementById('toggle-multi').checked;
    const enable_group_send = document.getElementById('toggle-group-send')
        ? document.getElementById('toggle-group-send').checked
        : false;

    const escalation_owner = document.getElementById('escalation-owner')
        ? document.getElementById('escalation-owner').value
        : 'jean.figueiredo';

    const blocked_contacts = document.getElementById('blocked-contacts')
        ? document.getElementById('blocked-contacts').value
        : '';

    const payload = {
        template,
        note_template,
        enable_whatsapp,
        enable_znuny_note,
        multi_contact,
        enable_group_send,
        escalation_owner,
        blocked_contacts,
    };

    try {
        await apiPost('/api/settings', payload);
        state.settings = { ...state.settings, ...payload };
        showToast('success', 'Configurações salvas com sucesso!');
    } catch (err) {
        showToast('error', 'Erro ao salvar configurações.');
    }
}

// ============================================================
// INIT
// ============================================================

(async function init() {
    // Tab Listeners
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    try {
        // Inicializar com refresh completo
        refreshAll();

        const status = await apiGet('/api/status');
        document.getElementById('last-update').textContent =
            status.last_refresh
                ? `Último: ${new Date(status.last_refresh).toLocaleTimeString('pt-BR')}`
                : 'Clique em "Atualizar Dados"';
    } catch {
        document.getElementById('last-update').textContent = 'Servidor offline';
    }
})();
