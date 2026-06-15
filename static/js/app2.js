/**
 * Stock Management System - Main Application Module
 * Handles UI interactions, search, and page-specific functionality
 */

// ===== Global State =====
const App = {
    searchTimeout: null,
    currentSearch: '',
    currentCategory: '',
};

// ===== Toast Notifications =====
function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    if (!toast) return;
    
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// ===== URL Query Parameters =====
function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        search: params.get('search') || '',
        category: params.get('category') || ''
    };
}

function updateURL(search, category) {
    const params = new URLSearchParams();
    if (search) params.set('search', search);
    if (category) params.set('category', category);
    
    const queryString = params.toString();
    const newURL = queryString ? `${window.location.pathname}?${queryString}` : window.location.pathname;
    
    window.history.replaceState({}, '', newURL);
}

// ===== Global Search =====
function initGlobalSearch() {
    const searchInput = document.getElementById('searchInput');
    const categoryFilter = document.getElementById('categoryFilter');
    const searchBtn = document.getElementById('searchBtn');
    
    if (!searchInput) return;
    
    // Load categories
    loadCategories();
    
    // Restore search state from URL
    const params = getQueryParams();
    if (params.search) {
        searchInput.value = params.search;
        App.currentSearch = params.search;
    }
    if (params.category) {
        App.currentCategory = params.category;
    }
    
    // Search on input change (debounced)
    searchInput.addEventListener('input', (e) => {
        clearTimeout(App.searchTimeout);
        App.searchTimeout = setTimeout(() => {
            performSearch(e.target.value, categoryFilter ? categoryFilter.value : '');
        }, 300);
    });
    
    // Search on Enter key
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(App.searchTimeout);
            performSearch(e.target.value, categoryFilter ? categoryFilter.value : '');
        }
    });
    
    // Search button click
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            clearTimeout(App.searchTimeout);
            performSearch(searchInput.value, categoryFilter ? categoryFilter.value : '');
        });
    }
    
    // Category filter change
    if (categoryFilter) {
        categoryFilter.addEventListener('change', (e) => {
            performSearch(searchInput.value, e.target.value);
        });
    }
}

async function loadCategories() {
    const categoryFilter = document.getElementById('categoryFilter');
    if (!categoryFilter || typeof API === 'undefined') return;
    
    try {
        const categories = await API.getCategories();
        
        // Clear existing options except "All Categories"
        categoryFilter.innerHTML = '<option value="">All Categories</option>';
        
        // Add categories
        categories.forEach(category => {
            const option = document.createElement('option');
            option.value = category;
            option.textContent = category;
            if (category === App.currentCategory) {
                option.selected = true;
            }
            categoryFilter.appendChild(option);
        });
    } catch (error) {
        console.error('Failed to load categories:', error);
    }
}

function performSearch(search, category) {
    App.currentSearch = search;
    App.currentCategory = category;
    
    // Update URL
    updateURL(search, category);
    
    // Trigger page-specific search handler
    if (typeof handleSearch === 'function') {
        handleSearch(search, category);
    }
}

// ===== Utility Functions =====
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function formatCurrency(amount) {
    return 'NPR ' + new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(amount || 0);
}

function formatNumber(num) {
    return new Intl.NumberFormat('en-US').format(num || 0);
}

// ===== Status Badge Helper =====
function getStatusBadge(status) {
    const statusClass = {
        'OK': 'badge-ok',
        'Near Low': 'badge-near',
        'Low': 'badge-low',
        'Out of Stock': 'badge-low'
    };
    return `<span class="badge ${statusClass[status] || 'badge-ok'}">${status}</span>`;
}

// ===== Initialize on DOM Ready =====
document.addEventListener('DOMContentLoaded', () => {
    initGlobalSearch();
});

// Make utility functions available globally
window.App = App;
window.showToast = showToast;
window.getQueryParams = getQueryParams;
window.formatCurrency = formatCurrency;
window.formatNumber = formatNumber;
window.getStatusBadge = getStatusBadge;
window.debounce = debounce;
