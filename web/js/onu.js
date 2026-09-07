/**
 * ONU Monitoring Module - Tree View
 * Path: ~/ServersMonitoringMCP/web/js/onu.js
 */

// ONU State
let onuData = [];
let oltsData = [];
let onuFilter = 'all';
let onuSearch = '';
let selectedOlt = null;
let onuThresholds = { good: -10, warning: -22 };
let onuRefreshInterval = null;

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupOnuEventListeners();
});

// Tab Navigation
// NOTE: primary tab switching (nav-item -> tab-pane) lives in router.js.
// This module only listens for `.tab-btn` / `.tab-content`, kept as-is from
// the original wiring so it doesn't double-bind against router.js.
function setupTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;

            tabBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            tabContents.forEach(content => {
                content.classList.remove('active');
                if (content.id === `tab-${tabId}`) {
                    content.classList.add('active');
                }
            });

            if (tabId === 'onu') {
                loadOnuData();
                if (!onuRefreshInterval) {
                    onuRefreshInterval = setInterval(loadOnuData, 60000);
                }
            } else {
                if (onuRefreshInterval) {
                    clearInterval(onuRefreshInterval);
                    onuRefreshInterval = null;
                }
            }
        });
    });

    // Also react to the real nav (router.js) so the ONU auto-refresh timer
    // starts/stops correctly even though router.js owns the actual tab swap.
    document.querySelectorAll('.nav-item[data-target]').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.target === 'tab-onu') {
                loadOnuData();
                if (!onuRefreshInterval) onuRefreshInterval = setInterval(loadOnuData, 60000);
            } else if (onuRefreshInterval) {
                clearInterval(onuRefreshInterval);
                onuRefreshInterval = null;
            }
        });
    });
}

// ONU Event Listeners
function setupOnuEventListeners() {
    // Initial setup - handlers will be re-attached dynamically
}

