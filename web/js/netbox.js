/**
 * NetBox Auto-Fill Module
 */

const NB_API = '/api/netbox';
let nbScanData = null;
let nbSelected = new Set();
let nbRouterSelected = new Set();

function authHeaders() {
    return { 'Content-Type': 'application/json' };
}

// Session auth is cookie-based; send it explicitly on every NetBox call.
const NB_FETCH_OPTS = { credentials: 'include' };

function nbUpdateDeviceType() {
    const deviceType = document.getElementById("nbDeviceType").value;
    const hostLabel = document.getElementById("nbHostLabel");
    if (deviceType === "router") {
        hostLabel.textContent = "Router IP Address";
    } else {
        hostLabel.textContent = "Switch IP Address";
    }
}

function nbUpdateConnFields() {
    const connType = document.getElementById("nbConnType").value;
    const userLabel = document.getElementById("nbUserLabel");
    const passLabel = document.getElementById("nbPassLabel");
    if (connType === "radius") {
        userLabel.textContent = "RADIUS Username";
        passLabel.textContent = "RADIUS Password";
    } else {
        userLabel.textContent = "SSH Username";
        passLabel.textContent = "SSH Password";
    }
}

function nbSwitchTab(t) {
    document.querySelectorAll('.nb-tab').forEach(b => b.classList.remove('active'));
    document.getElementById('nb-tab-single').classList.add('hidden', 'nb-hidden');
    document.getElementById('nb-tab-batch').classList.add('hidden', 'nb-hidden');

    if (t === 'single') {
        document.querySelectorAll('.nb-tab')[0].classList.add('active');
        document.getElementById('nb-tab-single').classList.remove('hidden', 'nb-hidden');
    } else {
        document.querySelectorAll('.nb-tab')[1].classList.add('active');
        document.getElementById('nb-tab-batch').classList.remove('hidden', 'nb-hidden');
    }
}

/** Alias for global escapeHtml defined in app.js */
const esc = escapeHtml;

function nbRenderLogs(logs, id, title) {
    const el = document.getElementById(id);
    el.className = 'card nb-log mb-4';
    el.classList.remove('hidden', 'nb-hidden');
    el.innerHTML = `<div class="card-header">${title}</div><div class="output-area">${logs.map(l => `<div>${esc(l)}</div>`).join('')}</div>`;
    el.querySelector('.output-area').scrollTop = 99999;
}

function nbStat(label, value) {
    return `<div class="form-group"><label class="form-label">${esc(label)}</label><div class="font-bold">${value}</div></div>`;
}

