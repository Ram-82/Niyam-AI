/**
 * Niyam AI - Frontend Configuration
 *
 * API_URL is auto-detected: localhost in dev, production URL otherwise.
 */
const CONFIG = {
    API_URL: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'http://localhost:8001/api'
        : 'https://niyam-ai.onrender.com/api',
};

// Export for use in scripts if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}
