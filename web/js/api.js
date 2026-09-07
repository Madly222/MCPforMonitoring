/**
 * API Client for MCP Server Monitor
 * Path: ~/ServersMonitoringMCP/web/js/api.js
 *
 * Real backend client (the UI example shipped a mock; this replaces it).
 * Auth is cookie-based (session_id, httponly) -> every request uses
 * credentials: 'include'.
 */
const API = {
    baseUrl: '/api',

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;

        const response = await fetch(url, {
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });

        if (response.status === 401) {
            // Session died (in-memory sessions are dropped on service restart).
            // Fall back to the login view instead of throwing into the UI.
            const loginView = document.getElementById('login-view');
            const appView = document.getElementById('app-view');
            if (loginView && appView) {
                appView.classList.remove('active');
                loginView.classList.add('active');
            }
            throw new Error('Unauthorized');
        }

        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }

        return response.json();
    },

    // ---------------------------------------------------------------- Auth
    auth: {
        login(username, password) {
            return API.request('/auth/login', {
                method: 'POST',
                body: JSON.stringify({ username, password }),
            });
        },
        logout() {
            return API.request('/auth/logout', { method: 'POST' });
        },
        check() {
            return API.request('/auth/check');
        },
        me() {
            return API.request('/auth/me');
        },
    },

    // ------------------------------------------------------------- Servers
    servers: {
        list() {
            return API.request('/servers');
        },
        status() {
            return API.request('/status');
        },
        get(serverId) {
            return API.request(`/servers/${serverId}`);
        },
        info(serverId) {
            return API.request(`/servers/${serverId}/info`);
        },
        reconnect(serverId) {
            return API.request(`/servers/${serverId}/reconnect`, { method: 'POST' });
        },
        autoCheck() {
            return API.request('/settings/auto-check');
        },
        action(serverId, serviceType, action) {
            return API.request(`/servers/${serverId}/action`, {
                method: 'POST',
                body: JSON.stringify({
                    server_id: serverId,
                    service_type: serviceType,
                    action: action,
                }),
            });
        },
        diagnostic(serverId, serviceType, diagnosticName) {
            return API.request(
                `/servers/${serverId}/services/${serviceType}/diagnostics/${diagnosticName}`
            );
        },
        checkUpdates(serverId) {
            return API.request(`/servers/${serverId}/updates/check`, { method: 'POST' });
        },
    },

    // ----------------------------------------------------------------- ONU
    onu: {
        status() {
            return API.request('/onu/status');
        },
        olts() {
            return API.request('/onu/olts');
        },
        olt(oltId) {
            return API.request(`/onu/olt/${oltId}`);
        },
        // admin + superadmin only
        poll(oltId) {
            return API.request(`/onu/olt/${oltId}/poll`, { method: 'POST' });
        },
    },

    // ------------------------------------------------- ACC (water) monitoring
    acc: {
        status() {
            return API.request('/acc/status');
        },
        check() {
            return API.request('/acc/check', { method: 'POST' });
        },
    },

    // ---------------------------------------------------- Electric monitoring
    electric: {
        status() {
            return API.request('/electric/status');
        },
        check() {
            return API.request('/electric/check', { method: 'POST' });
        },
    },

    // ------------------------------------------------------------ Monitoring
    monitoring: {
        status() {
            return API.request('/monitoring/status');
        },
        errors(params = {}) {
            const qs = new URLSearchParams(params).toString();
            return API.request(`/monitoring/errors${qs ? '?' + qs : ''}`);
        },
        health() {
            return API.request('/monitoring/health');
        },
    },

    // --------------------------------------------------------------- Updates
    updates: {
        status() {
            return API.request('/updates/status');
        },
        refresh() {
            return API.request('/updates/refresh', { method: 'POST' });
        },
    },

    // -------------------------------------------------------------- Commands
    commands: {
        execute(command) {
            return API.request('/execute', {
                method: 'POST',
                body: JSON.stringify({ command }),
            });
        },
    },

    // ----------------------------------------------------------- Raw console
    console: {
        exec(server_id, command, sudo) {
            return API.request('/console/exec', {
                method: 'POST',
                body: JSON.stringify({ server_id, command, sudo: !!sudo }),
            });
        },
    },

    // ---------------------------------------------------------------- Claude
    claude: {
        health() {
            return API.request('/claude/health');
        },
    },

    // ---------------------------------------------------------------- NetBox
    netbox: {
        health() {
            return API.request('/netbox/health');
        },
    },

    // --------------------------------------------------------------- Service
    service: {
        // superadmin only
        restart() {
            return API.request('/service/restart', { method: 'POST' });
        },
    },

    // ---------------------------------------------------- Admin (superadmin)
    admin: {
        listUsers() {
            return API.request('/admin/users');
        },
        createUser(username, password, role) {
            return API.request('/admin/users', {
                method: 'POST',
                body: JSON.stringify({ username, password, role }),
            });
        },
        deleteUser(username) {
            return API.request(`/admin/users/${encodeURIComponent(username)}`, {
                method: 'DELETE',
            });
        },
        setPassword(username, password) {
            return API.request(`/admin/users/${encodeURIComponent(username)}/password`, {
                method: 'PUT',
                body: JSON.stringify({ password }),
            });
        },
        setRole(username, role) {
            return API.request(`/admin/users/${encodeURIComponent(username)}/role`, {
                method: 'PUT',
                body: JSON.stringify({ role }),
            });
        },
        audit(params = {}) {
            const qs = new URLSearchParams(params).toString();
            return API.request(`/admin/audit${qs ? '?' + qs : ''}`);
        },

        getNotifications(channel) {
            return API.request(`/admin/config/notifications/${channel}`);
        },
        saveNotifications(channel, cfg) {
            return API.request(`/admin/config/notifications/${channel}`, {
                method: 'PUT',
                body: JSON.stringify(cfg),
            });
        },

        getAccPattern() {
            return API.request('/admin/config/acc-pattern');
        },
        saveAccPattern(pattern) {
            return API.request('/admin/config/acc-pattern', {
                method: 'PUT',
                body: JSON.stringify({ pattern }),
            });
        },

        getSchedule(channel) {
            return API.request(`/admin/config/schedule/${channel}`);
        },
        saveSchedule(channel, time) {
            return API.request(`/admin/config/schedule/${channel}`, {
                method: 'PUT',
                body: JSON.stringify({ time }),
            });
        },

        getElectricAddresses() {
            return API.request('/admin/config/electric-addresses');
        },
        saveElectricAddresses(addresses) {
            return API.request('/admin/config/electric-addresses', {
                method: 'PUT',
                body: JSON.stringify({ addresses }),
            });
        },

        reseedFromFile(section) {
            return API.request('/admin/config/reseed', {
                method: 'POST',
                body: JSON.stringify({ section }),
            });
        },

        getEnv() {
            return API.request('/admin/config/env');
        },
        saveEnv(values) {
            return API.request('/admin/config/env', {
                method: 'PUT',
                body: JSON.stringify({ values }),
            });
        },

        getDnsZone() {
            return API.request('/admin/config/dns-zone');
        },
        saveDnsZone(zone) {
            return API.request('/admin/config/dns-zone', {
                method: 'PUT',
                body: JSON.stringify({ zone }),
            });
        },

        getSshTimeout() {
            return API.request('/admin/config/ssh-timeout');
        },
        saveSshTimeout(seconds) {
            return API.request('/admin/config/ssh-timeout', {
                method: 'PUT',
                body: JSON.stringify({ seconds }),
            });
        },

        getCommandTimeout() {
            return API.request('/admin/config/command-timeout');
        },
        saveCommandTimeout(seconds) {
            return API.request('/admin/config/command-timeout', {
                method: 'PUT',
                body: JSON.stringify({ seconds }),
            });
        },

        getAutoCheck() {
            return API.request('/admin/config/auto-check');
        },
        saveAutoCheck(enabled, interval_seconds) {
            return API.request('/admin/config/auto-check', {
                method: 'PUT',
                body: JSON.stringify({ enabled, interval_seconds }),
            });
        },

        listServers() {
            return API.request('/admin/config/servers');
        },
        serviceTypes() {
            return API.request('/admin/config/service-types');
        },
        createServer(s) {
            return API.request('/admin/config/servers', {
                method: 'POST',
                body: JSON.stringify(s),
            });
        },
        editServer(id, s) {
            return API.request(`/admin/config/servers/${id}`, {
                method: 'PUT',
                body: JSON.stringify(s),
            });
        },
        deleteServer(id) {
            return API.request(`/admin/config/servers/${id}`, { method: 'DELETE' });
        },

        listOlts() {
            return API.request('/admin/config/olts');
        },
        createOlt(o) {
            return API.request('/admin/config/olts', {
                method: 'POST',
                body: JSON.stringify(o),
            });
        },
        editOlt(id, o) {
            return API.request(`/admin/config/olts/${id}`, {
                method: 'PUT',
                body: JSON.stringify(o),
            });
        },
        deleteOlt(id) {
            return API.request(`/admin/config/olts/${id}`, { method: 'DELETE' });
        },

        reloadConfig() {
            return API.request('/admin/config/reload', { method: 'POST' });
        },
    },
};
