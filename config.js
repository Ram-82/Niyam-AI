/**
 * Niyam AI - Frontend Configuration
 * 
 * For local development: Use '/api' if served by the backend, or 'http://localhost:8001/api' if served separately.
 * For production: Replace with your deployed Render/Cloud API URL.
 */
const CONFIG = {
    // API_URL: 'http://localhost:8001/api', // Use this if opening HTML files directly
    API_URL: '/api', // Use this when served by the backend (Recommended)
    // API_URL: 'https://niyam-api.onrender.com/api', // Example Production URL
};

// Export for use in scripts if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}
