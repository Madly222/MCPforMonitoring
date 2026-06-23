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

    async health() {
        return API.request('/health');
    },
};
