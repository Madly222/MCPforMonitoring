/**
 * Admin panel: user management and audit log (superadmin only).
 */

let adminInitialized = false;

document.addEventListener('DOMContentLoaded', async () => {
    setupAdminSubTabs();

    try {
        const me = await API.auth.me();
        if (me && me.role === 'superadmin') {
            const btn = document.getElementById('adminTabBtn');
            if (btn) {
                btn.classList.remove('hidden');
                btn.addEventListener('click', loadAdminData);
            }
            document.getElementById('addUserBtn').addEventListener('click', addUser);
            document.getElementById('auditRefreshBtn').addEventListener('click', loadAudit);
            document.getElementById('saveAddressesBtn').addEventListener('click', saveElectricAddresses);
            document.getElementById('saveAccPatternBtn').addEventListener('click', saveAccPattern);
            document.getElementById('saveScheduleBtn').addEventListener('click', saveSchedule);
            document.getElementById('saveAutoCheckBtn').addEventListener('click', saveAutoCheck);
            document.getElementById('saveSshTimeoutBtn').addEventListener('click', saveSshTimeout);
            document.getElementById('saveDnsZoneBtn').addEventListener('click', saveDnsZone);
            document.getElementById('saveEnvBtn').addEventListener('click', saveEnv);
            document.getElementById('reseedServersBtn').addEventListener('click', () => reseedFromFile('servers'));
            document.getElementById('reseedOltsBtn').addEventListener('click', () => reseedFromFile('olts'));
            document.getElementById('reseedUsersBtn').addEventListener('click', () => reseedFromFile('users'));
            document.getElementById('envFilter').addEventListener('input', filterEnv);
        }
    } catch (e) {
        // not authenticated or not superadmin: leave admin tab hidden
    }
});

// Left-hand sub-navigation inside the "Company settings" tab
// (Users / Servers / OLT Devices / Audit Log / Settings).
function setupAdminSubTabs() {
    const nav = document.getElementById('adminSubnav');
    if (!nav) return;
    nav.querySelectorAll('.subtab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            nav.querySelectorAll('.subtab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.admin-panel').forEach(p => p.classList.remove('active'));
            const panel = document.getElementById('admin-panel-' + btn.dataset.adminTab);
            if (panel) panel.classList.add('active');
        });
    });
}

function loadAdminData() {
    loadUsers();
    loadAudit();
    loadSettings();
}

