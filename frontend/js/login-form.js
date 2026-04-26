/**
 * login-form.js  –  InSight Auth UI + API wiring
 *
 * Flow:
 *   Login      → POST /api/auth/login      → redirect by role
 *   Register   → POST /api/auth/register   → OTP screen
 *   OTP verify → POST /api/auth/register/verify → Info screen
 *   Info       → POST /api/auth/info       → Wait/success screen
 *   Forgot     → POST /api/auth/forgot     → OTP screen
 *   Forgot OTP → POST /api/auth/forgot/verify → New-password screen
 *   Reset pwd  → POST /api/auth/reset-password → back to login
 *   Resend OTP → POST /api/auth/resend
 */

const card = document.getElementById("login-card");

let _pendingEmail   = "";
let _pendingPurpose = "";

// ── HELPERS ──────────────────────────────────────────────

function showSection(id) {
    document.querySelectorAll(".form").forEach(el => {
        el.style.display = el.id === id ? "flex" : "none";
    });
}

function setBg(theme) {
    card.style.background = theme === "light" ? "#8ecae6" : "#023047";
}

function navigate(sectionId, bg) {
    showSection(sectionId);
    if (bg) setBg(bg);
}

function setError(inputEl, msg) {
    clearError(inputEl);
    inputEl.style.borderColor = "#ef4444";
    const err = document.createElement("span");
    err.className = "__err";
    err.style.cssText = "color:#ef4444;font-size:0.72rem;margin-top:2px;display:block";
    err.textContent = msg;
    inputEl.parentNode.insertBefore(err, inputEl.nextSibling);
}

function clearError(inputEl) {
    inputEl.style.borderColor = "";
    const next = inputEl.nextSibling;
    if (next && next.classList && next.classList.contains("__err")) next.remove();
}

function setButtonLoading(btn, loading) {
    if (loading) {
        btn.dataset.originalText = btn.textContent;
        btn.textContent = "Please wait…";
        btn.disabled = true;
    } else {
        btn.textContent = btn.dataset.originalText || btn.textContent;
        btn.disabled = false;
    }
}

async function apiPost(url, body) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",          // send/receive cookies
        body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Something went wrong");
    return data;
}

function getOtpValue(container) {
    return [...container.querySelectorAll(".otp-box")].map(b => b.value).join("");
}

function clearOtpBoxes(container) {
    container.querySelectorAll(".otp-box").forEach(b => {
        b.value = "";
        b.classList.remove("filled");
    });
}

// ── OTP BOX UX ───────────────────────────────────────────

function initOtpBoxes(container) {
    const boxes = container.querySelectorAll(".otp-box");
    boxes.forEach((box, i) => {
        box.addEventListener("input", () => {
            box.classList.toggle("filled", box.value !== "");
            if (box.value && i < boxes.length - 1) boxes[i + 1].focus();
        });
        box.addEventListener("keydown", e => {
            if (e.key === "Backspace" && !box.value && i > 0) {
                boxes[i - 1].focus();
                boxes[i - 1].value = "";
                boxes[i - 1].classList.remove("filled");
            }
        });
        box.addEventListener("keypress", e => {
            if (!/[0-9]/.test(e.key)) e.preventDefault();
        });
    });
}

function startResendTimer(timerId, seconds = 30) {
    const timerEl = document.getElementById(timerId);
    if (!timerEl) return;
    const countEl = timerEl.querySelector(".timer-count");
    timerEl.style.display = "block";
    let remaining = seconds;
    countEl.textContent = remaining;
    const interval = setInterval(() => {
        remaining--;
        countEl.textContent = remaining;
        if (remaining <= 0) { clearInterval(interval); timerEl.style.display = "none"; }
    }, 1000);
}

// ── DELEGATED NAV (data-show anchors) ────────────────────
document.addEventListener("click", e => {
    const link = e.target.closest("[data-show]");
    if (!link) return;
    e.preventDefault();
    navigate(link.dataset.show, link.dataset.bg);
});

// ── LOGIN ─────────────────────────────────────────────────
document.querySelector('[data-form="login"]')?.addEventListener("submit", async e => {
    e.preventDefault();
    const emailEl = document.getElementById("login-gmail");
    const passEl  = document.getElementById("login-password");
    const btn     = e.target.querySelector("button[type=submit]");

    [emailEl, passEl].forEach(clearError);
    setButtonLoading(btn, true);

    try {
        const data = await apiPost("/api/auth/login", {
            email:    emailEl.value.trim(),
            password: passEl.value,
        });
        window.location.href = data.redirect;
    } catch (err) {
        setButtonLoading(btn, false);
        setError(emailEl, err.message);
    }
});

