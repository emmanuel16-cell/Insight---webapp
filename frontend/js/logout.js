/**
 * logout.js
 * Include this in admin.html, demo.html (instructor), and student.html.
 * Wires up every element with id="logout" or class="logout-btn",
 * and also the "Logout" link inside .user-dropdown.
 */

async function doLogout() {
    try {
        await fetch("/api/auth/logout", {
            method: "POST",
            credentials: "same-origin",
        });
    } catch (_) {
        // even if request fails, still redirect
    }
    window.location.href = "/login";
}

document.addEventListener("DOMContentLoaded", () => {
    const handleLogout = (e) => {
        e.preventDefault();
        if (confirm("Are you sure you want to log out?")) {
            doLogout();
        }
    };

    // Target any element that looks like a logout trigger
    document.querySelectorAll(
        '#logout, #logoutBtn, .logout-btn, .user-dropdown a[href="#logout"]'
    ).forEach(el => {
        el.addEventListener("click", handleLogout);
    });

    // Also catch the plain "Logout" text link inside .user-dropdown
    document.querySelectorAll(".user-dropdown a").forEach(a => {
        if (a.textContent.trim().toLowerCase() === "logout") {
            a.addEventListener("click", handleLogout);
        }
    });
});