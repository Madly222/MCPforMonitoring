/**
 * Main Application Handler
 */

let currentUser = null;
let refreshInterval = null;

/**
 * Custom Dialog System to replace window.alert, window.confirm, and window.prompt.
 * All methods return Promises. You MUST use 'await' when calling them.
 */
const Dialog = {
    overlay: null,
    title: null,
    message: null,
    input: null,
    footer: null,
    closeBtn: null,
    resolvePromise: null,

    init() {
        this.overlay = document.getElementById('customDialogOverlay');
        this.title = document.getElementById('customDialogTitle');
        this.message = document.getElementById('customDialogMessage');
        this.input = document.getElementById('customDialogInput');
        this.footer = document.getElementById('customDialogFooter');
        this.closeBtn = document.getElementById('customDialogCloseBtn');

        // Clicking the X button closes the dialog and returns false/null
        this.closeBtn.addEventListener('click', () => this.close(this.input.classList.contains('hidden') ? false : null));
    },

    show(options) {
        if (!this.overlay) this.init();

        this.title.textContent = options.title || 'Notification';
        this.message.textContent = options.message || '';
        this.footer.innerHTML = ''; 
        this.input.value = options.defaultValue || '';

        if (options.type === 'prompt') {
            this.input.classList.remove('hidden');
            setTimeout(() => this.input.focus(), 100);
        } else {
            this.input.classList.add('hidden');
        }

        const btnContainer = document.createElement('div');
        btnContainer.className = 'dialog-buttons';

        // Add Cancel button for confirm/prompt types
        if (options.type === 'confirm' || options.type === 'prompt') {
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn btn-secondary';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.onclick = () => this.close(options.type === 'prompt' ? null : false);
            btnContainer.appendChild(cancelBtn);
        }

        const okBtn = document.createElement('button');
        okBtn.className = options.type === 'confirm' && options.danger ? 'btn btn-danger' : 'btn btn-primary';
        okBtn.textContent = 'OK';
        okBtn.onclick = () => {
            const result = options.type === 'prompt' ? this.input.value : true;
            this.close(result);
        };
        btnContainer.appendChild(okBtn);

        this.footer.appendChild(btnContainer);
        this.overlay.classList.add('active');

        if (options.type === 'prompt') {
            this.input.onkeydown = (e) => {
                if (e.key === 'Enter') okBtn.click();
            };
        }

        return new Promise((resolve) => {
            this.resolvePromise = resolve;
        });
    },

    close(value) {
        this.overlay.classList.remove('active');
        if (this.resolvePromise) {
            this.resolvePromise(value);
            this.resolvePromise = null;
        }
    },

    async alert(message, title = 'System Message') {
        return this.show({ type: 'alert', message, title });
    },

    async confirm(message, title = 'Confirmation', danger = false) {
        return this.show({ type: 'confirm', message, title, danger });
    },

    async prompt(message, defaultValue = '', title = 'Input Required') {
        return this.show({ type: 'prompt', message, defaultValue, title });
    }
};

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const authData = await API.auth.check();
        if (!authData.authenticated) {
            document.getElementById('app-view').classList.remove('active');
            document.getElementById('login-view').classList.add('active');
            return;
        }
        currentUser = { username: authData.username, role: authData.role };
        // shared with onu.js / router.js for role-gated controls
        window.currentUser = currentUser;
        initializeUI();
        await loadServerStatus();
        populateConsoleServers();
        checkClaudeHealth();
        checkNetboxHealth();
        setupUtilityIndicators();
        setupRestartButton();
        await setupAutoRefresh();
    } catch (error) {
        console.error('Auth check failed:', error);
        document.getElementById('app-view').classList.remove('active');
        document.getElementById('login-view').classList.add('active');
    }
});