// ── REGISTER ──────────────────────────────────────────────
document.getElementById("confirm")?.addEventListener("click", async e => {
    e.preventDefault();
    const emailEl  = document.getElementById("register-gmail");
    const passEl   = document.getElementById("register-password");
    const rePassEl = document.getElementById("register-re-password");
    const btn      = document.getElementById("confirm");

    [emailEl, passEl, rePassEl].forEach(clearError);

    if (passEl.value !== rePassEl.value) {
        setError(rePassEl, "Passwords do not match");
        return;
    }

    setButtonLoading(btn, true);
    try {
        const data = await apiPost("/api/auth/register", {
            email:            emailEl.value.trim(),
            password:         passEl.value,
            confirm_password: rePassEl.value,
        });
        _pendingEmail   = data.email;
        _pendingPurpose = "register";
        document.getElementById("otp-email-display").textContent = _pendingEmail;
        navigate("confirmation-form", "light");
    } catch (err) {
        setError(emailEl, err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── REGISTER OTP VERIFY ───────────────────────────────────
document.getElementById("proceed")?.addEventListener("click", async e => {
    e.preventDefault();
    const section = document.getElementById("confirmation-form");
    const otp     = getOtpValue(section);
    const btn     = document.getElementById("proceed");

    if (otp.length < 5) { alert("Please enter all 5 digits."); return; }

    setButtonLoading(btn, true);
    try {
        await apiPost("/api/auth/register/verify", {
            email: _pendingEmail, otp, purpose: "register",
        });
        clearOtpBoxes(section);
        await loadDepartments();
        navigate("information-form", "light");
    } catch (err) {
        alert(err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── ACCOUNT INFO ──────────────────────────────────────────
async function loadDepartments() {
    const deptSelect = document.getElementById("info-department");
    if (!deptSelect) return;
    try {
        const res = await fetch("/api/admin/departments");
        if (!res.ok) return;
        const depts = await res.json();
        // Keep only the placeholder
        deptSelect.innerHTML = '<option value="">Select Department</option>';
        depts.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.code;
            opt.textContent = `${d.code} - ${d.name}`;
            deptSelect.appendChild(opt);
        });
    } catch (err) {
        console.error("Failed to load departments:", err);
    }
}

document.querySelector('[data-form="info"]')?.addEventListener("submit", async e => {
    e.preventDefault();
    const btn = document.getElementById("information-proceed");

    const studentIdEl = document.getElementById("info-student-id");
    const firstNameEl = document.getElementById("info-first-name");
    const lastNameEl  = document.getElementById("info-last-name");
    const genderEl    = document.getElementById("info-gender");
    const deptEl      = document.getElementById("info-department");
    const contactEl   = document.getElementById("info-contact");
    const sectionEl   = document.getElementById("info-section");

    [studentIdEl, firstNameEl, lastNameEl, genderEl, deptEl, contactEl, sectionEl].forEach(clearError);

    // Combine department and section (e.g., BSCS-1A)
    const combinedSection = `${deptEl.value}-${sectionEl.value.trim()}`;

    setButtonLoading(btn, true);
    try {
        await apiPost("/api/auth/info", {
            email:      _pendingEmail,
            student_id: studentIdEl.value.trim(),
            first_name: firstNameEl.value.trim(),
            last_name:  lastNameEl.value.trim(),
            gender:     genderEl.value,
            department: deptEl.value,
            section:    combinedSection,
            contact:    contactEl.value.trim(),
        });
        navigate("wait-form", "dark");
    } catch (err) {
        alert(err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── FORGOT – send code ────────────────────────────────────
document.getElementById("forgot-confirm")?.addEventListener("click", async e => {
    e.preventDefault();
    const emailEl = document.getElementById("forgot-email");
    const btn     = document.getElementById("forgot-confirm");
    clearError(emailEl);

    setButtonLoading(btn, true);
    try {
        await apiPost("/api/auth/forgot", { email: emailEl.value.trim() });
        _pendingEmail   = emailEl.value.trim();
        _pendingPurpose = "forgot";
        document.getElementById("forgot-otp-email").textContent = _pendingEmail;
        navigate("forgot-confirmation-form", "dark");
    } catch (err) {
        setError(emailEl, err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── FORGOT OTP VERIFY ─────────────────────────────────────
document.getElementById("forgot-otp-proceed")?.addEventListener("click", async e => {
    e.preventDefault();
    const section = document.getElementById("forgot-confirmation-form");
    const otp     = getOtpValue(section);
    const btn     = document.getElementById("forgot-otp-proceed");

    if (otp.length < 5) { alert("Please enter all 5 digits."); return; }

    setButtonLoading(btn, true);
    try {
        await apiPost("/api/auth/forgot/verify", {
            email: _pendingEmail, otp, purpose: "forgot",
        });
        clearOtpBoxes(section);
        navigate("new-password-form", "dark");
    } catch (err) {
        alert(err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── NEW PASSWORD ──────────────────────────────────────────
document.querySelector('[data-form="reset-password"]')?.addEventListener("submit", async e => {
    e.preventDefault();
    const inputs   = e.target.querySelectorAll("input[type=password]");
    const newPass  = inputs[0].value;
    const confPass = inputs[1].value;
    const btn      = e.target.querySelector("button[type=submit]");

    if (newPass !== confPass) { alert("Passwords do not match"); return; }

    setButtonLoading(btn, true);
    try {
        await apiPost("/api/auth/reset-password", {
            email: _pendingEmail, new_password: newPass, confirm_password: confPass,
        });
        alert("Password reset successfully! Please log in.");
        navigate("login-form", "dark");
    } catch (err) {
        alert(err.message);
    } finally {
        setButtonLoading(btn, false);
    }
});

// ── RESEND OTP ────────────────────────────────────────────
document.addEventListener("click", async e => {
    const resend = e.target.closest(".resend-link");
    if (!resend) return;
    e.preventDefault();
    try {
        await apiPost("/api/auth/resend", {
            email: _pendingEmail, purpose: _pendingPurpose,
        });
        startResendTimer(resend.dataset.timer);
    } catch (err) {
        alert(err.message);
    }
});

// ── OTP INIT ──────────────────────────────────────────────
document.querySelectorAll(".form").forEach(section => {
    if (section.querySelector(".otp-box")) initOtpBoxes(section);
});