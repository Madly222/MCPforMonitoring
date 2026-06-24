/**
 * Main Application Handler
 */

let currentUser = null;
let refreshInterval = null;

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const authData = await API.auth.check();
        if (!authData.authenticated) {
            window.location.href = '/login.html';
            return;
        }
        currentUser = { username: authData.username, role: authData.role };
        initializeUI();
        await loadServerStatus();
        populateConsoleServers();
        checkClaudeHealth();
        refreshInterval = setInterval(loadServerStatus, 30000);
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = '/login.html';
    }
});

function initializeUI() {
    document.getElementById('username').textContent = currentUser.username;
    document.getElementById('userRole').textContent = currentUser.role;
    document.getElementById('logoutBtn').addEventListener('click', handleLogout);
    document.getElementById('executeBtn').addEventListener('click', handleExecute);
    document.getElementById('commandInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleExecute();
    });
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('modalCloseBtn').addEventListener('click', closeModal);
    document.getElementById('serverModal').addEventListener('click', (e) => {
        if (e.target.id === 'serverModal') closeModal();
    });
}

async function handleLogout() {
    try { await API.auth.logout(); } catch (e) {}
    window.location.href = '/login.html';
}

async function loadServerStatus() {
    const grid = document.getElementById('serversGrid');
    try {
        const data = await API.servers.status();
        if (data.servers.length === 0) {
            grid.innerHTML = '<p class="loading">No servers configured</p>';
            return;
        }
        grid.innerHTML = data.servers.map(server => createServerCard(server)).join('');
        document.querySelectorAll('.server-card').forEach(card => {
            card.addEventListener('click', () => showServerDetails(card.dataset.serverId));
        });
        updateConnectionStatus(true);
    } catch (error) {
        console.error('Failed to load status:', error);
        updateConnectionStatus(false);
        grid.innerHTML = '<p class="loading">Failed to load servers</p>';
    }
}

function createServerCard(server) {
    const statusClass = server.connected ? 'status-ok' : 'status-error';
    const cardClass = server.connected ? '' : 'disconnected';
    
    const servicesHtml = server.services.map(service => {
        const running = service.running ? 'running' : 'stopped';
        const icon = service.health === 'healthy' ? '&#10004;' : service.health === 'unhealthy' ? '&#10008;' : '?';
        return `
            <div class="service-item">
                <span class="service-name">
                    <span class="status-dot ${service.running ? 'status-ok' : 'status-error'}"></span>
                    ${service.name || service.type}
                </span>
                <span class="service-status ${running}">${icon} ${service.running ? 'Running' : 'Stopped'}</span>
            </div>`;
    }).join('');

    const systemInfo = server.system_info ? `<div class="server-info"><small>Load: ${server.system_info.load || 'N/A'}</small></div>` : '';
    
    // Updates indicator
    let updatesHtml = '';
    if (server.updates) {
        const updatesClass = server.updates.available > 0 ? 'updates-available' : 'updates-ok';
        const updatesIcon = server.updates.available > 0 ? '&#8593;' : '&#10004;';
        const updatesTitle = server.updates.available > 0 
            ? `${server.updates.available} updates available (${server.updates.security} security)`
            : 'System up to date';
        updatesHtml = `<span class="updates-indicator ${updatesClass}" title="${updatesTitle}">${updatesIcon}</span>`;
    }

    return `
        <div class="server-card ${cardClass}" data-server-id="${server.id}">
            <div class="server-card-header">
                <div class="server-name"><span class="status-dot ${statusClass}"></span>${server.id}</div>
                ${updatesHtml}
            </div>
            <div class="server-host">${server.host}</div>
            ${systemInfo}
            <div class="server-services">${servicesHtml || '<p>No services</p>'}</div>
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
        const data = await API.request('/servers/' + serverId + '/info');
        
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
                    if (currentUser.role === 'admin' || currentUser.role === 'superadmin') {
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
        
        // Admin actions (without Install Updates)
        if (currentUser.role === 'admin' || currentUser.role === 'superadmin') {
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
    var output = document.getElementById('outputArea');
    output.textContent = 'Checking updates on ' + serverId + '...';
    try {
        var result = await API.request('/servers/' + serverId + '/updates/check', { method: 'POST' });
        if (result.success) {
            output.textContent = 'OK: ' + result.message + '\n\nPackages:\n' + (result.packages.join('\n') || 'None');
        } else {
            output.textContent = 'Error: ' + result.message + '\n\n' + (result.output || '');
        }
        addToHistory('check updates ' + serverId, result.success);
        // Refresh server list to update indicator
        await loadServerStatus();
    } catch (error) {
        output.textContent = 'Error: ' + error.message;
        addToHistory('check updates ' + serverId, false);
    }
}

async function performAction(serverId, serviceType, action) {
    if (!confirm(action + ' ' + serviceType + ' on ' + serverId + '?')) return;
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
            if (wrap) wrap.title = 'Claude API: OK (' + (h.model || '') + ')';
        } else {
            dot.style.background = '#f85149';
            if (wrap) wrap.title = 'Claude API: ERROR — ' + (h.error || 'unknown');
        }
    } catch (e) {
        dot.style.background = '#f85149';
        if (wrap) wrap.title = 'Claude API: unreachable';
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

function updateConnectionStatus(connected) {
    var dot = document.querySelector('.connection-status .status-dot');
    var text = document.getElementById('statusText');
    dot.className = 'status-dot ' + (connected ? 'status-ok' : 'status-error');
    text.textContent = connected ? 'Connected' : 'Disconnected';
}

function closeModal() {
    document.getElementById('serverModal').classList.remove('active');
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}