/**
 * Admin panel: user management and audit log (superadmin only).
 */

let adminInitialized = false;

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const me = await API.auth.me();
        if (me && me.role === 'superadmin') {
            const btn = document.getElementById('adminTabBtn');
            if (btn) {
                btn.style.display = '';
                btn.addEventListener('click', loadAdminData);
            }
            document.getElementById('addUserBtn').addEventListener('click', addUser);
            document.getElementById('auditRefreshBtn').addEventListener('click', loadAudit);
            document.getElementById('saveAddressesBtn').addEventListener('click', saveElectricAddresses);
            document.getElementById('saveAccPatternBtn').addEventListener('click', saveAccPattern);
            document.getElementById('saveScheduleBtn').addEventListener('click', saveSchedule);
        }
    } catch (e) {
        // not authenticated or not superadmin: leave admin tab hidden
    }
});

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
        let html = '<table style="width:100%;border-collapse:collapse;font-size:14px;">';
        html += '<thead><tr style="text-align:left;border-bottom:1px solid #3a3a5a;color:#9aa;">'
              + '<th style="padding:8px;">User</th><th style="padding:8px;">Role</th>'
              + '<th style="padding:8px;">Updated</th><th style="padding:8px;">Actions</th></tr></thead><tbody>';
        data.users.forEach(u => {
            const opts = roles.map(r =>
                `<option value="${r}" ${r === u.role ? 'selected' : ''}>${r}</option>`).join('');
            const safe = escapeHtml(u.username);
            html += '<tr style="border-bottom:1px solid #2a2a40;">'
                  + `<td style="padding:8px;"><strong>${safe}</strong></td>`
                  + `<td style="padding:8px;"><select onchange="changeUserRole('${safe}', this.value)" `
                  + 'style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;">'
                  + opts + '</select></td>'
                  + `<td style="padding:8px;color:#9aa;">${(u.updated_at || '').replace('T', ' ').slice(0, 19)}</td>`
                  + '<td style="padding:8px;">'
                  + `<button class="btn btn-sm btn-secondary" onclick="changeUserPassword('${safe}')">Password</button> `
                  + `<button class="btn btn-sm btn-danger" onclick="removeUser('${safe}')">Delete</button>`
                  + '</td></tr>';
        });
        html += '</tbody></table>';
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
        alert('Username and password are required');
        return;
    }
    try {
        await API.admin.createUser(username, password, role);
        document.getElementById('newUserName').value = '';
        document.getElementById('newUserPass').value = '';
        loadUsers();
        loadAudit();
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function changeUserRole(username, role) {
    try {
        await API.admin.setRole(username, role);
        loadAudit();
    } catch (e) {
        alert('Error: ' + e.message);
        loadUsers();
    }
}

async function changeUserPassword(username) {
    const password = prompt(`New password for ${username}:`);
    if (!password) return;
    try {
        await API.admin.setPassword(username, password);
        loadAudit();
        alert('Password updated');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function removeUser(username) {
    if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
    try {
        await API.admin.deleteUser(username);
        loadUsers();
        loadAudit();
    } catch (e) {
        alert('Error: ' + e.message);
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
            container.innerHTML = '<p class="empty-history">No audit entries</p>';
            return;
        }
        let html = '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
        html += '<thead><tr style="text-align:left;border-bottom:1px solid #3a3a5a;color:#9aa;">'
              + '<th style="padding:6px;">Time</th><th style="padding:6px;">User</th>'
              + '<th style="padding:6px;">Action</th><th style="padding:6px;">Target</th>'
              + '<th style="padding:6px;">Detail</th><th style="padding:6px;">OK</th>'
              + '<th style="padding:6px;">IP</th></tr></thead><tbody>';
        data.entries.forEach(e => {
            const ok = e.success === null || e.success === undefined ? '' : (e.success ? '✅' : '❌');
            html += '<tr style="border-bottom:1px solid #2a2a40;">'
                  + `<td style="padding:6px;color:#9aa;white-space:nowrap;">${(e.timestamp || '').replace('T', ' ').slice(0, 19)}</td>`
                  + `<td style="padding:6px;">${escapeHtml(e.username || '')}<br><span style="color:#778;">${escapeHtml(e.role || '')}</span></td>`
                  + `<td style="padding:6px;"><code>${escapeHtml(e.action || '')}</code></td>`
                  + `<td style="padding:6px;">${escapeHtml(e.target || '')}</td>`
                  + `<td style="padding:6px;">${escapeHtml(e.detail || '')}</td>`
                  + `<td style="padding:6px;text-align:center;">${ok}</td>`
                  + `<td style="padding:6px;color:#9aa;">${escapeHtml(e.ip || '')}</td>`
                  + '</tr>';
        });
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<p class="error-message">Error: ${escapeHtml(e.message)}</p>`;
    }
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
            `<input id="${id}" type="${type || 'text'}" value="${escapeHtml(val)}" `
            + 'style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;">';
        const pwPlaceholder = c.smtp_password_set ? 'set — leave blank to keep' : 'not set';
        container.innerHTML =
            `<div style="border-top:1px solid #2a2a40;margin-top:12px;padding-top:12px;">`
            + `<strong>${label}</strong>`
            + '<div style="display:grid;grid-template-columns:auto 1fr auto 1fr;gap:8px;align-items:center;margin:8px 0;">'
            + `<label style="color:#9aa;">SMTP server</label>${inp(channel + '_server', c.smtp_server)}`
            + `<label style="color:#9aa;">Port</label>${inp(channel + '_port', c.smtp_port, 'number')}`
            + `<label style="color:#9aa;">SMTP user</label>${inp(channel + '_user', c.smtp_user || '')}`
            + `<label style="color:#9aa;">SMTP password</label>`
            + `<input id="${channel}_password" type="password" placeholder="${pwPlaceholder}" `
            + 'style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;">'
            + `<label style="color:#9aa;">From</label>${inp(channel + '_from', c['from'])}`
            + `<label style="color:#9aa;">To (comma)</label>${inp(channel + '_to', c.to)}`
            + '</div>'
            + `<label style="color:#9aa;margin-right:16px;"><input type="checkbox" id="${channel}_tls" ${c.smtp_tls ? 'checked' : ''}> TLS</label>`
            + `<label style="color:#9aa;"><input type="checkbox" id="${channel}_enabled" ${c.enabled ? 'checked' : ''}> Notifications enabled</label> `
            + `<button class="btn btn-primary btn-sm" onclick="saveNotif('${channel}')" style="margin-left:12px;">Save ${label}</button>`
            + '</div>';
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
        alert('Saved');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function saveElectricAddresses() {
    const lines = document.getElementById('electricAddresses').value.split('\n')
        .map(l => l.trim()).filter(l => l && !l.startsWith('#'));
    try {
        const r = await API.admin.saveElectricAddresses(lines);
        document.getElementById('electricAddresses').value = (r.addresses || []).join('\n');
        loadAudit();
        alert(`Saved ${r.addresses.length} addresses`);
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function saveAccPattern() {
    const pattern = document.getElementById('accPattern').value.trim();
    if (!pattern) { alert('Pattern is required'); return; }
    try {
        await API.admin.saveAccPattern(pattern);
        loadAudit();
        alert('Saved');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function saveSchedule() {
    const et = document.getElementById('scheduleElectric').value;
    const at = document.getElementById('scheduleAcc').value;
    if (!et || !at) { alert('Set both times (HH:MM)'); return; }
    try {
        await API.admin.saveSchedule('electric', et);
        await API.admin.saveSchedule('acc', at);
        loadAudit();
        alert(`Schedule saved — electric ${et}, water ${at}`);
    } catch (e) {
        alert('Error: ' + e.message);
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

function serverFormHtml(s) {
    s = s || {};
    const dis = editingServerId ? 'disabled' : '';
    const fld = (id, val, type, ph) =>
        `<input id="srv_${id}" type="${type || 'text'}" value="${escapeHtml(val == null ? '' : val)}" placeholder="${ph || ''}" `
        + 'style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;">';
    const sel = (id, val, opts) =>
        `<select id="srv_${id}" style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;">`
        + opts.map(o => `<option value="${o}" ${o === val ? 'selected' : ''}>${o}</option>`).join('') + '</select>';
    const pwPh = (s.auth_value_set ? 'set — blank keeps' : '');
    const sudoPh = (s.sudo_password_set ? 'set — blank keeps' : '');
    return '<div style="background:#1e1e2e;padding:14px;border-radius:8px;margin:8px 0;">'
        + `<strong>${editingServerId ? 'Edit server: ' + escapeHtml(editingServerId) : 'Add server'}</strong>`
        + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0;">'
        + `<div>id<br>${fld('id', s.id, 'text', '')}${dis ? '<small style="color:#778;">(immutable)</small>' : ''}</div>`
        + `<div>host<br>${fld('host', s.host)}</div>`
        + `<div>port<br>${fld('port', s.port || 22, 'number')}</div>`
        + `<div>user<br>${fld('user', s.user)}</div>`
        + `<div>auth_type<br>${sel('auth_type', s.auth_type || 'password', ['password', 'key'])}</div>`
        + `<div>auth_value (password or key filename)<br><input id="srv_auth_value" type="password" placeholder="${pwPh}" style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;"></div>`
        + `<div>sudo_password<br><input id="srv_sudo_password" type="password" placeholder="${sudoPh}" style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;"></div>`
        + `<div>distro<br>${fld('distro', s.distro, 'text', 'debian / ubuntu...')}</div>`
        + '</div>'
        + (() => {
            const chosen = new Set(s.services || []);
            const types = serviceTypesCache || [];
            const boxes = types.length
                ? types.map(t =>
                    `<label style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;color:#cdd;">`
                    + `<input type="checkbox" class="srv-svc" value="${escapeHtml(t)}" ${chosen.has(t) ? 'checked' : ''}> ${escapeHtml(t)}</label>`
                  ).join('')
                : '<small style="color:#c66;">No service types available (add one in code)</small>';
            return `<div style="margin:4px 0 10px;">services<br>${boxes}</div>`;
        })()
        + `<label style="color:#9aa;"><input type="checkbox" id="srv_enabled" ${s.enabled === false ? '' : 'checked'}> enabled</label> `
        + '<button class="btn btn-primary btn-sm" id="serverSaveBtn" style="margin-left:12px;">Save</button> '
        + '<button class="btn btn-secondary btn-sm" id="serverCancelBtn">Clear</button>'
        + '</div>';
}

function serversTableHtml(servers) {
    if (editingServerId) document.getElementById('srv_id') && (document.getElementById('srv_id').disabled = true);
    let html = '<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;"><thead>'
        + '<tr style="text-align:left;border-bottom:1px solid #3a3a5a;color:#9aa;">'
        + '<th style="padding:6px;">ID</th><th style="padding:6px;">Host</th><th style="padding:6px;">User</th>'
        + '<th style="padding:6px;">Auth</th><th style="padding:6px;">Services</th><th style="padding:6px;">On</th>'
        + '<th style="padding:6px;">Actions</th></tr></thead><tbody>';
    servers.forEach(s => {
        const id = escapeHtml(s.id);
        html += '<tr style="border-bottom:1px solid #2a2a40;">'
            + `<td style="padding:6px;"><strong>${id}</strong></td>`
            + `<td style="padding:6px;">${escapeHtml(s.host || '')}:${s.port || 22}</td>`
            + `<td style="padding:6px;">${escapeHtml(s.user || '')}</td>`
            + `<td style="padding:6px;">${escapeHtml(s.auth_type || '')}</td>`
            + `<td style="padding:6px;">${escapeHtml((s.services || []).join(', '))}</td>`
            + `<td style="padding:6px;">${s.enabled ? '✅' : '⛔'}</td>`
            + '<td style="padding:6px;">'
            + `<button class="btn btn-sm btn-secondary" onclick='editServer(${JSON.stringify(id)})'>Edit</button> `
            + `<button class="btn btn-sm btn-danger" onclick='deleteServerRow(${JSON.stringify(id)})'>Delete</button>`
            + '</td></tr>';
    });
    return html + '</tbody></table>';
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
    if (!body.id || !body.host || !body.user) { alert('id, host and user are required'); return; }
    try {
        if (editingServerId) {
            await API.admin.editServer(editingServerId, body);
        } else {
            await API.admin.createServer(body);
        }
        editingServerId = null;
        loadServersAdmin();
        loadAudit();
        alert('Saved. Restart the service to apply.');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deleteServerRow(id) {
    if (!confirm(`Delete server "${id}"?`)) return;
    try {
        await API.admin.deleteServer(id);
        loadServersAdmin();
        loadAudit();
        alert('Deleted. Restart the service to apply.');
    } catch (e) {
        alert('Error: ' + e.message);
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
    const fld = (id, val, type, ph) =>
        `<input id="olt_${id}" type="${type || 'text'}" value="${escapeHtml(val == null ? '' : val)}" placeholder="${ph || ''}" `
        + 'style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;">';
    const sel = (id, val, opts) =>
        `<select id="olt_${id}" style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;">`
        + opts.map(x => `<option value="${x}" ${x === val ? 'selected' : ''}>${x}</option>`).join('') + '</select>';
    return '<div style="background:#1e1e2e;padding:14px;border-radius:8px;margin:8px 0;">'
        + `<strong>${editingOltId ? 'Edit OLT: ' + escapeHtml(editingOltId) : 'Add OLT'}</strong>`
        + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0;">'
        + `<div>id<br>${fld('id', o.id)}</div>`
        + `<div>host<br>${fld('host', o.host)}</div>`
        + `<div>SNMP port<br>${fld('port', o.port || 161, 'number')}</div>`
        + `<div>community<br>${fld('community', o.community || 'public')}</div>`
        + `<div>version<br>${sel('version', o.version || '2c', ['2c', '3'])}</div>`
        + `<div>vendor<br>${sel('vendor', o.vendor || 'zte', ['zte', 'huawei'])}</div>`
        + `<div>ssh_username<br>${fld('ssh_username', o.ssh_username)}</div>`
        + `<div>ssh_password<br><input id="olt_ssh_password" type="password" placeholder="${o.ssh_password_set ? 'set — blank keeps' : ''}" style="padding:6px;background:#252540;border:1px solid #3a3a5a;border-radius:6px;color:#fff;width:100%;"></div>`
        + `<div>ssh_port<br>${fld('ssh_port', o.ssh_port || 22, 'number')}</div>`
        + '</div>'
        + `<label style="color:#9aa;"><input type="checkbox" id="olt_enabled" ${o.enabled === false ? '' : 'checked'}> enabled</label> `
        + '<button class="btn btn-primary btn-sm" id="oltSaveBtn" style="margin-left:12px;">Save</button> '
        + '<button class="btn btn-secondary btn-sm" id="oltCancelBtn">Clear</button>'
        + '</div>';
}

function oltsTableHtml(olts) {
    let html = '<table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:8px;"><thead>'
        + '<tr style="text-align:left;border-bottom:1px solid #3a3a5a;color:#9aa;">'
        + '<th style="padding:6px;">ID</th><th style="padding:6px;">Host</th><th style="padding:6px;">Ver</th>'
        + '<th style="padding:6px;">Vendor</th><th style="padding:6px;">On</th><th style="padding:6px;">Actions</th></tr></thead><tbody>';
    olts.forEach(o => {
        const id = escapeHtml(o.id);
        html += '<tr style="border-bottom:1px solid #2a2a40;">'
            + `<td style="padding:6px;"><strong>${id}</strong></td>`
            + `<td style="padding:6px;">${escapeHtml(o.host || '')}:${o.port || 161}</td>`
            + `<td style="padding:6px;">${escapeHtml(o.version || '')}</td>`
            + `<td style="padding:6px;">${escapeHtml(o.vendor || '')}</td>`
            + `<td style="padding:6px;">${o.enabled ? '✅' : '⛔'}</td>`
            + '<td style="padding:6px;">'
            + `<button class="btn btn-sm btn-secondary" onclick='editOlt(${JSON.stringify(id)})'>Edit</button> `
            + `<button class="btn btn-sm btn-danger" onclick='deleteOltRow(${JSON.stringify(id)})'>Delete</button>`
            + '</td></tr>';
    });
    return html + '</tbody></table>';
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
    if (!body.id || !body.host) { alert('id and host are required'); return; }
    try {
        if (editingOltId) {
            await API.admin.editOlt(editingOltId, body);
        } else {
            await API.admin.createOlt(body);
        }
        editingOltId = null;
        loadOltsAdmin();
        loadAudit();
        alert('Saved. Restart the service to apply.');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}

async function deleteOltRow(id) {
    if (!confirm(`Delete OLT "${id}"?`)) return;
    try {
        await API.admin.deleteOlt(id);
        loadOltsAdmin();
        loadAudit();
        alert('Deleted. Restart the service to apply.');
    } catch (e) {
        alert('Error: ' + e.message);
    }
}
