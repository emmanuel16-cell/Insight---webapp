/**
 * PASSWORD TOGGLE SYSTEM
 * Automatically adds show/hide functionality to all inputs inside a .password-input-wrapper
 */

document.addEventListener('DOMContentLoaded', () => {
    initPasswordToggles();

    // Use MutationObserver to handle dynamically added forms/modals
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes.length) {
                initPasswordToggles();
            }
        });
    });

    observer.observe(document.body, { childList: true, subtree: true });
});

/**
 * Initialize all password toggles on the page
 */
function initPasswordToggles() {
    const wrappers = document.querySelectorAll('.password-input-wrapper');

    wrappers.forEach(wrapper => {
        // Skip if already initialized
        if (wrapper.dataset.initialized) return;

        const input = wrapper.querySelector('input[type="password"], input[type="text"]');
        const icon = wrapper.querySelector('.password-toggle-icon i');

        if (input && icon) {
            wrapper.addEventListener('click', (e) => {
                // Check if the click was on the icon
                if (e.target.closest('.password-toggle-icon')) {
                    togglePassword(input, icon);
                }
            });
            wrapper.dataset.initialized = "true";
        }
    });
}

/**
 * Toggle between password and text type
 */
function togglePassword(input, icon) {
    if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
    } else {
        input.type = 'password';
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
    }
}
