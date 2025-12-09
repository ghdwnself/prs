/**
 * PalletOptimizer Common JS
 * Handles UI interactions, Toasts, and Common Utilities
 */

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initDropZones();
});

// --- 1. Sidebar Active State ---
function initSidebar() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link');

    navLinks.forEach(link => {
        const href = link.getAttribute('href');
        // Simple check: if URL contains the href (e.g., 'mmd.html')
        if (currentPath.includes(href) || (currentPath === '/' && href === 'index.html')) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

// --- 2. Drag & Drop UI Logic ---
function initDropZones() {
    const dropZones = document.querySelectorAll('.drop-zone');
    
    dropZones.forEach(zone => {
        const input = zone.querySelector('input[type="file"]');
        
        // Click to open file dialog
        zone.addEventListener('click', () => {
            if(input) input.click();
        });

        // Drag over effect
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('dragover');
        });

        // Drag leave effect
        zone.addEventListener('dragleave', () => {
            zone.classList.remove('dragover');
        });

        // Drop effect
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            
            if (e.dataTransfer.files.length && input) {
                input.files = e.dataTransfer.files;
                // Trigger change event manually
                const event = new Event('change');
                input.dispatchEvent(event);
            }
        });

        // File selected feedback
        if(input) {
            input.addEventListener('change', () => {
                if (input.files.length > 0) {
                    const fileName = input.files[0].name;
                    const textEl = zone.querySelector('.drop-zone-text');
                    if(textEl) textEl.innerHTML = `<strong>Selected:</strong> ${fileName}`;
                }
            });
        }
    });
}

// --- 3. Toast Notification System ---
// Usage: showToast('Operation successful!', 'success');
window.showToast = function(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'ℹ️';
    if (type === 'success') icon = '✅';
    if (type === 'error') icon = '⚠️';

    toast.innerHTML = `
        <span style="font-size: 1.2rem;">${icon}</span>
        <div style="flex:1; font-size: 0.9rem; font-weight: 500;">${message}</div>
    `;

    container.appendChild(toast);

    // Remove after 3 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
};

// --- 4. Utility: Format Currency ---
window.formatCurrency = function(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
};

// --- 5. Utility: Format Date ---
window.formatDate = function(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric', 
        month: 'short', 
        day: 'numeric'
    });
};

// --- 6. Utility: Normalize Status ---
window.normalizeStatus = function(rawStatus) {
    if (!rawStatus) return 'warning';
    
    const status = String(rawStatus).toLowerCase();
    
    // Critical indicators
    if (status.includes('critical') || status.includes('action') || 
        status.includes('short') || status.includes('out of stock') || 
        status.includes('🚨')) {
        return 'critical';
    }
    
    // Warning indicators
    if (status.includes('warn') || status.includes('low') || 
        status.includes('needs') || status.includes('⚠️')) {
        return 'warning';
    }
    
    // OK indicators
    if (status.includes('ok') || status.includes('clear') || 
        status.includes('good') || status === 'ok') {
        return 'ok';
    }
    
    // Default to warning for unknown statuses
    return 'warning';
};

// --- 7. Utility: Get Status Display Text ---
window.getStatusDisplay = function(rawStatus) {
    if (!rawStatus) return 'Unknown';
    return String(rawStatus);
};