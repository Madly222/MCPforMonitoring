/**
 * API Client for MCP Server Monitor
 */
const API = {
    baseUrl: '/api',

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;

        const defaultOptions = {
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
            },
        };
        const response = await fetch(url, { ...defaultOptions, ...options });
        if (response.status === 401) {
            window.location.href = '/login.html';
            throw new Error('Unauthorized');
        }
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `HTTP ${response.status}`);
        }
        return response.json();
    },

    // Auth API
    auth: {
        async login(username, password) {
            return API.request('/auth/login', {
                method: 'POST',
                body: JSON.stringify({ username, password }),
            });
        },
        async logout() {
            return API.request('/auth/logout', { method: 'POST' });
        },
        async check() {
            return API.request('/auth/check');
        },
        async me() {
            return API.request('/auth/me');
        },
    },

    // Servers API
    servers: {
        async list() {
            return API.request('/servers');
        },
        async status() {
            return API.request('/status');
        },
        async reconnect(serverId) {
            return API.request(`/servers/${serverId}/reconnect`, { method: 'POST' });
        },
        async autoCheck() {
            return API.request('/settings/auto-check');
        },
        async get(serverId) {
            return API.request(`/servers/${serverId}`);
        },
        async action(serverId, serviceType, action) {
            return API.request(`/servers/${serverId}/action`, {
                method: 'POST',
                body: JSON.stringify({
                    server_id: serverId,
                    service_type: serviceType,
                    action: action,
                }),
            });
        },
        async diagnostic(serverId, serviceType, diagnosticName) {
            return API.request(
                `/servers/${serverId}/services/${serviceType}/diagnostics/${diagnosticName}`
            );
        },
    },

    // ONU Monitoring API
    onu: {
        async status() {
            return API.request('/onu/status');
        },
        async olts() {
            return API.request('/onu/olts');
        },
        async olt(oltId) {
            return API.request(`/onu/olt/${oltId}`);
        },
        async poll(oltId) {
            return API.request(`/onu/olt/${oltId}/poll`, { method: 'POST' });
        },
    },

    // ACC Water Monitoring API
    acc: {
        async status() {
            return API.request('/acc/status');
        },
        async check() {
            return API.request('/acc/check', { method: 'POST' });
        },
    },

    // Electric Monitoring API
    electric: {
        async status() {
            return API.request('/electric/status');
        },
        async check() {
            return API.request('/electric/check', { method: 'POST' });
        },
    },

    // Invoice Generator API
    invoice: {
        async generate() {
            return API.request('/invoice/generate', { method: 'POST' });
        },
    },

    // Commands API
    commands: {
        async execute(command) {
            return API.request('/execute', {
                method: 'POST',
                body: JSON.stringify({ command }),
            });
        },
    },

    // Raw SSH console
    console: {
        async exec(server_id, command, sudo) {
            return API.request('/console/exec', {
                method: 'POST',
                body: JSON.stringify({ server_id, command, sudo: !!sudo }),
            });
        },
    },

    // Claude health
    claude: {
        async health() {
            return API.request('/claude/health');
        },
    },

    // Admin API (superadmin only)
    admin: {
        async listUsers() {
            return API.request('/admin/users');
        },
        async createUser(username, password, role) {
            return API.request('/admin/users', {
                method: 'POST',
                body: JSON.stringify({ username, password, role }),
            });
        },
        async deleteUser(username) {
            return API.request(`/admin/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
        },
        async setPassword(username, password) {
            return API.request(`/admin/users/${encodeURIComponent(username)}/password`, {
                method: 'PUT',
                body: JSON.stringify({ password }),
            });
        },
        async setRole(username, role) {
            return API.request(`/admin/users/${encodeURIComponent(username)}/role`, {
                method: 'PUT',
                body: JSON.stringify({ role }),
            });
        },
        async audit(params = {}) {
            const q = new URLSearchParams();
            if (params.limit) q.set('limit', params.limit);
            if (params.username) q.set('username', params.username);
            if (params.action) q.set('action', params.action);
            if (params.since) q.set('since', params.since);
            const qs = q.toString();
            return API.request(`/admin/audit${qs ? '?' + qs : ''}`);
        },
        async getNotifications(channel) {
            return API.request(`/admin/config/notifications/${channel}`);
        },
        async saveNotifications(channel, cfg) {
            return API.request(`/admin/config/notifications/${channel}`, {
                method: 'PUT', body: JSON.stringify(cfg),
            });
        },
        async getAccPattern() {
            return API.request('/admin/config/acc-pattern');
        },
        async saveAccPattern(pattern) {
            return API.request('/admin/config/acc-pattern', {
                method: 'PUT', body: JSON.stringify({ pattern }),
            });
        },
        async getSchedule(channel) {
            return API.request(`/admin/config/schedule/${channel}`);
        },
        async saveSchedule(channel, time) {
            return API.request(`/admin/config/schedule/${channel}`, {
                method: 'PUT', body: JSON.stringify({ time }),
            });
        },
        async getElectricAddresses() {
            return API.request('/admin/config/electric-addresses');
        },
        async saveElectricAddresses(addresses) {
            return API.request('/admin/config/electric-addresses', {
                method: 'PUT', body: JSON.stringify({ addresses }),
            });
        },
        async listServers() { return API.request('/admin/config/servers'); },
        async serviceTypes() { return API.request('/admin/config/service-types'); },
        async getSshTimeout() { return API.request('/admin/config/ssh-timeout'); },
        async saveSshTimeout(seconds) {
            return API.request('/admin/config/ssh-timeout', {
                method: 'PUT',
                body: JSON.stringify({ seconds }),
            });
        },
        async getAutoCheck() { return API.request('/admin/config/auto-check'); },
        async saveAutoCheck(enabled, interval_seconds) {
            return API.request('/admin/config/auto-check', {
                method: 'PUT',
                body: JSON.stringify({ enabled, interval_seconds }),
            });
        },
        async createServer(s) {
            return API.request('/admin/config/servers', { method: 'POST', body: JSON.stringify(s) });
        },
        async editServer(id, s) {
            return API.request(`/admin/config/servers/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(s) });
        },
        async deleteServer(id) {
            return API.request(`/admin/config/servers/${encodeURIComponent(id)}`, { method: 'DELETE' });
        },
        async listOlts() { return API.request('/admin/config/olts'); },
        async createOlt(o) {
            return API.request('/admin/config/olts', { method: 'POST', body: JSON.stringify(o) });
        },
        async editOlt(id, o) {
            return API.request(`/admin/config/olts/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(o) });
        },
        async deleteOlt(id) {
            return API.request(`/admin/config/olts/${encodeURIComponent(id)}`, { method: 'DELETE' });
        },
    },

    async health() {
        return API.request('/health');
    },
};
