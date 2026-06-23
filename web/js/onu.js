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
let onuThresholds = { good: -20, warning: -25 };
let onuRefreshInterval = null;

// Initialize when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupOnuEventListeners();
});

// Tab Navigation
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
            container.innerHTML = `<div class="onu-empty">Failed to load: ${error.message}</div>`;
        }
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
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
                total: 0
            };
        }
        oltMap[oltId].onus.push(onu);
        oltMap[oltId].total++;
        
        if (onu.status === 'online') oltMap[oltId].online++;
        else if (onu.status === 'offline') oltMap[oltId].offline++;
        else if (onu.status === 'low_signal') oltMap[oltId].low_signal++;
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
        return acc;
    }, { total: 0, online: 0, offline: 0, low_signal: 0 });
    
    container.innerHTML = `
        <div class="onu-total-stats">
            <span>Total: <strong>${totalStats.total}</strong> ONU</span>
            <span class="stat-online">● Online: <strong>${totalStats.online}</strong></span>
            <span class="stat-offline">● Offline: <strong>${totalStats.offline}</strong></span>
            <span class="stat-warning">● Low Signal: <strong>${totalStats.low_signal}</strong></span>
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
    
    return `
        <div class="olt-card ${healthClass}" data-olt-id="${olt.id}">
            <div class="olt-header">
                <span class="olt-icon">📡</span>
                <span class="olt-name">${escapeHtml(olt.id)}</span>
            </div>
            <div class="olt-stats">
                <div class="olt-stat total">
                    <span class="olt-stat-value">${olt.total}</span>
                    <span class="olt-stat-label">Total</span>
                </div>
                <div class="olt-stat online">
                    <span class="olt-stat-value">${olt.online}</span>
                    <span class="olt-stat-label">Online</span>
                </div>
                <div class="olt-stat offline">
                    <span class="olt-stat-value">${olt.offline}</span>
                    <span class="olt-stat-label">Offline</span>
                </div>
                <div class="olt-stat warning">
                    <span class="olt-stat-value">${olt.low_signal}</span>
                    <span class="olt-stat-label">Low Signal</span>
                </div>
            </div>
            <div class="olt-action">Click to view ONUs →</div>
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
            <button class="refresh-btn" id="refreshOnuBtn">🔄 Refresh</button>
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
    
    // Apply status filter
    if (onuFilter !== 'all') {
        filteredData = filteredData.filter(onu => onu.status === onuFilter);
    }
    
    // Apply search filter
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
    
    // Sort by ONU ID (numeric)
    filteredData.sort((a, b) => {
        const aId = parseInt(a.onu_id) || 0;
        const bId = parseInt(b.onu_id) || 0;
        return aId - bId;
    });
    
    if (filteredData.length === 0) {
        container.innerHTML = '<div class="onu-empty">No ONU devices match your filter</div>';
        return;
    }
    
    container.innerHTML = `
        <div class="onu-list">
            <div class="onu-list-header">
                <span class="col-id">ONU</span>
                <span class="col-client">Client / Description</span>
                <span class="col-mac">MAC Address</span>
                <span class="col-sn">Serial Number</span>
                <span class="col-model">Model</span>
                <span class="col-signal">Rx / Tx</span>
                <span class="col-status">Status</span>
            </div>
            ${filteredData.map(onu => renderOnuRow(onu)).join('')}
        </div>
    `;
}

// Render ONU Row
function renderOnuRow(onu) {
    const statusClass = onu.status || 'unknown';
    const signalClass = getSignalClass(onu.rx_power);
    
    // Parse port: "1/1/3:5" -> port 3
    let portNum = '?';
    if (onu.port && onu.port.includes(':')) {
        const parts = onu.port.split('/');
        const lastPart = parts[parts.length - 1];
        portNum = lastPart.split(':')[0];
    }
    
    // Current values
    const rxDisplay = onu.rx_power !== null && onu.rx_power !== undefined 
        ? `${onu.rx_power.toFixed(1)}` 
        : '—';
    
    const txDisplay = onu.tx_power !== null && onu.tx_power !== undefined 
        ? `${onu.tx_power.toFixed(1)}` 
        : '—';
    
    // Average values (5 min)
    const rxAvgDisplay = onu.rx_power_avg !== null && onu.rx_power_avg !== undefined
        ? `${onu.rx_power_avg.toFixed(1)}`
        : '—';
    
    const txAvgDisplay = onu.tx_power_avg !== null && onu.tx_power_avg !== undefined
        ? `${onu.tx_power_avg.toFixed(1)}`
        : '—';
    
    // Format offline reason
    let reasonBadge = '';
    if (onu.offline_reason) {
        reasonBadge = `<span class="reason-badge">${escapeHtml(onu.offline_reason)}</span>`;
    }
    
    return `
        <div class="onu-row-item ${statusClass}">
            <div class="col-id">
                <span class="onu-status-dot ${statusClass}"></span>
                <strong>#${onu.onu_id}</strong>
                <span class="port-badge">P${portNum}</span>
            </div>
            <div class="col-client">
                ${onu.description ? escapeHtml(onu.description) : '<span class="no-desc">—</span>'}
                ${onu.last_offline ? `<span class="last-offline" title="Last offline: ${escapeHtml(onu.last_offline)}">⏱️</span>` : ''}
            </div>
            <div class="col-mac">${onu.mac_address || '—'}</div>
            <div class="col-sn">${onu.serial_number || '—'}</div>
            <div class="col-model">${onu.onu_type || '—'}</div>
            <div class="col-signal">
                <div class="signal-current">
                    <span class="${signalClass}">${rxDisplay}</span> / <span>${txDisplay}</span>
                </div>
                <div class="signal-avg" title="Average (5 min)">
                    avg: ${rxAvgDisplay} / ${txAvgDisplay}
                </div>
            </div>
            <div class="col-status">
                <span class="status-badge ${statusClass}">${formatStatus(onu.status)}</span>
                ${reasonBadge}
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

// Get Signal Class
function getSignalClass(rxPower) {
    if (rxPower === null || rxPower === undefined) return '';
    if (rxPower >= onuThresholds.good) return 'signal-good';
    if (rxPower >= onuThresholds.warning) return 'signal-warning';
    return 'signal-critical';
}

// Escape HTML
if (typeof escapeHtml === 'undefined') {
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}