async function setupAutoRefresh() {
    if (refreshInterval) { clearInterval(refreshInterval); refreshInterval = null; }
    let cfg = { enabled: true, interval_seconds: 30 };
    try {
        cfg = await API.servers.autoCheck();
    } catch (e) {
        console.warn('Auto-check setting unavailable, using defaults:', e);
    }
    if (cfg.enabled && cfg.interval_seconds >= 5) {
        refreshInterval = setInterval(loadServerStatus, cfg.interval_seconds * 1000);
    }
}

function initializeUI() {
    const userEl = document.getElementById('display-username');
    if (userEl) userEl.textContent = currentUser.username;
    
    const roleEl = document.getElementById('userRole');
    if (roleEl) roleEl.textContent = currentUser.role;
    
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    
    const executeBtn = document.getElementById('executeBtn');
    if (executeBtn) executeBtn.addEventListener('click', handleExecute);
    
    const cmdInput = document.getElementById('commandInput');
    if (cmdInput) {
        cmdInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleExecute();
        });
    }

    const modalClose = document.getElementById('modalClose');
    if (modalClose) modalClose.addEventListener('click', closeModal);
    
    const modalCloseBtn = document.getElementById('modalCloseBtn');
    if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeModal);
    
    const serverModal = document.getElementById('serverModal');
    if (serverModal) {
        serverModal.addEventListener('click', (e) => {
            if (e.target.id === 'serverModal') closeModal();
        });
    }
}

async function handleLogout() {
    try { await API.auth.logout(); } catch (e) {}
    window.location.reload();
}

let _serversGridBound = false;
function bindServersGrid() {
    if (_serversGridBound) return;
    const grid = document.getElementById('serversGrid');
    grid.addEventListener('click', (e) => {
        const retry = e.target.closest('.server-retry');
        if (retry) {
            e.stopPropagation();
            retryServer(retry.dataset.serverId);
            return;
        }
        const card = e.target.closest('.server-card');
        if (card && card.dataset.serverId && !card.classList.contains('checking')
            && !card.classList.contains('disconnected')) {
            showServerDetails(card.dataset.serverId);
        }
    });
    _serversGridBound = true;
}