async function nbScan() {
    const host = document.getElementById('nbHost').value.trim();
    if (!host) return;

    const deviceType = document.getElementById('nbDeviceType').value;
    document.getElementById('nbError').classList.add('hidden', 'nb-hidden');
    const btn = document.getElementById('nbBtnScan');
    btn.disabled = true;
    btn.innerHTML = 'Scanning...';

    ['nbDeviceInfo', 'nbPortTable', 'nbApplyLog', 'nbRouterInfo'].forEach(i => {
        const el = document.getElementById(i);
        if (el) el.classList.add('hidden', 'nb-hidden');
    });

    try {
        const body = { host, connection_type: document.getElementById('nbConnType').value, device_type: deviceType };
        const u = document.getElementById('nbUser').value.trim();
        const p = document.getElementById('nbPass').value;

        if (u) body.username = u;
        if (p) body.password = p;

        const endpoint = deviceType === 'router' ? '/scan-router' : '/scan';
        const res = await fetch(NB_API + endpoint, { ...NB_FETCH_OPTS, method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
        const data = await res.json();

        if (!res.ok) throw new Error(data.detail || 'Scan failed');

        nbScanData = data;
        nbRenderLogs(data.logs || [], 'nbScanLog', 'Scan Log');

        if (deviceType === 'router') {
            nbRenderRouter(data);
        } else {
            const di = document.getElementById('nbDeviceInfo');
            di.classList.remove('hidden', 'nb-hidden');
            di.innerHTML = `<div class="nb-scan-grid">
                ${nbStat('Host', data.host)}
                ${nbStat('Hostname', data.hostname || '—')}
                ${nbStat('NetBox Device', data.device_name || 'Not found')}
                ${nbStat('Ports Found', data.ports?.length || 0)}
            </div>`;
            nbSelected = new Set((data.ports || []).map(p => p.port_name));
            nbRenderPorts();
        }
    } catch (e) {
        const el = document.getElementById('nbError');
        el.textContent = e.message;
        el.classList.remove('hidden', 'nb-hidden');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔍 Scan';
    }
}

function nbRenderRouter(data) {
    const el = document.getElementById("nbRouterInfo");
    el.classList.remove("hidden", "nb-hidden");

    let h = `<div class="nb-scan-grid mb-4">
        ${nbStat('Host', data.host)}
        ${nbStat('Hostname', data.hostname || '—')}
        ${nbStat('Model', data.model || '—')}
        ${nbStat('Serial', data.serial || '—')}
        ${nbStat('IOS Version', data.ios_version || '—')}
        ${nbStat('Uptime', data.uptime || '—')}
    </div>`;

    if (data.interfaces?.length) {
        nbRouterSelected = new Set(data.interfaces.filter(i => i.status === "up").map(i => i.name));
        const allSel = nbRouterSelected.size === data.interfaces.length;
        h += `<div class="flex justify-between align-center mb-3">
                <strong>Interfaces (${data.interfaces.length})</strong>
                <div class="flex gap-2">
                    <button class="btn btn-outline btn-sm" onclick="nbToggleAllRouter()">${allSel ? "Deselect All" : "Select All"}</button>
                    <button class="btn btn-success btn-sm" id="nbBtnApplyRouter" onclick="nbApplyRouter()">✅ Apply to NetBox</button>
                </div>
              </div>
              <div class="table-wrap"><table>
              <thead>
                <tr><th><input type="checkbox" ${allSel ? "checked" : ""} onchange="nbToggleAllRouter()"></th>
                <th>Interface</th><th>IP Address</th><th>Status</th><th>Protocol</th><th>Description</th></tr>
              </thead><tbody>`;

        for (const i of data.interfaces) {
            const sel = nbRouterSelected.has(i.name);
            const stC = i.status === "up" ? "text-success" : "text-danger";
            const prC = i.protocol === "up" ? "text-success" : "text-danger";
            h += `<tr>
                    <td><input type="checkbox" ${sel ? "checked" : ""} onchange="nbToggleRouter('${i.name}')"></td>
                    <td class="cell-strong">${esc(i.name)}</td><td class="font-mono">${esc(i.ip_address)}</td>
                    <td class="${stC}">${esc(i.status)}</td>
                    <td class="${prC}">${esc(i.protocol)}</td>
                    <td>${esc(i.description || "—")}</td>
                  </tr>`;
        }
        h += `</tbody></table></div>`;
    }
    el.innerHTML = h;
}

function nbToggleRouter(name) {
    if (nbRouterSelected.has(name)) nbRouterSelected.delete(name);
    else nbRouterSelected.add(name);
    nbRenderRouter(nbScanData);
}

function nbToggleAllRouter() {
    if (nbRouterSelected.size === nbScanData.interfaces.length) nbRouterSelected.clear();
    else nbRouterSelected = new Set(nbScanData.interfaces.map(i => i.name));
    nbRenderRouter(nbScanData);
}

async function nbSyncMac() {
    const btn = document.getElementById("nbSyncMac");
    btn.disabled = true; btn.innerHTML = "Syncing...";
    try {
        const res = await fetch(NB_API + "/sync-mac", { method: "POST", headers: authHeaders(), credentials: "include" });
        const data = await res.json();
        if (data.success) {
            const s = data.stats || {};
            await Dialog.alert("✅ MAC Sync Complete\n\nUpdated: " + s.updated + "\nSkipped: " + s.skipped + "\nNot found: " + s.not_found + "\nErrors: " + s.errors);
        } else {
            await Dialog.alert("❌ Error: " + (data.error || "Unknown error"));
        }
        if (data.logs?.length) {
            nbRenderLogs(data.logs, "nbScanLog", "MAC Sync Log");
        }
    } catch (e) {
        await Dialog.alert("❌ Error: " + e.message);
    } finally {
        btn.disabled = false; btn.innerHTML = "🔄 Sync MAC";
    }
}

async function nbSyncPorts() {
    const btn = document.getElementById("nbSyncPorts");
    btn.disabled = true; btn.innerHTML = "Tracing...";
    try {
        const body = {
            radius_username: (document.getElementById("nbRadUser") || {}).value || "",
            radius_password: (document.getElementById("nbRadPass") || {}).value || "",
            ssh_username: (document.getElementById("nbSshUser") || {}).value || "",
            ssh_password: (document.getElementById("nbSshPass") || {}).value || ""
        };
        const res = await fetch(NB_API + "/sync-interfaces", { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(body) });
        const data = await res.json();
        if (data.success) {
            const s = data.stats || {};
            const fails = (data.failures || []).length;
            await Dialog.alert("✅ Port Sync Complete\n\nAssigned: " + s.assigned + "\nAlready OK: " + s.already_ok + "\nErrors: " + s.errors);
        } else {
            await Dialog.alert("❌ Error: " + (data.error || "Unknown error"));
        }
        if (data.logs?.length) {
            nbRenderLogs(data.logs, "nbScanLog", "Port Sync Log");
        }
    } catch (e) {
        await Dialog.alert("❌ Error: " + e.message);
    } finally {
        btn.disabled = false; btn.innerHTML = "🔗 Sync Ports";
    }
}

async function nbApplyRouter() {
    const btn = document.getElementById("nbBtnApplyRouter");
    btn.disabled = true; btn.innerHTML = "Applying...";
    try {
        const res = await fetch(NB_API + "/apply-router", { ...NB_FETCH_OPTS, method: "POST", headers: authHeaders(), body: JSON.stringify({ host: nbScanData.host, selected_ports: [...nbRouterSelected] }) });
        const data = await res.json();
        nbRenderLogs(data.logs || [], "nbApplyLog", "Apply Log");
    } catch (e) {
        await Dialog.alert("Error: " + e.message);
    } finally {
        btn.disabled = false; btn.innerHTML = "✅ Apply to NetBox";
    }
}

function nbRenderPorts() {
    if (!nbScanData?.ports?.length) return;
    const el = document.getElementById('nbPortTable');
    el.classList.remove('hidden', 'nb-hidden');

    const allSel = nbSelected.size === nbScanData.ports.length;
    let h = `<div class="card-header justify-between nb-port-table-header">
                <span>Port Configuration (${nbSelected.size}/${nbScanData.ports.length} selected)</span>
                <div class="flex gap-2">
                    <button class="btn btn-outline btn-sm" onclick="nbToggleAll()">${allSel ? 'Deselect All' : 'Select All'}</button>
                    <button class="btn btn-success btn-sm" id="nbBtnApply" onclick="nbApply()" ${nbSelected.size === 0 ? 'disabled' : ''}>✅ Apply</button>
                </div>
             </div>
             <div class="table-wrap nb-port-table-wrap"><table>
             <thead>
                <tr><th><input type="checkbox" ${allSel ? 'checked' : ''} onchange="nbToggleAll()"></th>
                <th>Port</th><th>Mode</th><th>VLANs</th><th>Description</th><th>CDP Neighbor</th><th>Remote Port</th></tr>
             </thead><tbody>`;

    for (const p of nbScanData.ports) {
        const sel = nbSelected.has(p.port_name);
        h += `<tr onclick="nbToggle('${p.port_name}')" class="nb-row-selectable">
                <td><input type="checkbox" ${sel ? 'checked' : ''} onclick="event.stopPropagation();nbToggle('${p.port_name}')"></td>
                <td class="cell-strong">${esc(p.port_name)}</td>
                <td>${p.mode || '—'}</td>
                <td>${p.access_vlan || '—'}</td>
                <td>${esc(p.description || '—')}</td>
                <td>${esc(p.cdp_neighbor || '—')}</td>
                <td>${esc(p.cdp_remote_port || '—')}</td>
              </tr>`;
    }
    h += '</tbody></table></div>';
    el.innerHTML = h;
}

function nbToggle(n) {
    nbSelected.has(n) ? nbSelected.delete(n) : nbSelected.add(n);
    nbRenderPorts();
}

function nbToggleAll() {
    if (!nbScanData) return;
    nbSelected.size === nbScanData.ports.length ? nbSelected = new Set() : nbSelected = new Set(nbScanData.ports.map(p => p.port_name));
    nbRenderPorts();
}

async function nbApply() {
    if (!nbScanData || nbSelected.size === 0) return;
    const btn = document.getElementById('nbBtnApply');
    btn.disabled = true; btn.innerHTML = 'Applying...';
    try {
        const res = await fetch(NB_API + '/apply', { ...NB_FETCH_OPTS, method: 'POST', headers: authHeaders(), body: JSON.stringify({ host: nbScanData.host, selected_ports: [...nbSelected] }) });
        const data = await res.json();
        nbRenderLogs(data.logs || [], 'nbApplyLog', 'Apply Log');
    } catch (e) {
        nbRenderLogs(['❌ Error: ' + e.message], 'nbApplyLog', 'Apply Log');
    } finally {
        btn.disabled = false; btn.innerHTML = '✅ Apply (' + nbSelected.size + ')';
    }
}

async function nbBatch() {
    const ips = document.getElementById('nbBatchIps').value.trim().split('\n').map(s => s.trim()).filter(Boolean);
    if (!ips.length) return;

    const btn = document.getElementById('nbBtnBatch');
    btn.disabled = true; btn.innerHTML = 'Running...';

    const results = document.getElementById('nbBatchResults');
    results.innerHTML = '';

    const u = document.getElementById('nbBatchUser').value.trim();
    const p = document.getElementById('nbBatchPass').value;

    for (let i = 0; i < ips.length; i++) {
        const card = document.createElement('div');
        card.className = 'card mb-3';
        card.innerHTML = `<div class="card-header">Processing ${esc(ips[i])}...</div>`;
        results.appendChild(card);

        try {
            const body = { host: ips[i] };
            if (u) body.username = u;
            if (p) body.password = p;

            const res = await fetch(NB_API + '/auto', { ...NB_FETCH_OPTS, method: 'POST', headers: authHeaders(), body: JSON.stringify(body) });
            const data = await res.json();

            const st = data.errors?.length ? '⚠️' : '✅';
            const logs = [...(data.scan_logs || []), ...(data.apply_logs || [])];

            card.innerHTML = `<div class="card-header">${st} ${esc(ips[i])} — ${esc(data.hostname || 'unknown')}</div>
                              <div class="output-area">${logs.map(l => `<div>${esc(l)}</div>`).join('')}</div>`;
        } catch (e) {
            card.innerHTML = `<div class="card-header text-danger">❌ ${esc(ips[i])}</div><div class="error-message">${esc(e.message)}</div>`;
        }
    }
    btn.disabled = false; btn.innerHTML = 'Run All';
}