// Load ONU Data
async function loadOnuData() {
    const refreshBtn = document.getElementById('refreshOnuBtn');

    if (refreshBtn) refreshBtn.disabled = true;

    try {
        const response = await API.onu.status();
        onuData = response.onus || [];
        onuThresholds = response.thresholds || { good: -20, warning: -25 };

        // Group by OLT
        groupByOlt();

        // Update view
        if (selectedOlt) {
            showOnuView();
        } else {
            showOltList();
        }
    } catch (error) {
        console.error('Failed to load ONU data:', error);
        const container = document.getElementById('onuContainer');
        if (container) {
            container.innerHTML = `<div class="onu-empty">Failed to load: ${escapeHtml(error.message)}</div>`;
        }
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

// POST /api/onu/olt/{id}/poll is admin+superadmin only -> hide it for operators
function canPollOlt() {
    const role = (window.currentUser && window.currentUser.role) || '';
    return role === 'admin' || role === 'superadmin';
}

// Force poll of the currently selected OLT
async function pollSelectedOlt() {
    if (!selectedOlt) return;
    const btn = document.getElementById('pollOltBtn');
    if (btn) { btn.disabled = true; btn.textContent = '📡 Polling...'; }
    try {
        const res = await API.onu.poll(selectedOlt);
        await loadOnuData();
        if (res && res.message) console.info(res.message);
    } catch (e) {
        alert('Poll failed: ' + e.message);
    } finally {
        const b = document.getElementById('pollOltBtn');
        if (b) { b.disabled = false; b.textContent = '📡 Poll now'; }
    }
}

// Group ONU by OLT
function groupByOlt() {
    const oltMap = {};

    onuData.forEach(onu => {
        const oltId = onu.olt_id || 'unknown';
        if (!oltMap[oltId]) {
            oltMap[oltId] = {
                id: oltId,
                onus: [],
                online: 0,
                offline: 0,
                low_signal: 0,
                not_registered: 0,
                total: 0
            };
        }
        oltMap[oltId].onus.push(onu);
        oltMap[oltId].total++;

        if (onu.status === 'online') oltMap[oltId].online++;
        else if (onu.status === 'offline') oltMap[oltId].offline++;
        else if (onu.status === 'low_signal') oltMap[oltId].low_signal++;

        if (onu.registration === 'not_registered') oltMap[oltId].not_registered++;
    });

    oltsData = Object.values(oltMap);
}

// Show OLT List (main view)
function showOltList() {
    const container = document.getElementById('onuContainer');
    const header = document.getElementById('onuHeader');

    if (!container) return;

    // Header with refresh button
    header.innerHTML = `
        <div class="onu-toolbar">
            <h3>📡 OLT Devices</h3>
            <button class="refresh-btn" id="refreshOnuBtn">🔄 Refresh</button>
        </div>
    `;

    document.getElementById('refreshOnuBtn')?.addEventListener('click', loadOnuData);

    if (oltsData.length === 0) {
        container.innerHTML = '<div class="onu-empty">No OLT devices found. Check configuration.</div>';
        return;
    }

    // Calculate totals
    const totalStats = oltsData.reduce((acc, olt) => {
        acc.total += olt.total;
        acc.online += olt.online;
        acc.offline += olt.offline;
        acc.low_signal += olt.low_signal;
        acc.not_registered += olt.not_registered;
        return acc;
    }, { total: 0, online: 0, offline: 0, low_signal: 0, not_registered: 0 });

    container.innerHTML = `
        <div class="onu-total-stats">
            <span>Total: <strong>${totalStats.total}</strong> ONU</span>
            <span class="stat-online">● Online: <strong>${totalStats.online}</strong></span>
            <span class="stat-offline">● Offline: <strong>${totalStats.offline}</strong></span>
            <span class="stat-warning">● Low Signal: <strong>${totalStats.low_signal}</strong></span>
            <span class="stat-unreg">● Not registered: <strong>${totalStats.not_registered}</strong></span>
        </div>
        <div class="olt-grid">
            ${oltsData.map(olt => renderOltCard(olt)).join('')}
        </div>
    `;

    // Add click handlers
    document.querySelectorAll('.olt-card').forEach(card => {
        card.addEventListener('click', () => {
            selectedOlt = card.dataset.oltId;
            showOnuView();
        });
    });
}

// Render OLT Card
function renderOltCard(olt) {
    const healthClass = olt.offline > 0 ? 'has-offline' : (olt.low_signal > 0 ? 'has-warning' : 'all-ok');
    
    // Prevent division by zero
    const total = olt.total || 1; 

    const pctOnline = (olt.online / total) * 100;
    const pctOffline = (olt.offline / total) * 100;
    const pctLow = (olt.low_signal / total) * 100;

    const offsetOnline = 0;
    const offsetOffline = -pctOnline;
    const offsetLow = -(pctOnline + pctOffline);

    return `
        <div class="olt-card ${healthClass}" data-olt-id="${olt.id}">
            <div class="olt-header">
                <span class="olt-icon">📡</span>
                <span class="olt-name">${escapeHtml(olt.id)}</span>
                <span class="olt-action">Click to view ONUs →</span>
            </div>
            
            <div class="olt-card-body">
                <div class="olt-stats-left">
                    <div class="olt-stat-group">
                        <div class="olt-stat-group-title">Overview</div>
                        <div class="olt-stat-row total">
                            <span class="olt-stat-dot total"></span>
                            <span class="olt-stat-label">Total</span>
                            <span class="olt-stat-value">${olt.total}</span>
                        </div>
                    </div>
                    
                    <div class="olt-stat-group">
                        <div class="olt-stat-group-title">Status</div>
                        <div class="olt-stat-row online">
                            <span class="olt-stat-dot online"></span>
                            <span class="olt-stat-label">Online</span>
                            <span class="olt-stat-value">${olt.online}</span>
                        </div>
                        <div class="olt-stat-row warning">
                            <span class="olt-stat-dot warning"></span>
                            <span class="olt-stat-label">Low Signal</span>
                            <span class="olt-stat-value">${olt.low_signal}</span>
                        </div>
                        <div class="olt-stat-row offline">
                            <span class="olt-stat-dot offline"></span>
                            <span class="olt-stat-label">Offline</span>
                            <span class="olt-stat-value">${olt.offline}</span>
                        </div>
                    </div>

                    <div class="olt-stat-group">
                        <div class="olt-stat-group-title">Registration</div>
                        <div class="olt-stat-row registered">
                            <span class="olt-stat-dot registered"></span>
                            <span class="olt-stat-label">Registered</span>
                            <span class="olt-stat-value">${olt.total - olt.not_registered}</span>
                        </div>
                        <div class="olt-stat-row unregistered">
                            <span class="olt-stat-dot unregistered"></span>
                            <span class="olt-stat-label">Not registered</span>
                            <span class="olt-stat-value">${olt.not_registered}</span>
                        </div>
                    </div>
                </div>
                
                <div class="olt-chart-right">
                    <svg class="olt-chart-svg" viewBox="0 0 42 42">
                        <circle cx="21" cy="21" r="15.9155" fill="transparent" stroke="var(--bg-inset)" stroke-width="6"></circle>
                        
                        ${pctOnline > 0 ? `<circle class="donut-segment" cx="21" cy="21" r="15.9155" fill="transparent" stroke="var(--success)" stroke-width="6" stroke-dasharray="${pctOnline} ${100 - pctOnline}" stroke-dashoffset="${offsetOnline}"></circle>` : ''}
                        
                        ${pctOffline > 0 ? `<circle class="donut-segment" cx="21" cy="21" r="15.9155" fill="transparent" stroke="var(--danger)" stroke-width="6" stroke-dasharray="${pctOffline} ${100 - pctOffline}" stroke-dashoffset="${offsetOffline}"></circle>` : ''}
                        
                        ${pctLow > 0 ? `<circle class="donut-segment" cx="21" cy="21" r="15.9155" fill="transparent" stroke="var(--warning)" stroke-width="6" stroke-dasharray="${pctLow} ${100 - pctLow}" stroke-dashoffset="${offsetLow}"></circle>` : ''}
                    </svg>
                </div>
            </div>
        </div>
    `;
}

// Show ONU View for selected OLT
function showOnuView() {
    const container = document.getElementById('onuContainer');
    const header = document.getElementById('onuHeader');

    if (!container || !selectedOlt) return;

    const olt = oltsData.find(o => o.id === selectedOlt);
    if (!olt) return;

    // Header with back button, search, filters
    header.innerHTML = `
        <div class="onu-toolbar">
            <div class="onu-toolbar-left">
                <button class="back-btn" id="backToOltsBtn">← Back</button>
                <h3>📡 ${escapeHtml(selectedOlt)}</h3>
                <span class="onu-count">(${olt.total} ONUs)</span>
            </div>
            <div class="onu-toolbar-right">
                ${canPollOlt() ? `<button class="refresh-btn" id="pollOltBtn" title="Force a poll of this OLT">📡 Poll now</button>` : ''}
                <button class="refresh-btn" id="refreshOnuBtn">🔄 Refresh</button>
            </div>
        </div>
        <div class="onu-toolbar-row">
            <div class="onu-search">
                <input type="text" id="onuSearchInput" placeholder="🔍 Search by name, port, MAC, serial..." value="${escapeHtml(onuSearch)}">
            </div>
            <div class="onu-filters">
                <button class="filter-btn ${onuFilter === 'all' ? 'active' : ''}" data-filter="all">All</button>
                <button class="filter-btn ${onuFilter === 'online' ? 'active' : ''}" data-filter="online">Online</button>
                <button class="filter-btn ${onuFilter === 'offline' ? 'active' : ''}" data-filter="offline">Offline</button>
                <button class="filter-btn ${onuFilter === 'low_signal' ? 'active' : ''}" data-filter="low_signal">Low Signal</button>
                <button class="filter-btn ${onuFilter === 'not_registered' ? 'active' : ''}" data-filter="not_registered">Not registered</button>
            </div>
        </div>
    `;

    // Event handlers
    document.getElementById('backToOltsBtn')?.addEventListener('click', () => {
        selectedOlt = null;
        onuSearch = '';
        onuFilter = 'all';
        showOltList();
    });

    document.getElementById('refreshOnuBtn')?.addEventListener('click', loadOnuData);

    document.getElementById('pollOltBtn')?.addEventListener('click', pollSelectedOlt);

    document.getElementById('onuSearchInput')?.addEventListener('input', (e) => {
        onuSearch = e.target.value.toLowerCase();
        renderOnuList();
    });

    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            onuFilter = btn.dataset.filter;
            renderOnuList();
        });
    });

    renderOnuList();
}

