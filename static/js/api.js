/**
 * Stock Management System - API Module
 * Handles all API calls to the Django REST Framework backend
 */

const API = {
    baseUrl: '/api',
    
    /**
     * Get CSRF token from cookie
     */
    getCsrfToken() {
        const name = 'csrftoken=';
        const decodedCookie = decodeURIComponent(document.cookie);
        const ca = decodedCookie.split(';');
        for (let i = 0; i < ca.length; i++) {
            let c = ca[i];
            while (c.charAt(0) === ' ') c = c.substring(1);
            if (c.indexOf(name) === 0) return c.substring(name.length, c.length);
        }
        return '';
    },
    
    /**
     * Generic fetch wrapper with error handling
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const csrfToken = this.getCsrfToken();
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            credentials: 'include',
        };
        
        const config = { ...defaultOptions, ...options };
        
        try {
            const response = await fetch(url, config);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.error || data.detail || 'An error occurred');
            }
            
            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },
    
    // ===== Product Endpoints =====
    
    /**
     * Get all products with optional search filter
     * @param {string} search - Search term for filtering by name or category
     * @param {string} category - Category filter
     */
    async getProducts(search = '', category = '') {
        let endpoint = '/products/';
        const params = new URLSearchParams();
        
        if (search) params.append('search', search);
        if (category) params.append('category', category);
        
        const queryString = params.toString();
        if (queryString) endpoint += `?${queryString}`;
        
        const data = await this.request(endpoint);
        // Handle paginated response (DRF default) or plain array
        return data.results || data;
    },
    
    /**
     * Get a single product by ID
     */
    async getProduct(id) {
        return this.request(`/products/${id}/`);
    },
    
    /**
     * Create a new product
     */
    async createProduct(productData) {
        return this.request('/products/', {
            method: 'POST',
            body: JSON.stringify(productData),
        });
    },
    
    /**
     * Update an existing product
     */
    async updateProduct(id, productData) {
        return this.request(`/products/${id}/`, {
            method: 'PUT',
            body: JSON.stringify(productData),
        });
    },
    
    /**
     * Delete a product
     */
    async deleteProduct(id) {
        return this.request(`/products/${id}/`, {
            method: 'DELETE',
        });
    },
    
    /**
     * Sell a product (deduct stock)
     */
    async sellProduct(id, quantity, note = '') {
        return this.request(`/products/${id}/sell/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },
    
    /**
     * Restock a product (add stock)
     */
    async restockProduct(id, quantity, note = '') {
        return this.request(`/products/${id}/restock/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },
    
    /**
     * Get all distinct categories
     */
    async getCategories() {
        return this.request('/products/categories/');
    },
    
    // ===== Variant Endpoints =====
    
    /**
     * Get all variants with optional product filter
     * @param {number} productId - Optional product ID to filter variants
     */
    async getVariants(productId = null) {
        let endpoint = '/variants/';
        if (productId) endpoint += `?product_id=${productId}`;
        return this.request(endpoint);
    },
    
    /**
     * Get a single variant by ID
     */
    async getVariant(id) {
        return this.request(`/variants/${id}/`);
    },
    
    /**
     * Create a new variant
     */
    async createVariant(variantData) {
        return this.request('/variants/', {
            method: 'POST',
            body: JSON.stringify(variantData),
        });
    },
    
    /**
     * Update an existing variant
     */
    async updateVariant(id, variantData) {
        return this.request(`/variants/${id}/`, {
            method: 'PATCH',
            body: JSON.stringify(variantData),
        });
    },
    
    /**
     * Delete a variant
     */
    async deleteVariant(id) {
        return this.request(`/variants/${id}/`, {
            method: 'DELETE',
        });
    },
    
    /**
     * Sell a variant (deduct stock)
     * @param {number} variantId - Variant ID
     * @param {number} quantity - Quantity to sell
     * @param {string} note - Optional note
     */
    async sellVariant(variantId, quantity, note = '') {
        return this.request(`/variants/${variantId}/sell/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },
    
    /**
     * Restock a variant (add stock)
     * @param {number} variantId - Variant ID
     * @param {number} quantity - Quantity to restock
     * @param {string} note - Optional note
     */
    async restockVariant(variantId, quantity, note = '') {
        return this.request(`/variants/${variantId}/restock/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },
    
    /**
     * Update variant min stock level
     * @param {number} variantId - Variant ID
     * @param {number} minStock - New min stock value
     */
    async updateVariantMinStock(variantId, minStock) {
        return this.request(`/variants/${variantId}/`, {
            method: 'PATCH',
            body: JSON.stringify({ min_stock: minStock }),
        });
    },
    
    /**
     * Update variant stock directly (set absolute value)
     * @param {number} variantId - Variant ID
     * @param {number} stock - New stock value
     */
    async updateVariantStock(variantId, stock) {
        return this.request(`/variants/${variantId}/`, {
            method: 'PATCH',
            body: JSON.stringify({ stock: stock }),
        });
    },
    
    // ===== Report Endpoints =====
    
    /**
     * Get revenue report
     * @param {string} period - 'daily', 'weekly', or 'monthly'
     */
    async getRevenueReport(period = 'daily') {
        return this.request(`/reports/revenue/?period=${period}`);
    },
    
    /**
     * Get top 5 products by units sold this week
     * @param {string} search - Optional search term to filter results
     */
    async getTopProducts(search = '') {
        let endpoint = '/reports/top-products/';
        if (search) endpoint += `?search=${encodeURIComponent(search)}`;
        return this.request(endpoint);
    },
    
    // ===== Excel Export =====
    
    /**
     * Export all products to Excel file
     */
    async exportToExcel() {
        window.open('/api/products/export/excel/', '_blank');
    },
    
    // ===== Google Sheets Integration =====
    
    /**
     * Sync products to Google Sheets
     * @param {string} sheetId - Google Sheet ID
     * @param {string} apiKey - Google API Key
     */
    async syncToGoogleSheets(sheetId, apiKey) {
        return this.request('/products/sync/google-sheets/', {
            method: 'POST',
            body: JSON.stringify({ sheet_id: sheetId, api_key: apiKey }),
        });
    },
    
    /**
     * Import products from Google Sheets
     * @param {string} sheetId - Google Sheet ID
     * @param {string} apiKey - Google API Key
     * @param {string} range - Sheet range (default: Sheet1!A1:I100)
     */
    async importFromGoogleSheets(sheetId, apiKey, range = 'Sheet1!A1:I100') {
        return this.request('/products/import/google-sheets/', {
            method: 'POST',
            body: JSON.stringify({ sheet_id: sheetId, api_key: apiKey, range: range }),
        });
    },
};

// Make API available globally
window.API = API;