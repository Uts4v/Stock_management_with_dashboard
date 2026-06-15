/**
 * Stock Management System - API Module
 * Handles all API calls to the Django REST Framework backend
 */

const API = {
    baseUrl: '/api',

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

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;

        const config = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken(),
                ...options.headers
            },
            ...options
        };

        try {
            const response = await fetch(url, config);
            const text = await response.text();

            let data = null;

            if (text && text.trim() !== '') {
                try {
                    data = JSON.parse(text);
                } catch {
                    data = { message: text };
                }
            }

            if (!response.ok) {
                throw new Error(
                    data?.error ||
                    data?.detail ||
                    data?.message ||
                    `HTTP Error ${response.status}`
                );
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    async getProducts(search = '', category = '') {
        let endpoint = '/products/';
        const params = new URLSearchParams();

        if (search) params.append('search', search);
        if (category) params.append('category', category);

        const queryString = params.toString();
        if (queryString) endpoint += `?${queryString}`;

        const data = await this.request(endpoint);
        return data?.results || data || [];
    },

    async getProduct(id) {
        return this.request(`/products/${id}/`);
    },

    async createProduct(productData) {
        return this.request('/products/', {
            method: 'POST',
            body: JSON.stringify(productData),
        });
    },

    async updateProduct(id, productData) {
        return this.request(`/products/${id}/`, {
            method: 'PUT',
            body: JSON.stringify(productData),
        });
    },

    async deleteProduct(id) {
        return this.request(`/products/${id}/`, {
            method: 'DELETE',
        });
    },

    async sellProduct(id, quantity, note = '') {
        return this.request(`/products/${id}/sell/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },

    async restockProduct(id, quantity, note = '') {
        return this.request(`/products/${id}/restock/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },

    async getCategories() {
        return this.request('/products/categories/');
    },

    async getVariants(productId = null) {
        let endpoint = '/variants/';
        if (productId) endpoint += `?product_id=${productId}`;
        return this.request(endpoint);
    },

    async getVariant(id) {
        return this.request(`/variants/${id}/`);
    },

    async createVariant(variantData) {
        return this.request('/variants/', {
            method: 'POST',
            body: JSON.stringify(variantData),
        });
    },

    async updateVariant(id, variantData) {
        return this.request(`/variants/${id}/`, {
            method: 'PATCH',
            body: JSON.stringify(variantData),
        });
    },

    async deleteVariant(id) {
        return this.request(`/variants/${id}/`, {
            method: 'DELETE',
        });
    },

    async sellVariant(variantId, quantity, note = '') {
        return this.request(`/variants/${variantId}/sell/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },

    async restockVariant(variantId, quantity, note = '') {
        return this.request(`/variants/${variantId}/restock/`, {
            method: 'POST',
            body: JSON.stringify({ quantity, note }),
        });
    },

    async updateVariantMinStock(variantId, minStock) {
        return this.request(`/variants/${variantId}/`, {
            method: 'PATCH',
            body: JSON.stringify({ min_stock: minStock }),
        });
    },

    async updateProductStock(productId, stock) {
        return this.request(`/products/${productId}/update-stock/`, {
            method: 'PATCH',
            body: JSON.stringify({ stock }),
        });
    },

    async updateProductMinStock(productId, minStock) {
        return this.request(`/products/${productId}/update_min_stock/`, {
            method: 'PATCH',
            body: JSON.stringify({ min_stock: minStock }),
        });
    },

    async updateVariantStock(variantId, stock) {
        return this.request(`/variants/${variantId}/update-stock/`, {
            method: 'PATCH',
            body: JSON.stringify({ stock }),
        });
    },

    async getRevenueReport(period = 'daily') {
        return this.request(`/reports/revenue/?period=${period}`);
    },

    async getTopProducts(search = '') {
        let endpoint = '/reports/top-products/';
        if (search) endpoint += `?search=${encodeURIComponent(search)}`;
        return this.request(endpoint);
    },

    async exportToExcel() {
        window.open('/api/products/export/excel/', '_blank');
    },

    async syncToGoogleSheets(sheetId, apiKey) {
        return this.request('/products/sync/google-sheets/', {
            method: 'POST',
            body: JSON.stringify({ sheet_id: sheetId, api_key: apiKey }),
        });
    },

    async importFromGoogleSheets(sheetId, apiKey, range = 'Sheet1!A1:I100') {
        return this.request('/products/import/google-sheets/', {
            method: 'POST',
            body: JSON.stringify({
                sheet_id: sheetId,
                api_key: apiKey,
                range: range
            }),
        });
    },
};

window.API = API;