// Render ONU List
function renderOnuList() {
    const container = document.getElementById('onuContainer');
    if (!container || !selectedOlt) return;

    const olt = oltsData.find(o => o.id === selectedOlt);
    if (!olt) return;

    let filteredData = [...olt.onus];

    if (onuFilter === 'not_registered') {
        // registration filter, not a status filter
        filteredData = filteredData.filter(onu => onu.registration === 'not_registered');
    } else if (onuFilter !== 'all') {
        filteredData = filteredData.filter(onu => onu.status === onuFilter);
    }

    if (onuSearch) {
        filteredData = filteredData.filter(onu => {
            const desc = (onu.description || '').toLowerCase();
            const port = (onu.port || '').toLowerCase();
            const onuId = (onu.onu_id || '').toString();
            const sn = (onu.serial_number || '').toLowerCase();
            const mac = (onu.mac_address || '').toLowerCase().replace(/:/g, '');
            const searchTerm = onuSearch.replace(/:/g, '');
            return desc.includes(onuSearch) || port.includes(onuSearch) || onuId.includes(onuSearch) || sn.includes(onuSearch) || mac.includes(searchTerm);
        });
    }

    filteredData.sort((a, b) => {
        const parsePort = (p) => (p || '').match(/\d+/g)?.map(Number) || [];
        const pA = parsePort(a.port);
        const pB = parsePort(b.port);

        for (let i = 0; i < Math.max(pA.length, pB.length); i++) {
            const valA = pA[i] || 0;
            const valB = pB[i] || 0;
            if (valA !== valB) {
                return valA - valB;
            }
        }
        return parseInt(a.onu_id || 0) - parseInt(b.onu_id || 0);
    });

    if (filteredData.length === 0) {
        container.innerHTML = '<div class="onu-empty">No ONU devices match your filter</div>';
        return;
    }

    let listHtml = '';
    let currentBasePort = null;

    filteredData.forEach((onu, index) => {
        const basePort = (onu.port || '').split(':')[0] || 'Unknown';
        
        if (basePort !== currentBasePort) {
            if (currentBasePort !== null) {
                listHtml += `</div>`;
            }
            listHtml += `<div class="onu-port-group">`;
            currentBasePort = basePort;
        }
        
        listHtml += renderOnuRow(onu);
        
        if (index === filteredData.length - 1) {
            listHtml += `</div>`;
        }
    });

    container.innerHTML = `
        <div class="onu-list-header">
            <span class="col-id"></span>
            <span class="col-port">Port</span>
            <span class="col-client">Client</span>
            <span class="col-port-desc">Port Description</span>
            <span class="col-mac">MAC Address</span>
            <span class="col-sn">Serial Number</span>
            <span class="col-model">Model</span>
            <span class="col-signal">Rx / Tx Signal</span>
            <span class="col-status">Optical</span>
            <span class="col-reg">OLT Reg.</span>
        </div>
        <div class="onu-list">
            ${listHtml}
        </div>
    `;
}

