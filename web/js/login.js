/**
 * Login Page Handler
 */

document.addEventListener('DOMContentLoaded', async () => {
    // Check if already authenticated
    try {
        const response = await fetch('/api/auth/check', { credentials: 'include' });
        const data = await response.json();
        
        if (data.authenticated) {
            window.location.href = '/';
            return;
        }
    } catch (e) {
        // Not authenticated, continue with login page
    }

    const form = document.getElementById('loginForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const loginBtn = document.getElementById('loginBtn');
    const errorEl = document.getElementById('error');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const username = usernameInput.value.trim();
        const password = passwordInput.value;

        if (!username || !password) {
            errorEl.textContent = 'Please enter username and password';
            return;
        }

        loginBtn.disabled = true;
        loginBtn.textContent = 'Logging in...';
        errorEl.textContent = '';

        try {
            const response = await fetch('/api/auth/login', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ username, password }),
            });

            const data = await response.json();

            if (response.ok && data.success) {
                window.location.href = '/';
            } else {
                errorEl.textContent = data.detail || 'Invalid username or password';
                loginBtn.disabled = false;
                loginBtn.textContent = 'Login';
            }
        } catch (error) {
            errorEl.textContent = 'Connection error. Please try again.';
            loginBtn.disabled = false;
            loginBtn.textContent = 'Login';
        }
    });

    // Focus username input
    usernameInput.focus();
});
