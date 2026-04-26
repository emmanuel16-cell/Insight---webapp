/**
 * add-account.js  –  InSight Admin: Create Account Modal
 * Email + role only — system auto-generates a temporary password.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', () => {

        const host     = document.getElementById('add-account');
        const closeBtn = document.getElementById('closeAddAccount');
        const cancelBtn= document.getElementById('aaCancel');
        const submitBtn= document.getElementById('aaSubmit');
        const roleTabs = document.querySelectorAll('.aa-role-tab');
        const msgEl    = document.getElementById('aaMessage');

        if (!host) return;

        let currentRole = 'instructor';

        /* ── OPEN / CLOSE ───────────────────────────────────── */
        function openModal() {
            host.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            resetForm();
        }
        function closeModal() {
            host.style.display = 'none';
            document.body.style.overflow = '';
        }

        document.getElementById('add-accountBtn')?.addEventListener('click', e => {
            e.preventDefault();
            e.stopImmediatePropagation();
            openModal();
        });
        document.querySelectorAll('[data-open-add-account]').forEach(btn => {
            btn.addEventListener('click', e => { e.preventDefault(); e.stopImmediatePropagation(); openModal(); });
        });

        closeBtn?.addEventListener('click', closeModal);
        cancelBtn?.addEventListener('click', closeModal);
        host.addEventListener('click', e => {
            if (e.target === host || e.target.id === 'addAccountOverlay') closeModal();
        });
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && host.style.display === 'flex') closeModal();
        });

        /* ── ROLE TABS ──────────────────────────────────────── */
        roleTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                roleTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                currentRole = tab.dataset.role;
            });
        });

        /* ── VALIDATE ───────────────────────────────────────── */
        function validate() {
            document.getElementById('aaEmail')?.classList.remove('error');
            const email = document.getElementById('aaEmail')?.value.trim();
            if (!email) {
                document.getElementById('aaEmail').classList.add('error');
                showMessage('Please enter an email address.', 'error');
                return false;
            }
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                document.getElementById('aaEmail').classList.add('error');
                showMessage('Please enter a valid email address.', 'error');
                return false;
            }
            return true;
        }

        /* ── SUBMIT ─────────────────────────────────────────── */
        submitBtn?.addEventListener('click', async () => {
            hideMessage();
            if (!validate()) return;

            const payload = {
                role:  currentRole,
                email: document.getElementById('aaEmail').value.trim(),
            };

            submitBtn.classList.add('loading');
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending invite…';

            try {
                const res = await fetch('/api/admin/create-account', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify(payload),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || `Error ${res.status}`);

                showMessage(
                    `<i class="fas fa-check-circle"></i> Invite sent! A temporary password has been emailed to <strong>${payload.email}</strong>.`,
                    'success'
                );
                setTimeout(closeModal, 2200);
            } catch (err) {
                showMessage(`<i class="fas fa-exclamation-circle"></i> ${err.message}`, 'error');
            } finally {
                submitBtn.classList.remove('loading');
                submitBtn.innerHTML = '<i class="fas fa-paper-plane"></i> <span>Create &amp; Send Invite</span>';
            }
        });

        /* ── HELPERS ────────────────────────────────────────── */
        function showMessage(html, type) {
            if (!msgEl) return;
            msgEl.innerHTML = html;
            msgEl.className = `aa-message ${type}`;
            msgEl.style.display = 'flex';
        }
        function hideMessage() { if (msgEl) msgEl.style.display = 'none'; }

        function resetForm() {
            roleTabs.forEach(t => t.classList.toggle('active', t.dataset.role === 'instructor'));
            currentRole = 'instructor';
            const emailEl = document.getElementById('aaEmail');
            if (emailEl) { emailEl.value = ''; emailEl.classList.remove('error'); }
            hideMessage();
        }

    });
})();