// Render ONU Row
function renderOnuRow(onu) {
    const statusClass = onu.status || 'unknown';
    // `status` = optical signal presence, `registration` = presence on the OLT.
    // They are independent: an ONU can be registered with no light, or lit but
    // not registered. Both are rendered, never collapsed into one badge.
    const regClass = onu.registration || 'unknown';
    const signalClass = getSignalClass(onu.rx_power);

    const rxDisplay = onu.rx_power !== null && onu.rx_power !== undefined ? onu.rx_power.toFixed(1) : '—';
    const txDisplay = onu.tx_power !== null && onu.tx_power !== undefined ? onu.tx_power.toFixed(1) : '—';

    let rxWidth = 0;
    if (onu.rx_power !== null && onu.rx_power !== undefined) {
        const maxPower = onuThresholds.good;
        const minPower = -30;
        rxWidth = Math.max(0, Math.min(100, ((onu.rx_power - minPower) / (maxPower - minPower)) * 100));
    }
    
    // Some OLT firmware never reports Tx power -> the field stays null for
    // every ONU on that OLT. That is expected, not a rendering bug.
    let txWidth = 0;
    if (onu.tx_power !== null && onu.tx_power !== undefined) {
        txWidth = Math.max(0, Math.min(100, (onu.tx_power + 2) * 14));
    }

    let reasonBadge = '';
    if (onu.offline_reason) {
        reasonBadge = `<span class="reason-badge">${escapeHtml(onu.offline_reason)}</span>`;
    }

    const icons = {
        'online': 'img/rj45-online.png',
        'low_signal': 'img/rj45-warning.png',
        'offline': 'img/rj45-offline.png'
    };
    
    const iconSrc = icons[statusClass] || 'img/rj45-default.png';

    const basePort = (onu.port || '').split(':')[0];
    const portDesc = basePort ? `Splitter Node ${basePort}` : '—';

    return `
        <div class="onu-row-item ${statusClass}">
            <div class="col-id">
                <img src="${iconSrc}" alt="ONU Status" class="onu-status-img ${statusClass}" style="width: 24px; height: 24px; object-fit: contain;">
            </div>
            
            <div class="col-port">
                <span class="port-badge" title="Physical Interface">${escapeHtml(onu.port || '—')}</span>
            </div>
            
            <div class="col-client">
                ${onu.description ? escapeHtml(onu.description) : '<span class="no-desc">—</span>'}
                ${onu.last_offline ? `<span class="last-offline" title="Last offline: ${escapeHtml(onu.last_offline)}">⏱️</span>` : ''}
            </div>

            <div class="col-port-desc" title="${escapeHtml(portDesc)}">${escapeHtml(portDesc)}</div>
            
            <div class="col-mac">${onu.mac_address || '—'}</div>
            <div class="col-sn">${onu.serial_number || '—'}</div>
            <div class="col-model">${onu.onu_type || '—'}</div>
            
            <div class="col-signal">
                <div class="metric-row">
                    <span class="metric-label">Rx</span>
                    <div class="metric-bar-container">
                        <div class="metric-bar-fill ${rxWidth > 0 ? signalClass : ''}" style="width: ${rxWidth}%"></div>
                    </div>
                    <span class="metric-val ${signalClass}">${rxDisplay}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">Tx</span>
                    <div class="metric-bar-container">
                        <div class="metric-bar-fill ${txWidth > 0 ? 'tx-fill' : ''}" style="width: ${txWidth}%"></div>
                    </div>
                    <span class="metric-val text-muted">${txDisplay}</span>
                </div>
            </div>

            <div class="col-status">
                <span class="status-badge ${statusClass}" title="Optical signal presence">${formatStatus(onu.status)}</span>
                ${reasonBadge}
            </div>

            <div class="col-reg">
                <span class="reg-badge ${regClass}" title="Registration on the OLT">${formatRegistration(onu.registration)}</span>
            </div>
        </div>
    `;
}

// Format Status
function formatStatus(status) {
    switch (status) {
        case 'online': return 'Online';
        case 'offline': return 'Offline';
        case 'low_signal': return 'Low Signal';
        default: return 'Unknown';
    }
}

// Format Registration (OLT registration state, independent of optical status)
function formatRegistration(registration) {
    switch (registration) {
        case 'registered': return 'Registered';
        case 'not_registered': return 'Not registered';
        default: return 'Unknown';
    }
}

// Get Signal Class
function getSignalClass(rxPower) {
    if (rxPower === null || rxPower === undefined) return '';
    if (rxPower >= onuThresholds.good) return 'signal-good';
    if (rxPower >= onuThresholds.warning) return 'signal-warning';
    return 'signal-critical';
}
