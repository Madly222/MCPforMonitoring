/**
 * router.js - SPA Routing and Layout Management
 */
document.addEventListener('DOMContentLoaded', async () => {
    
    const loginView = document.getElementById('login-view');
    const appView = document.getElementById('app-view');
    
    const loginForm = document.getElementById('loginForm');
    if(loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('login-username').value.trim();
            const password = document.getElementById('login-password').value;
            const btn = document.getElementById('loginBtn');
            const err = document.getElementById('error');
            
            btn.disabled = true; btn.textContent = 'Signing in...'; err.textContent = '';
            
            try {
                const res = await API.auth.login(username, password);
                if(res.success) {
                    window.location.reload();
                } else {
                    err.textContent = res.detail || 'Invalid credentials';
                }
            } catch (error) {
                err.textContent = 'Connection error';
            }
            btn.disabled = false; btn.textContent = 'Sign in';
        });
    }

    try {
        const authData = await API.auth.check();
        if (authData.authenticated) {
            loginView.classList.remove('active');
            appView.classList.add('active');
            
            document.getElementById('display-username').textContent = authData.username;
            document.getElementById('userRole').textContent = authData.role;

            // shared with app.js / onu.js for role-gated controls
            window.currentUser = { username: authData.username, role: authData.role };

            // Backend gating, mirrored here:
            //   /api/admin/*          -> require_superadmin
            //   /api/service/restart  -> superadmin only
            //   /api/onu/.../poll     -> require_admin (admin + superadmin), handled in onu.js
            if (authData.role === 'superadmin') {
                document.getElementById('adminTabBtn')?.classList.remove('hidden');
                document.getElementById('restartBtn')?.classList.remove('hidden');
            }
        } else {
            loginView.classList.add('active');
            appView.classList.remove('active');
        }
    } catch(e) {
        loginView.classList.add('active');
        appView.classList.remove('active');
    }

    const navItems = document.querySelectorAll('.nav-item');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const pageTitle = document.getElementById('current-page-title');

    const titles = {
        'tab-servers': { title: 'Server Monitoring', sub: 'Servers & Terminals Overview' },
        'tab-onu': { title: 'ONU Monitoring', sub: 'Optical Network Units Status' },
        'tab-netbox': { title: 'netbox Auto-Fill', sub: 'Device sync & configuration' },
        'tab-admin': { title: 'Settings', sub: 'Access & System Configuration' }
    };

    navItems.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            
            navItems.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            tabPanes.forEach(pane => pane.classList.remove('active'));
            document.getElementById(targetId).classList.add('active');

            if(titles[targetId]) {
                pageTitle.textContent = titles[targetId].title;
            }

            if (targetId === 'tab-onu' && typeof loadOnuData === 'function') {
                selectedOlt = null;
                onuSearch = '';
                onuFilter = 'all';
                loadOnuData();
            }

            if (targetId === 'tab-netbox' && typeof nbSwitchTab === 'function') {
                nbSwitchTab('single');
                
                ['nbDeviceInfo', 'nbPortTable', 'nbApplyLog', 'nbRouterInfo', 'nbScanLog', 'nbError'].forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.classList.add('hidden', 'nb-hidden');
                });
            }

            if (targetId === 'tab-admin' && typeof loadAdminData === 'function') {
                loadAdminData();
            }
        });
    });
});