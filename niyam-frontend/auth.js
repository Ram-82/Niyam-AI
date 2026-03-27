/**
 * Niyam AI - Authentication Utilities
 *
 * Provides:
 *   - niyamFetch(): drop-in replacement for fetch() that auto-attaches
 *     the Bearer token and transparently refreshes expired access tokens.
 *   - logout(): server-side token invalidation + localStorage cleanup.
 *   - isAuthenticated(): quick check for stored token.
 *   - getToken() / getRefreshToken(): accessors.
 */

const NiyamAuth = (() => {
    const TOKEN_KEY = 'niyam_access_token';
    const REFRESH_KEY = 'niyam_refresh_token';
    const USER_NAME_KEY = 'niyam_user_name';
    const BUSINESS_NAME_KEY = 'niyam_business_name';
    const USER_BUSINESS_KEY = 'niyam_user_business';

    let _refreshPromise = null; // Singleton to avoid concurrent refresh calls

    function getToken() {
        return localStorage.getItem(TOKEN_KEY);
    }

    function getRefreshToken() {
        return localStorage.getItem(REFRESH_KEY);
    }

    function setTokens(access, refresh) {
        if (access) localStorage.setItem(TOKEN_KEY, access);
        if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    }

    function isAuthenticated() {
        return !!getToken();
    }

    function clearAuth() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(REFRESH_KEY);
        localStorage.removeItem(USER_NAME_KEY);
        localStorage.removeItem(BUSINESS_NAME_KEY);
        localStorage.removeItem(USER_BUSINESS_KEY);
    }

    /**
     * Attempt to refresh the access token using the stored refresh token.
     * Returns true if refresh succeeded, false otherwise.
     */
    async function refreshAccessToken() {
        // Deduplicate concurrent refresh attempts
        if (_refreshPromise) return _refreshPromise;

        _refreshPromise = (async () => {
            const refreshToken = getRefreshToken();
            if (!refreshToken) return false;

            try {
                const apiUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_URL)
                    ? CONFIG.API_URL
                    : '/api';

                const resp = await fetch(`${apiUrl}/auth/refresh`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${refreshToken}`,
                        'Content-Type': 'application/json',
                    },
                });

                if (!resp.ok) return false;

                const result = await resp.json();
                if (result.success && result.data) {
                    setTokens(result.data.access_token, result.data.refresh_token);
                    return true;
                }
                return false;
            } catch (err) {
                console.error('Token refresh failed:', err);
                return false;
            } finally {
                _refreshPromise = null;
            }
        })();

        return _refreshPromise;
    }

    /**
     * Authenticated fetch wrapper.
     *
     * - Attaches Bearer token automatically.
     * - On 401, attempts one token refresh then retries the original request.
     * - On permanent auth failure, redirects to login.
     */
    async function niyamFetch(url, options = {}) {
        const token = getToken();
        const headers = { ...(options.headers || {}) };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        let response = await fetch(url, { ...options, headers });

        if (response.status === 401 && !options._isRetry) {
            const refreshed = await refreshAccessToken();
            if (refreshed) {
                // Retry with new token
                const newToken = getToken();
                headers['Authorization'] = `Bearer ${newToken}`;
                response = await fetch(url, { ...options, headers, _isRetry: true });
            } else {
                // Refresh failed — redirect to login
                clearAuth();
                window.location.href = 'login.html';
                return response;
            }
        }

        return response;
    }

    /**
     * Logout: invalidate token server-side, then clear local storage.
     */
    async function logout() {
        const token = getToken();
        if (token) {
            try {
                const apiUrl = (typeof CONFIG !== 'undefined' && CONFIG.API_URL)
                    ? CONFIG.API_URL
                    : '/api';

                await fetch(`${apiUrl}/auth/logout`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` },
                });
            } catch (err) {
                console.warn('Logout API call failed (token still cleared locally):', err);
            }
        }
        clearAuth();
        window.location.href = 'login.html';
    }

    return {
        getToken,
        getRefreshToken,
        setTokens,
        isAuthenticated,
        clearAuth,
        refreshAccessToken,
        niyamFetch,
        logout,
    };
})();

/**
 * Escape HTML entities to prevent XSS when inserting API data into innerHTML.
 * Use this for any user-controllable or API-sourced string inserted into HTML.
 */
function escapeHtml(str) {
    if (str == null) return '';
    const s = String(str);
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