function escapeHtml(str) {
    return String(str == null ? '' : str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

async function loadServerStatus() {
    const grid = document.getElementById('serversGrid');
    bindServersGrid();

    let configured = [];
    try {
        const list = await API.servers.list();
        configured = (list.servers || []).filter(s => s.enabled !== false);
    } catch (error) {
        console.error('Failed to load server list:', error);
        grid.innerHTML = '<p class="loading">Failed to load servers</p>';
        return;
    }

    if (configured.length === 0) {
        grid.innerHTML = '<p class="loading">No servers configured</p>';
        return;
    }

    grid.innerHTML = configured.map(s => createServerCard(s, 'checking')).join('');

    // 2) Real status. Each server is independent: the endpoint returns one entry
    //    per server (dead ones as connected=false), so a single failure only
    //    paints that one card red — the rest render normally.
    try {
        const data = await API.servers.status();
        grid.innerHTML = data.servers.map(s => createServerCard(s)).join('');
    } catch (error) {
        console.error('Failed to load status:', error);
        grid.innerHTML = configured.map(s => createServerCard({
            id: s.id, host: s.host, enabled: s.enabled,
            connected: false, services: [], error: 'Failed to retrieve status'
        })).join('');
    }
}

async function retryServer(serverId) {
    const replaceCard = (html) => {
        const el = document.querySelector(`.server-card[data-server-id="${serverId}"]`);
        if (el) el.outerHTML = html;
    };
    const existing = document.querySelector(`.server-card[data-server-id="${serverId}"]`);
    const host = existing ? (existing.querySelector('.server-host')?.textContent || '') : '';
    const out = document.getElementById('outputArea');

    if (out) out.textContent = `Reconnecting to ${serverId}...`;
    replaceCard(createServerCard({ id: serverId, host }, 'checking'));
    try {
        const status = await API.servers.reconnect(serverId);
        replaceCard(createServerCard(status));
        if (out) {
            out.textContent = status.connected
                ? `OK: ${serverId} — connection restored`
                : `${serverId} — NOT RESPONDING\n\n${status.error || 'unknown reason'}`;
        }
    } catch (error) {
        console.error('Retry failed for', serverId, error);
        const msg = String(error.message || error);
        replaceCard(createServerCard({
            id: serverId, host, connected: false, services: [], error: msg
        }));
        if (out) out.textContent = `${serverId} — request error\n\n${msg}`;
    }
}

// state: 'checking' | 'connected' | 'error' (defaults from server.connected)
function createServerCard(server, state) {
    if (!state) state = server.connected ? 'connected' : 'error';

    if (state === 'checking') {
        return `
        <div class="card server-card checking" data-server-id="${server.id}">
            <div class="card-header">
                <div class="flex align-center gap-2">
                    <span class="dot" style="background:#888; animation: pulse 1.5s infinite;"></span>
                    ${server.id}
                </div>
            </div>
            <div class="text-muted mb-3">${server.host || ''}</div>
            <div class="text-muted" style="font-size: 12px;">Checking connection...</div>
        </div>`;
    }

    if (state === 'error') {
        const errMsg = server.error
            ? `<div class="error-message mt-3" style="font-size: 12px;">${escapeHtml(server.error)}</div>` : '';
        return `
        <div class="card server-card disconnected" data-server-id="${server.id}">
            <div class="card-header" style="justify-content: space-between;">
                <div class="flex align-center gap-2">
                    <span class="dot error"></span>
                    ${server.id}
                </div>
                <span class="role-badge" style="background: rgba(218,54,51,0.1); color: #ff7b72;">Unresponsive</span>
            </div>
            <div class="text-muted">${server.host || ''}</div>
            ${errMsg}
            <button class="btn btn-outline btn-sm server-retry w-100 mt-4" data-server-id="${server.id}" type="button">🔄 Retry</button>
        </div>`;
    }

    // connected
    const servicesHtml = server.services.map(service => {
        const icon = service.health === 'healthy' ? '✓' : '✕';
        const dotClass = service.running ? 'ok' : 'error';
        return `
            <div class="flex align-center" style="justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border-base);">
                <span class="flex align-center gap-2" style="font-size: 13px;">
                    <span class="dot ${dotClass}"></span>
                    ${service.name || service.type}
                </span>
                <span class="text-muted" style="font-size: 12px;">${icon} ${service.running ? 'Running' : 'Stopped'}</span>
            </div>`;
    }).join('');

    const systemInfo = server.system_info ? `<div class="text-muted mt-3 mb-3" style="font-size: 12px;">Load: ${server.system_info.load || 'N/A'}</div>` : '';
    
    // Updates indicator
    let updatesHtml = '';
    if (server.updates) {
        const updatesTitle = server.updates.available > 0 
            ? `${server.updates.available} updates available (${server.updates.security} security)`
            : 'System up to date';
        const updateColor = server.updates.available > 0 ? 'color: var(--accent-yellow);' : 'color: var(--accent-green);';
        updatesHtml = `<span class="role-badge" style="${updateColor}" title="${updatesTitle}">
            ${server.updates.available > 0 ? '⚠️ Updates' : '✓ Up to date'}
        </span>`;
    }

    return `
        <div class="card server-card" data-server-id="${server.id}" style="cursor: pointer; transition: border-color 0.2s;">
            <div class="card-header" style="justify-content: space-between;">
                <div class="flex align-center gap-2">
                    <span class="dot ok"></span>
                    ${server.id}
                </div>
                ${updatesHtml}
            </div>
            <div class="text-muted">${server.host}</div>
            ${systemInfo}
            <div class="mt-2">${servicesHtml || '<p class="text-muted">No services</p>'}</div>
        </div>`;
}

async function showServerDetails(serverId) {
    const modal = document.getElementById('serverModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');

    title.textContent = 'Server: ' + serverId;
    body.innerHTML = '<div class="loading"><span class="spinner"></span>Loading...</div>';
    modal.classList.add('active');

    try {
        const data = await API.servers.info(serverId);
        
        let html = '<div class="server-info-grid">';
        
        // OS Section
        html += '<div class="info-section"><h4>&#128421; Operating System</h4><div class="detail-list">';
        html += '<div class="detail-item"><span class="detail-label">OS</span><span class="detail-value">' + (data.os.name || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Kernel</span><span class="detail-value">' + (data.os.kernel || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Architecture</span><span class="detail-value">' + (data.os.arch || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Init System</span><span class="detail-value">' + (data.status.init_system || 'Unknown') + '</span></div>';
        html += '</div></div>';
        
        // Hardware Section
        html += '<div class="info-section"><h4>&#9881; Hardware</h4><div class="detail-list">';
        html += '<div class="detail-item"><span class="detail-label">CPU</span><span class="detail-value">' + (data.hardware.cpu_model || 'Unknown') + ' (' + data.hardware.cpu_cores + ' cores)</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Memory</span><span class="detail-value">' + data.hardware.memory_used_mb + '/' + data.hardware.memory_total_mb + ' MB (' + data.hardware.memory_percent + '%)</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Disk</span><span class="detail-value">' + data.hardware.disk_used_gb + '/' + data.hardware.disk_total_gb + ' GB (' + data.hardware.disk_percent + '%)</span></div>';
        html += '</div></div>';
        
        // Status Section
        html += '<div class="info-section"><h4>&#128202; Status</h4><div class="detail-list">';
        html += '<div class="detail-item"><span class="detail-label">Hostname</span><span class="detail-value">' + (data.network.hostname || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Uptime</span><span class="detail-value">' + (data.status.uptime || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Load</span><span class="detail-value">' + (data.status.load_average || 'Unknown') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Services</span><span class="detail-value">' + data.services.running + ' running / ' + data.services.total + ' total</span></div>';
        html += '</div></div>';
        
        // Network Section
        html += '<div class="info-section"><h4>&#127760; Network</h4><div class="detail-list">';
        var ifaces = data.network.interfaces.map(function(i) { return i.name + ': ' + i.ip; }).join('<br>');
        html += '<div class="detail-item"><span class="detail-label">Interfaces</span><span class="detail-value">' + ifaces + '</span></div>';
        var ports = data.network.open_ports.slice(0, 10).join(', ') + (data.network.open_ports.length > 10 ? '...' : '');
        html += '<div class="detail-item"><span class="detail-label">Open Ports</span><span class="detail-value">' + ports + '</span></div>';
        html += '</div></div>';
        
        // Security Section
        html += '<div class="info-section"><h4>&#128274; Security</h4><div class="detail-list">';
        var updClass = data.security.updates_available > 0 ? 'warning-text' : '';
        html += '<div class="detail-item"><span class="detail-label">Updates</span><span class="detail-value ' + updClass + '">' + data.security.updates_available + ' available (' + data.security.security_updates + ' security)</span></div>';
        var rebootClass = data.security.reboot_required ? 'warning-text' : '';
        html += '<div class="detail-item"><span class="detail-label">Reboot Required</span><span class="detail-value ' + rebootClass + '">' + (data.security.reboot_required ? 'Yes' : 'No') + '</span></div>';
        html += '<div class="detail-item"><span class="detail-label">Firewall</span><span class="detail-value">' + data.security.firewall_status + '</span></div>';
        html += '</div></div>';
        
        html += '</div>';
        
        // Services section
        try {
            var serverData = await API.servers.get(serverId);
            if (serverData.services && serverData.services.length > 0) {
                html += '<div class="info-section" style="margin-top:16px;"><h4>&#128295; Services</h4><div class="services-list">';
                serverData.services.forEach(function(service) {
                    var icon = service.running ? '&#128994;' : '&#128308;';
                    html += '<div class="service-row"><div class="service-info"><strong>' + icon + ' ' + (service.name || service.type) + '</strong><span class="service-health">(' + (service.health || 'unknown') + ')</span></div>';
                    if (currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) {
                        html += '<div class="service-actions">';
                        html += '<button class="btn btn-sm btn-success" onclick="performAction(\'' + serverId + '\', \'' + service.type + '\', \'restart\')">Restart</button>';
                        html += '<button class="btn btn-sm btn-secondary" onclick="performAction(\'' + serverId + '\', \'' + service.type + '\', \'stop\')">Stop</button>';
                        html += '</div>';
                    }
                    html += '</div>';
                });
                html += '</div></div>';
            }
        } catch (e) { console.log('Services error:', e); }
        
        // Admin actions
        if (currentUser && (currentUser.role === 'admin' || currentUser.role === 'superadmin')) {
            html += '<div class="admin-actions"><h4>&#9889; System Actions</h4><div class="action-buttons">';
            html += '<button class="btn btn-secondary" onclick="checkUpdates(\'' + serverId + '\')">Check Updates</button>';
            html += '<button class="btn btn-secondary" onclick="showServerDetails(\'' + serverId + '\')">Refresh</button>';
            html += '</div></div>';
        }
        
        body.innerHTML = html;
    } catch (error) {
        body.innerHTML = '<p class="error-message">Error: ' + error.message + '</p>';
    }
}

async function checkUpdates(serverId) {
    const output = document.getElementById('outputArea');
    output.textContent = 'Checking updates on ' + serverId + '...';
    try {
        const result = await API.servers.checkUpdates(serverId);
        if (result.success) {
            output.textContent = 'OK: ' + result.message + '\n\nPackages:\n' + (result.packages.join('\n') || 'None');
        } else {
            output.textContent = 'Error: ' + result.message + '\n\n' + (result.output || '');
        }
        addToHistory('check updates ' + serverId, result.success);
        await loadServerStatus();
    } catch (error) {
        output.textContent = 'Error: ' + error.message;
        addToHistory('check updates ' + serverId, false);
    }
}

async function performAction(serverId, serviceType, action) {
    const isConfirmed = await Dialog.confirm(action + ' ' + serviceType + ' on ' + serverId + '?');
    if (!isConfirmed) return;
    var output = document.getElementById('outputArea');
    output.textContent = 'Performing ' + action + '...';
    try {
        var result = await API.servers.action(serverId, serviceType, action);
        output.textContent = result.success 
            ? 'OK: ' + action + ' completed\n\n' + (result.output || '')
            : 'Error: ' + action + ' failed\n\n' + result.message;
        addToHistory(action + ' ' + serviceType + '@' + serverId, result.success);
        await loadServerStatus();
        showServerDetails(serverId);
    } catch (error) {
        output.textContent = 'Error: ' + error.message;
        addToHistory(action + ' ' + serviceType + '@' + serverId, false);
    }
}

async function handleExecute() {
    var input = document.getElementById('commandInput');
    var output = document.getElementById('outputArea');
    var command = input.value.trim();
    if (!command) return;

    var serverSel = document.getElementById('consoleServer');
    var serverId = serverSel ? serverSel.value : '';
    var useSudo = document.getElementById('consoleSudo') && document.getElementById('consoleSudo').checked;

    output.textContent = 'Executing...';

    // Raw SSH console mode: a server is selected
    if (serverId) {
        try {
            var r = await API.console.exec(serverId, command, useSudo);
            var t = '[' + serverId + '] $ ' + (useSudo ? 'sudo ' : '') + command + '\n\n';
            if (r.stdout) t += r.stdout;
            if (r.stderr) t += (r.stdout ? '\n' : '') + '--- stderr ---\n' + r.stderr;
            if (!r.stdout && !r.stderr) t += '(no output)';
            t += '\n\n(exit code ' + r.exit_code + ')';
            output.textContent = t;
            addToHistory(serverId + ': ' + command, r.success);
        } catch (error) {
            output.textContent = 'Error: ' + error.message;
            addToHistory(serverId + ': ' + command, false);
        }
        input.value = '';
        return;
    }

    // Interpret mode (Claude / keyword fallback)
    try {
        var result = await API.commands.execute(command);
        var text = '';
        var icon = result.source === 'claude' ? '[AI]' : '[CMD]';
        if (result.interpretation) text += icon + ' Interpretation: ' + result.interpretation + '\n\n';
        if (result.commands_executed) {
            text += 'Commands:\n';
            result.commands_executed.forEach(function(cmd) {
                text += '  $ ' + cmd.command + '\n';
                if (cmd.output) text += '  ' + cmd.output + '\n';
            });
            text += '\n';
        }
        if (result.result) text += 'Result:\n' + result.result;
        if (result.error) text += 'Error: ' + result.error;
        output.textContent = text || 'Done';
        addToHistory(command, result.success);
        await loadServerStatus();
    } catch (error) {
        output.textContent = 'Error: ' + error.message;
        addToHistory(command, false);
    }
    input.value = '';
}

async function populateConsoleServers() {
    var sel = document.getElementById('consoleServer');
    if (!sel) return;
    try {
        var data = await API.servers.list();
        var servers = data.servers || data || [];
        servers.forEach(function(s) {
            var opt = document.createElement('option');
            opt.value = s.id;
            opt.textContent = '🖥️ ' + s.id;
            sel.appendChild(opt);
        });
    } catch (e) { /* ignore */ }
}

async function checkClaudeHealth() {
    var dot = document.getElementById('claudeDot');
    var wrap = document.getElementById('claudeStatus');
    if (!dot) return;
    try {
        var h = await API.claude.health();
        if (h.ok) {
            dot.style.background = '#3fb950';
            if (wrap) {
                wrap.title = 'Claude API: OK (' + (h.model || '') + ')';
                wrap.classList.remove('error');
            }
        } else {
            dot.style.background = '#f85149';
            if (wrap) {
                wrap.title = 'Claude API: ERROR — ' + (h.error || 'unknown');
                wrap.classList.add('error');
            }
        }
    } catch (e) {
        dot.style.background = '#f85149';
        if (wrap) {
            wrap.title = 'Claude API: unreachable';
            wrap.classList.add('error');
        }
    }
}

function addToHistory(command, success) {
    var list = document.getElementById('historyList');
    var empty = list.querySelector('.empty-history');
    if (empty) empty.remove();
    var time = new Date().toLocaleTimeString();
    var item = document.createElement('div');
    item.className = 'history-item';
    var statusIcon = success ? '&#10004;' : '&#10008;';
    item.innerHTML = '<span class="history-time">' + time + '</span><span class="history-command">' + escapeHtml(command) + '</span><span class="history-status">' + statusIcon + '</span>';
    list.insertBefore(item, list.firstChild);
    while (list.children.length > 20) list.removeChild(list.lastChild);
}

function closeModal() {
    document.getElementById('serverModal').classList.remove('active');
}

async function checkNetboxHealth() {
    var dot = document.getElementById('netboxDot');
    var wrap = document.getElementById('netboxStatus');
    if (!dot) return;
    try {
        var h = await API.netbox.health();
        // GET /api/netbox/health returns {status:'ok'|'degraded', netbox:{connected,version|error}}
        // — there is no top-level `ok` field (that was the mock's shape).
        var nb = h.netbox || {};
        if (h.status === 'ok' && nb.connected) {
            dot.style.background = '#3fb950';
            if (wrap) {
                wrap.title = 'NetBox API: OK (v' + (nb.version || '?') + ')';
                wrap.classList.remove('error');
            }
        } else {
            dot.style.background = '#f85149';
            if (wrap) {
                wrap.title = 'NetBox API: ERROR' + (nb.error ? ' — ' + nb.error : '');
                wrap.classList.add('error');
            }
        }
    } catch (e) {
        dot.style.background = '#f85149';
        if (wrap) {
            wrap.title = 'NetBox API: unreachable';
            wrap.classList.add('error');
        }
    }
}


/* =========================================================================
   HEADER UTILITY INDICATORS (electricity / water) + SERVICE RESTART

   Ported out of the inline <script> blocks that used to sit at the bottom of
   index.html. They are plain named functions here, called once from the
   DOMContentLoaded handler above, so nothing ends up nested inside an
   unrelated IIFE.
========================================================================= */

const UTILITY_REFRESH_MS = 30 * 60 * 1000;

function setupUtilityIndicators() {
    setupUtilityIndicator({
        wrapId: 'electricStatus',
        dotId: 'electricDot',
        label: 'Electricity',
        statusFn: () => API.electric.status(),
        checkFn: () => API.electric.check(),
    });
    setupUtilityIndicator({
        wrapId: 'waterStatus',
        dotId: 'waterDot',
        label: 'Water',
        statusFn: () => API.acc.status(),
        checkFn: () => API.acc.check(),
    });
}

function setupUtilityIndicator({ wrapId, dotId, label, statusFn, checkFn }) {
    const wrap = document.getElementById(wrapId);
    const dot = document.getElementById(dotId);
    if (!wrap || !dot) return;

    let last = null;

    function paint(state, title) {
        dot.classList.remove('ok', 'warning', 'error', 'checking');
        if (state) dot.classList.add(state);
        wrap.title = title;
    }

    async function refresh() {
        try {
            const data = await statusFn();
            last = data;
            if (data.ok) {
                paint('ok', label + ': OK' + (data.last_check
                    ? '\nChecked: ' + new Date(data.last_check).toLocaleString()
                    : ''));
            } else {
                paint('error', '⚠️ Possible ' + label.toLowerCase() + ' outage!'
                    + '\nMatches: ' + (data.matches_count ?? 0)
                    + (data.last_check ? '\nChecked: ' + new Date(data.last_check).toLocaleString() : ''));
            }
        } catch (e) {
            paint('warning', label + ': status unavailable');
        }
    }

    wrap.addEventListener('click', async () => {
        if (last && !last.ok && Array.isArray(last.matches) && last.matches.length > 0) {
            alert('⚠️ Possible ' + label.toLowerCase() + ' outage!\n\n' + last.matches.join('\n\n'));
            return;
        }
        paint('checking', label + ': checking...');
        try {
            const data = await checkFn();
            last = data;
            if (data.ok) {
                paint('ok', label + ': OK');
                alert('✅ No ' + label.toLowerCase() + ' outages found');
            } else {
                paint('error', '⚠️ Possible ' + label.toLowerCase() + ' outage!');
                alert('⚠️ Possible ' + label.toLowerCase() + ' outage!\n\n'
                    + (data.matches || []).join('\n\n'));
            }
        } catch (e) {
            paint('warning', label + ': check failed');
            alert('Check failed: ' + e.message);
        }
    });

    refresh();
    setInterval(refresh, UTILITY_REFRESH_MS);
}

function setupRestartButton() {
    const btn = document.getElementById('restartBtn');
    if (!btn) return;

    btn.addEventListener('click', async () => {
        if (!confirm('Restart the mcp-monitor service? The connection will drop briefly.')) return;

        btn.disabled = true;
        btn.style.opacity = '0.5';
        try {
            const result = await API.service.restart();
            if (result.success) {
                alert('✅ ' + result.message + '\n\nReloading in 5 seconds...');
                setTimeout(() => location.reload(), 5000);
            } else {
                alert('❌ Error: ' + result.message);
            }
        } catch (e) {
            alert('❌ Error: ' + e.message);
        } finally {
            btn.disabled = false;
            btn.style.opacity = '1';
        }
    });
}