async function loadUsers() {
    const container = document.getElementById('usersTable');
    try {
        const data = await API.admin.listUsers();
        const roles = data.valid_roles || ['operator', 'admin', 'superadmin'];
        let html = '<div class="table-wrap"><table><thead><tr>'
              + '<th>User</th><th>Role</th><th>Updated</th><th>Actions</th></tr></thead><tbody>';
        data.users.forEach(u => {
            const opts = roles.map(r =>
                `<option value="${r}" ${r === u.role ? 'selected' : ''}>${r}</option>`).join('');
            const safe = escapeHtml(u.username);
            html += '<tr>'
                  + `<td class="cell-strong">${safe}</td>`
                  + `<td><select class="form-control input-sm" onchange="changeUserRole('${safe}', this.value)">${opts}</select></td>`
                  + `<td class="text-tertiary">${(u.updated_at || '').replace('T', ' ').slice(0, 19)}</td>`
                  + '<td><div class="table-actions">'
                  + `<button class="btn btn-sm btn-secondary" onclick="changeUserPassword('${safe}')">Password</button>`
                  + `<button class="btn btn-sm btn-danger" onclick="removeUser('${safe}')">Delete</button>`
                  + '</div></td></tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}

async function addUser() {
    const username = document.getElementById('newUserName').value.trim();
    const password = document.getElementById('newUserPass').value;
    const role = document.getElementById('newUserRole').value;
    if (!username || !password) {
        await Dialog.alert('Username and password are required');
        return;
    }
    try {
        await API.admin.createUser(username, password, role);
        document.getElementById('newUserName').value = '';
        document.getElementById('newUserPass').value = '';
        loadUsers();
        loadAudit();
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function changeUserRole(username, role) {
    try {
        await API.admin.setRole(username, role);
        loadAudit();
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
        loadUsers();
    }
}

async function changeUserPassword(username) {
    const password = await Dialog.prompt(`New password for ${username}:`);
    if (!password) return;
    try {
        await API.admin.setPassword(username, password);
        loadAudit();
        await Dialog.alert('Password updated');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function removeUser(username) {
    const isConfirmed = await Dialog.confirm(`Delete user "${username}"? This cannot be undone.`);
    if (!isConfirmed) return;

    try {
        await API.admin.deleteUser(username);
        loadUsers();
        loadAudit();
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function loadAudit() {
    const container = document.getElementById('auditTable');
    try {
        const params = {
            limit: 200,
            username: document.getElementById('auditUser').value.trim() || undefined,
            action: document.getElementById('auditAction').value.trim() || undefined,
        };
        const data = await API.admin.audit(params);
        if (!data.entries.length) {
            container.innerHTML = '<div class="empty-state">No audit entries</div>';
            return;
        }
        let html = '<div class="table-wrap"><table><thead><tr>'
              + '<th>Time</th><th>User</th><th>Action</th><th>Target</th>'
              + '<th>Detail</th><th>OK</th><th>IP</th></tr></thead><tbody>';
        data.entries.forEach(e => {
            const ok = e.success === null || e.success === undefined ? '' : (e.success ? '<span class="text-success">✔</span>' : '<span class="text-danger">✘</span>');
            html += '<tr>'
                  + `<td class="text-tertiary nowrap">${(e.timestamp || '').replace('T', ' ').slice(0, 19)}</td>`
                  + `<td>${escapeHtml(e.username || '')}<br><span class="text-tertiary text-xs">${escapeHtml(e.role || '')}</span></td>`
                  + `<td><code class="cell-code">${escapeHtml(e.action || '')}</code></td>`
                  + `<td>${escapeHtml(e.target || '')}</td>`
                  + `<td>${escapeHtml(e.detail || '')}</td>`
                  + `<td style="text-align:center;">${ok}</td>`
                  + `<td class="text-tertiary">${escapeHtml(e.ip || '')}</td>`
                  + '</tr>';
        });
        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}


// ===== Settings =====

async function loadSettings() {
    try {
        const ea = await API.admin.getElectricAddresses();
        document.getElementById('electricAddresses').value = (ea.addresses || []).join('\n');
    } catch (e) { /* ignore */ }
    try {
        const ap = await API.admin.getAccPattern();
        document.getElementById('accPattern').value = ap.pattern || '';
    } catch (e) { /* ignore */ }
    try {
        const se = await API.admin.getSchedule('electric');
        document.getElementById('scheduleElectric').value = se.time || '08:00';
        const sa = await API.admin.getSchedule('acc');
        document.getElementById('scheduleAcc').value = sa.time || '08:00';
    } catch (e) { /* ignore */ }
    try {
        const dz = await API.admin.getDnsZone();
        document.getElementById('dnsTestZone').value = dz.zone || '';
    } catch (e) { /* ignore */ }
    try {
        const env = await API.admin.getEnv();
        renderEnvEditor(env.entries || []);
    } catch (e) {
        document.getElementById('envEditor').innerHTML = '<span class="env-message text-danger">Error loading .env</span>';
    }
    try {
        const st = await API.admin.getSshTimeout();
        document.getElementById('sshTimeout').value = st.seconds || 8;
    } catch (e) { /* ignore */ }
    try {
        const ac = await API.admin.getAutoCheck();
        document.getElementById('autoCheckEnabled').checked = ac.enabled !== false;
        document.getElementById('autoCheckInterval').value = ac.interval_seconds || 30;
    } catch (e) { /* ignore */ }
    renderNotifChannel('electric', 'notifElectric', '⚡ Electric');
    renderNotifChannel('acc', 'notifAcc', '💧 Water (acc.md)');
    loadServersAdmin();
    loadOltsAdmin();
}

async function renderNotifChannel(channel, containerId, label) {
    const container = document.getElementById(containerId);
    try {
        const c = await API.admin.getNotifications(channel);
        const inp = (id, val, type) =>
            `<input id="${id}" class="form-control input-sm" type="${type || 'text'}" value="${escapeHtml(val)}">`;
        const pwPlaceholder = c.smtp_password_set ? 'set — leave blank to keep' : 'not set';
        container.innerHTML =
            `<div class="notif-channel-title">${label}</div>`
            + '<div class="notif-grid">'
            + `<div class="form-group"><label class="form-label">SMTP server</label>${inp(channel + '_server', c.smtp_server)}</div>`
            + `<div class="form-group"><label class="form-label">Port</label>${inp(channel + '_port', c.smtp_port, 'number')}</div>`
            + `<div class="form-group"><label class="form-label">SMTP user</label>${inp(channel + '_user', c.smtp_user || '')}</div>`
            + `<div class="form-group"><label class="form-label">SMTP password</label>`
            + `<input id="${channel}_password" class="form-control input-sm" type="password" placeholder="${pwPlaceholder}"></div>`
            + `<div class="form-group"><label class="form-label">From</label>${inp(channel + '_from', c['from'])}</div>`
            + `<div class="form-group"><label class="form-label">To (comma separated)</label>${inp(channel + '_to', c.to)}</div>`
            + '</div>'
            + '<div class="notif-checks">'
            + `<label class="checkbox-label"><input type="checkbox" id="${channel}_tls" ${c.smtp_tls ? 'checked' : ''}> TLS</label>`
            + `<label class="checkbox-label"><input type="checkbox" id="${channel}_enabled" ${c.enabled ? 'checked' : ''}> Notifications enabled</label>`
            + '</div>'
            + `<button class="btn btn-primary btn-sm" onclick="saveNotif('${channel}')">Save ${label}</button>`;
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}

async function saveNotif(channel) {
    const cfg = {
        smtp_server: document.getElementById(channel + '_server').value.trim(),
        smtp_port: parseInt(document.getElementById(channel + '_port').value, 10) || 25,
        smtp_user: document.getElementById(channel + '_user').value.trim(),
        smtp_password: document.getElementById(channel + '_password').value,
        smtp_tls: document.getElementById(channel + '_tls').checked,
        from: document.getElementById(channel + '_from').value.trim(),
        to: document.getElementById(channel + '_to').value.trim(),
        enabled: document.getElementById(channel + '_enabled').checked,
    };
    try {
        await API.admin.saveNotifications(channel, cfg);
        loadAudit();
        await Dialog.alert('Saved');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveElectricAddresses() {
    const lines = document.getElementById('electricAddresses').value.split('\n')
        .map(l => l.trim()).filter(l => l && !l.startsWith('#'));
    try {
        const r = await API.admin.saveElectricAddresses(lines);
        document.getElementById('electricAddresses').value = (r.addresses || []).join('\n');
        loadAudit();
        await Dialog.alert(`Saved ${r.addresses.length} addresses`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveAccPattern() {
    const pattern = document.getElementById('accPattern').value.trim();
    if (!pattern) { await Dialog.alert('Pattern is required'); return; }
    try {
        await API.admin.saveAccPattern(pattern);
        loadAudit();
        await Dialog.alert('Saved');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveSchedule() {
    const et = document.getElementById('scheduleElectric').value;
    const at = document.getElementById('scheduleAcc').value;
    if (!et || !at) { await Dialog.alert('Set both times (HH:MM)'); return; }
    try {
        await API.admin.saveSchedule('electric', et);
        await API.admin.saveSchedule('acc', at);
        loadAudit();
        await Dialog.alert(`Schedule saved — electric ${et}, water ${at}`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveAutoCheck() {
    const enabled = document.getElementById('autoCheckEnabled').checked;
    const interval = parseInt(document.getElementById('autoCheckInterval').value, 10);
    if (!interval || interval < 5) { await Dialog.alert('Interval must be at least 5 seconds'); return; }
    try {
        const r = await API.admin.saveAutoCheck(enabled, interval);
        loadAudit();
        await Dialog.alert(`Auto-check saved — ${r.enabled ? 'on' : 'off'}, every ${r.interval_seconds}s (applies on next dashboard load)`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveDnsZone() {
    const zone = document.getElementById('dnsTestZone').value.trim();
    if (!zone) { await Dialog.alert('Enter a zone, e.g. example.com'); return; }
    try {
        const r = await API.admin.saveDnsZone(zone);
        loadAudit();
        await Dialog.alert(`DNS test zone saved — ${r.zone}`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function reseedFromFile(section) {
    const isConfirmed = await Dialog.confirm(`Reload ${section} from secrets.yaml?\n\nThis DISCARDS panel edits for ${section} and re-reads the file.`);
    if (!isConfirmed) return;

    try {
        const r = await API.admin.reseedFromFile(section);
        loadAudit();
        if ((section === 'servers' || section === 'olts') && typeof loadServersAdmin === 'function') loadServersAdmin();
        if (section === 'olts' && typeof loadOltsAdmin === 'function') loadOltsAdmin();
        if (section === 'users' && typeof loadUsers === 'function') loadUsers();
        await Dialog.alert(r.detail + (r.restart_recommended
            ? '\n\nRestart to fully apply:\n  sudo systemctl restart mcp-monitor'
            : ''));
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

function renderEnvEditor(entries) {
    const box = document.getElementById('envEditor');
    if (!entries.length) { box.innerHTML = '<span class="env-message">No .env file found</span>'; return; }
    box.innerHTML = entries.map(e => {
        const ph = e.secret ? (e.has_value ? '•••• (set — blank keeps it)' : '(not set)') : '';
        const type = e.secret ? 'password' : 'text';
        const val = e.secret ? '' : (e.value || '');
        return `<div class="env-row" data-key="${e.key.toLowerCase()}">
            <span class="env-key">${e.key}</span>
            <input type="${type}" class="form-control env-input" data-key="${e.key}" data-secret="${e.secret ? 1 : 0}"
                   value="${String(val).replace(/"/g,'&quot;')}" placeholder="${ph}">
        </div>`;
    }).join('');
}

function filterEnv() {
    const q = document.getElementById('envFilter').value.toLowerCase();
    document.querySelectorAll('#envEditor .env-row').forEach(row => {
        row.classList.toggle('hidden', !row.dataset.key.includes(q));
    });
}

async function saveEnv() {
    const values = {};
    document.querySelectorAll('#envEditor .env-input').forEach(inp => {
        const secret = inp.dataset.secret === '1';
        const v = inp.value;
        if (secret && v === '') return;      // blank secret = keep current
        values[inp.dataset.key] = v;
    });
    if (!Object.keys(values).length) { await Dialog.alert('Nothing to save'); return; }
    try {
        const r = await API.admin.saveEnv(values);
        loadAudit();
        await Dialog.alert(`.env saved — ${r.written} key(s) updated.\nRestart the service to apply:\n  sudo systemctl restart mcp-monitor`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function saveSshTimeout() {
    const seconds = parseInt(document.getElementById('sshTimeout').value, 10);
    if (!seconds || seconds < 3 || seconds > 120) { await Dialog.alert('Timeout must be between 3 and 120 seconds'); return; }
    try {
        const r = await API.admin.saveSshTimeout(seconds);
        loadAudit();
        await Dialog.alert(`SSH connect timeout saved — ${r.seconds}s (applies immediately)`);
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

// ===== Servers management =====

let editingServerId = null;
let serviceTypesCache = null;

async function ensureServiceTypes() {
    if (serviceTypesCache) return serviceTypesCache;
    try {
        const r = await API.admin.serviceTypes();
        serviceTypesCache = r.types || [];
    } catch (e) {
        serviceTypesCache = [];
    }
    return serviceTypesCache;
}

async function loadServersAdmin() {
    const container = document.getElementById('serversAdmin');
    try {
        await ensureServiceTypes();
        const data = await API.admin.listServers();
        container.innerHTML = serverFormHtml() + serversTableHtml(data.servers);
        document.getElementById('serverSaveBtn').addEventListener('click', saveServer);
        document.getElementById('serverCancelBtn').addEventListener('click', () => { editingServerId = null; loadServersAdmin(); });
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}

function fieldHtml(idPrefix, id, val, type, ph) {
    return `<input id="${idPrefix}_${id}" class="form-control" type="${type || 'text'}" value="${escapeHtml(val == null ? '' : val)}" placeholder="${ph || ''}">`;
}
function selectHtml(idPrefix, id, val, opts) {
    return `<select id="${idPrefix}_${id}" class="form-control">`
        + opts.map(o => `<option value="${o}" ${o === val ? 'selected' : ''}>${o}</option>`).join('') + '</select>';
}

function serverFormHtml(s) {
    s = s || {};
    const dis = editingServerId ? true : false;
    const pwPh = (s.auth_value_set ? 'set — blank keeps' : '');
    const sudoPh = (s.sudo_password_set ? 'set — blank keeps' : '');
    return `<div class="admin-form-card">
        <div class="admin-form-title">${editingServerId ? 'Edit server: ' + escapeHtml(editingServerId) : 'Add server'}${dis ? '<span class="immutable-hint">(id is immutable)</span>' : ''}</div>
        <div class="admin-form-grid">
            <div class="form-group"><label class="form-label">ID</label>${fieldHtml('srv', 'id', s.id)}</div>
            <div class="form-group"><label class="form-label">Host</label>${fieldHtml('srv', 'host', s.host)}</div>
            <div class="form-group"><label class="form-label">Port</label>${fieldHtml('srv', 'port', s.port || 22, 'number')}</div>
            <div class="form-group"><label class="form-label">User</label>${fieldHtml('srv', 'user', s.user)}</div>
            <div class="form-group"><label class="form-label">Auth type</label>${selectHtml('srv', 'auth_type', s.auth_type || 'password', ['password', 'key'])}</div>
            <div class="form-group"><label class="form-label">Auth value (password / key file)</label><input id="srv_auth_value" class="form-control" type="password" placeholder="${pwPh}"></div>
            <div class="form-group"><label class="form-label">Sudo password</label><input id="srv_sudo_password" class="form-control" type="password" placeholder="${sudoPh}"></div>
            <div class="form-group"><label class="form-label">Distro</label>${fieldHtml('srv', 'distro', s.distro, 'text', 'debian / ubuntu...')}</div>
        </div>
        ${(() => {
            const chosen = new Set(s.services || []);
            const types = serviceTypesCache || [];
            const boxes = types.length
                ? types.map(t =>
                    `<label class="checkbox-label"><input type="checkbox" class="srv-svc" value="${escapeHtml(t)}" ${chosen.has(t) ? 'checked' : ''}> ${escapeHtml(t)}</label>`
                  ).join('')
                : '<span class="text-danger text-xs">No service types available (add one in code)</span>';
            return `<div class="form-group"><label class="form-label">Services</label><div class="service-checkbox-row">${boxes}</div></div>`;
        })()}
        <div class="admin-form-footer">
            <label class="checkbox-label"><input type="checkbox" id="srv_enabled" ${s.enabled === false ? '' : 'checked'}> Enabled</label>
            <button class="btn btn-primary btn-sm" id="serverSaveBtn">Save</button>
            <button class="btn btn-secondary btn-sm" id="serverCancelBtn">Clear</button>
        </div>
    </div>`;
}

function serversTableHtml(servers) {
    if (editingServerId) document.getElementById('srv_id') && (document.getElementById('srv_id').disabled = true);
    let html = '<div class="table-wrap"><table><thead><tr>'
        + '<th>ID</th><th>Host</th><th>User</th><th>Auth</th><th>Services</th><th>On</th><th>Actions</th></tr></thead><tbody>';
    servers.forEach(s => {
        const id = escapeHtml(s.id);
        html += '<tr>'
            + `<td class="cell-strong">${id}</td>`
            + `<td class="font-mono">${escapeHtml(s.host || '')}:${s.port || 22}</td>`
            + `<td>${escapeHtml(s.user || '')}</td>`
            + `<td>${escapeHtml(s.auth_type || '')}</td>`
            + `<td>${escapeHtml((s.services || []).join(', '))}</td>`
            + `<td>${s.enabled ? '<span class="badge badge-success">On</span>' : '<span class="badge badge-neutral">Off</span>'}</td>`
            + '<td><div class="table-actions">'
            + `<button class="btn btn-sm btn-secondary" onclick='editServer(${JSON.stringify(id)})'>Edit</button>`
            + `<button class="btn btn-sm btn-danger" onclick='deleteServerRow(${JSON.stringify(id)})'>Delete</button>`
            + '</div></td></tr>';
    });
    return html + '</tbody></table></div>';
}

async function editServer(id) {
    await ensureServiceTypes();
    const data = await API.admin.listServers();
    const s = data.servers.find(x => x.id === id);
    if (!s) return;
    editingServerId = id;
    const container = document.getElementById('serversAdmin');
    container.innerHTML = serverFormHtml(s) + serversTableHtml(data.servers);
    document.getElementById('srv_id').disabled = true;
    document.getElementById('serverSaveBtn').addEventListener('click', saveServer);
    document.getElementById('serverCancelBtn').addEventListener('click', () => { editingServerId = null; loadServersAdmin(); });
}

function collectServer() {
    const v = id => document.getElementById('srv_' + id).value;
    const body = {
        id: v('id').trim(),
        host: v('host').trim(),
        port: parseInt(v('port'), 10) || 22,
        user: v('user').trim(),
        auth_type: v('auth_type'),
        auth_value: document.getElementById('srv_auth_value').value,
        sudo_password: document.getElementById('srv_sudo_password').value,
        distro: v('distro').trim() || null,
        services: Array.from(document.querySelectorAll('.srv-svc:checked')).map(el => el.value),
        enabled: document.getElementById('srv_enabled').checked,
    };
    return body;
}

async function saveServer() {
    const body = collectServer();
    if (!body.id || !body.host || !body.user) { await Dialog.alert('id, host and user are required'); return; }
    try {
        if (editingServerId) {
            await API.admin.editServer(editingServerId, body);
        } else {
            await API.admin.createServer(body);
        }
        editingServerId = null;
        loadServersAdmin();
        loadAudit();
        await Dialog.alert('Saved. Restart the service to apply.');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function deleteServerRow(id) {
    const isConfirmed = await Dialog.confirm(`Delete server "${id}"?`);
    if (!isConfirmed) return;

    try {
        await API.admin.deleteServer(id);
        loadServersAdmin();
        loadAudit();
        await Dialog.alert('Deleted. Restart the service to apply.');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

// ===== OLT management =====

let editingOltId = null;

async function loadOltsAdmin() {
    const container = document.getElementById('oltsAdmin');
    try {
        const data = await API.admin.listOlts();
        container.innerHTML = oltFormHtml() + oltsTableHtml(data.olts);
        document.getElementById('oltSaveBtn').addEventListener('click', saveOlt);
        document.getElementById('oltCancelBtn').addEventListener('click', () => { editingOltId = null; loadOltsAdmin(); });
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}

function oltFormHtml(o) {
    o = o || {};
    return `<div class="admin-form-card">
        <div class="admin-form-title">${editingOltId ? 'Edit OLT: ' + escapeHtml(editingOltId) : 'Add OLT'}</div>
        <div class="admin-form-grid">
            <div class="form-group"><label class="form-label">ID</label>${fieldHtml('olt', 'id', o.id)}</div>
            <div class="form-group"><label class="form-label">Host</label>${fieldHtml('olt', 'host', o.host)}</div>
            <div class="form-group"><label class="form-label">SNMP port</label>${fieldHtml('olt', 'port', o.port || 161, 'number')}</div>
            <div class="form-group"><label class="form-label">Community</label>${fieldHtml('olt', 'community', o.community || 'public')}</div>
            <div class="form-group"><label class="form-label">Version</label>${selectHtml('olt', 'version', o.version || '2c', ['2c', '3'])}</div>
            <div class="form-group"><label class="form-label">Vendor</label>${selectHtml('olt', 'vendor', o.vendor || 'zte', ['zte', 'huawei'])}</div>
            <div class="form-group"><label class="form-label">SSH username</label>${fieldHtml('olt', 'ssh_username', o.ssh_username)}</div>
            <div class="form-group"><label class="form-label">SSH password</label><input id="olt_ssh_password" class="form-control" type="password" placeholder="${o.ssh_password_set ? 'set — blank keeps' : ''}"></div>
            <div class="form-group"><label class="form-label">SSH port</label>${fieldHtml('olt', 'ssh_port', o.ssh_port || 22, 'number')}</div>
        </div>
        <div class="admin-form-footer">
            <label class="checkbox-label"><input type="checkbox" id="olt_enabled" ${o.enabled === false ? '' : 'checked'}> Enabled</label>
            <button class="btn btn-primary btn-sm" id="oltSaveBtn">Save</button>
            <button class="btn btn-secondary btn-sm" id="oltCancelBtn">Clear</button>
        </div>
    </div>`;
}

function oltsTableHtml(olts) {
    let html = '<div class="table-wrap"><table><thead><tr>'
        + '<th>ID</th><th>Host</th><th>Ver</th><th>Vendor</th><th>On</th><th>Actions</th></tr></thead><tbody>';
    olts.forEach(o => {
        const id = escapeHtml(o.id);
        html += '<tr>'
            + `<td class="cell-strong">${id}</td>`
            + `<td class="font-mono">${escapeHtml(o.host || '')}:${o.port || 161}</td>`
            + `<td>${escapeHtml(o.version || '')}</td>`
            + `<td>${escapeHtml(o.vendor || '')}</td>`
            + `<td>${o.enabled ? '<span class="badge badge-success">On</span>' : '<span class="badge badge-neutral">Off</span>'}</td>`
            + '<td><div class="table-actions">'
            + `<button class="btn btn-sm btn-secondary" onclick='editOlt(${JSON.stringify(id)})'>Edit</button>`
            + `<button class="btn btn-sm btn-danger" onclick='deleteOltRow(${JSON.stringify(id)})'>Delete</button>`
            + '</div></td></tr>';
    });
    return html + '</tbody></table></div>';
}

async function editOlt(id) {
    const data = await API.admin.listOlts();
    const o = data.olts.find(x => x.id === id);
    if (!o) return;
    editingOltId = id;
    const container = document.getElementById('oltsAdmin');
    container.innerHTML = oltFormHtml(o) + oltsTableHtml(data.olts);
    document.getElementById('olt_id').disabled = true;
    document.getElementById('oltSaveBtn').addEventListener('click', saveOlt);
    document.getElementById('oltCancelBtn').addEventListener('click', () => { editingOltId = null; loadOltsAdmin(); });
}

function collectOlt() {
    const v = id => document.getElementById('olt_' + id).value;
    return {
        id: v('id').trim(),
        host: v('host').trim(),
        port: parseInt(v('port'), 10) || 161,
        community: v('community').trim() || 'public',
        version: v('version'),
        vendor: v('vendor'),
        ssh_username: v('ssh_username').trim() || null,
        ssh_password: document.getElementById('olt_ssh_password').value,
        ssh_port: parseInt(v('ssh_port'), 10) || 22,
        enabled: document.getElementById('olt_enabled').checked,
    };
}

async function saveOlt() {
    const body = collectOlt();
    if (!body.id || !body.host) { await Dialog.alert('id and host are required'); return; }
    try {
        if (editingOltId) {
            await API.admin.editOlt(editingOltId, body);
        } else {
            await API.admin.createOlt(body);
        }
        editingOltId = null;
        loadOltsAdmin();
        loadAudit();
        await Dialog.alert('Saved. Restart the service to apply.');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}

async function deleteOltRow(id) {
    const isConfirmed = await Dialog.confirm(`Delete OLT "${id}"?`);
    if (!isConfirmed) return;

    try {
        await API.admin.deleteOlt(id);
        loadOltsAdmin();
        loadAudit();
        await Dialog.alert('Deleted. Restart the service to apply.');
    } catch (e) {
        await Dialog.alert('Error: ' + e.message);
    }
}