/* ============================================================
   Global UI module
   Loaded by every dashboard. Reads window.UI_ROLE for palette commands.
   Public API exposed as window.UI:
     UI.toast(msg, type, opts)
     UI.confirm(msg, opts) -> Promise<boolean>
     UI.showProcessing(opts) -> { hide() }
     UI.attachAISubmissionOverlay(form, opts)
     UI.debouncedFilter(input, items, getText, opts)
     UI.registerCommands([{ section, label, icon, run|url, keywords }])
     UI.openPalette() / UI.closePalette()
   Declarative hooks (no JS needed in templates):
     <form data-ui-confirm="message">      -> custom glass confirm before submit
     <form data-ui-ai-submit>               -> show AI processing overlay on submit
     <div  data-ui-flash-legacy>            -> hidden by JS (server flashes already shown as toasts)
     <script id="ui-flash-data" type="application/json">[[cat,msg],...]</script>
   ============================================================ */
(function () {
    "use strict";

    /* ---------- DOM utilities ---------- */
    function el(tag, attrs, html) {
        const node = document.createElement(tag);
        if (attrs) for (const [k, v] of Object.entries(attrs)) {
            if (k === 'class') node.className = v;
            else if (k === 'dataset') Object.assign(node.dataset, v);
            else node.setAttribute(k, v);
        }
        if (html != null) node.innerHTML = html;
        return node;
    }
    function escHtml(s) {
        return String(s ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    /* ============================================================
       1. TOAST SYSTEM
       ============================================================ */
    let toastHost = null;
    function ensureToastHost() {
        if (toastHost && document.body.contains(toastHost)) return toastHost;
        toastHost = document.getElementById('ui-toast-host');
        if (!toastHost) {
            toastHost = el('div', { id: 'ui-toast-host', class: 'fixed top-6 left-6 z-[9999] flex flex-col gap-4 pointer-events-none w-full max-w-sm' });
            document.body.appendChild(toastHost);
        }
        return toastHost;
    }
    const TOAST_ICONS = { 
        success: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>', 
        error: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>', 
        info: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>', 
        warning: '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>' 
    };
    
    const TOAST_COLORS = {
        success: 'border-emerald-500/30 bg-white/80 text-emerald-800 shadow-emerald-500/10 icon-emerald-600',
        error: 'border-rose-500/30 bg-white/80 text-rose-800 shadow-rose-500/10 icon-rose-600',
        warning: 'border-amber-500/30 bg-white/80 text-amber-800 shadow-amber-500/10 icon-amber-600',
        info: 'border-blue-500/30 bg-white/80 text-blue-800 shadow-blue-500/10 icon-blue-600'
    };

    function toast(message, type, opts) {
        type = type || 'info';
        opts = opts || {};
        const duration = opts.duration ?? 5000;
        const host = ensureToastHost();
        
        const colors = TOAST_COLORS[type] || TOAST_COLORS['info'];
        const parts = colors.split(' ');
        const borderColor = parts[0];
        const bgColor = parts[1];
        const textColor = parts[2];
        const shadowColor = parts[3];
        const iconColor = parts[4].replace('icon-', 'text-');
        const iconBg = parts[4].replace('icon-', 'bg-').replace('600', '100');

        const t = document.createElement('div');
        // Initial state: shifted left, opacity 0
        t.className = `pointer-events-auto flex items-start gap-3 p-4 rounded-2xl border ${borderColor} ${bgColor} backdrop-blur-xl shadow-xl ${shadowColor} transform -translate-x-[120%] opacity-0 transition-all duration-500 cubic-bezier(0.4, 0, 0.2, 1)`;
        
        t.innerHTML = `
            <div class="flex-shrink-0 w-8 h-8 rounded-full ${iconBg} ${iconColor} flex items-center justify-center shadow-sm">
                ${TOAST_ICONS[type] || TOAST_ICONS['info']}
            </div>
            <div class="flex-1 text-sm font-bold ${textColor} leading-snug mt-1.5">
                ${escHtml(message)}
            </div>
            <button class="flex-shrink-0 text-slate-400 hover:text-slate-600 transition ml-2 mt-1.5 focus:outline-none" aria-label="Dismiss">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
            </button>`;
            
        host.appendChild(t);
        
        // Trigger slide-in
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                t.classList.remove('-translate-x-[120%]', 'opacity-0');
                t.classList.add('translate-x-0', 'opacity-100');
            });
        });

        let dismissed = false;
        const dismiss = () => {
            if (dismissed) return;
            dismissed = true;
            // Trigger slide-out to left
            t.classList.remove('translate-x-0', 'opacity-100');
            t.classList.add('-translate-x-[120%]', 'opacity-0');
            setTimeout(() => t.remove(), 500);
        };
        
        t.querySelector('button').addEventListener('click', dismiss);
        if (duration > 0) setTimeout(dismiss, duration);
        return { dismiss };
    }

    function hydrateFlashesAsToasts() {
        const node = document.getElementById('ui-flash-data');
        if (node) {
            let messages = [];
            try { messages = JSON.parse(node.textContent || '[]'); } catch (_) {}
            document.querySelectorAll('[data-ui-flash-legacy]').forEach(n => n.classList.add('ui-flash-legacy'));
            messages.forEach(([category, msg], i) => {
                const type = category === 'success' ? 'success'
                           : category === 'error'   ? 'error'
                           : category === 'warning' ? 'warning'
                           : 'info';
                setTimeout(() => toast(msg, type), 100 + i * 140);
            });
        }

        // Also check sessionStorage for redirects from AJAX polling
        const storedMsg = sessionStorage.getItem('toast_msg');
        if (storedMsg) {
            const storedType = sessionStorage.getItem('toast_type') || 'success';
            sessionStorage.removeItem('toast_msg');
            sessionStorage.removeItem('toast_type');
            // Slight delay to let page settle
            setTimeout(() => toast(storedMsg, storedType), 200);
        }
    }

    /* ================================================================
       2. CONFIRM DIALOG (glass)
       ============================================================ */
    function confirmDialog(message, opts) {
        opts = opts || {};
        return new Promise(resolve => {
            const safe = !!opts.safe;
            const backdrop = el('div', { class: 'ui-confirm-backdrop' });
            backdrop.innerHTML = `
                <div class="ui-confirm" role="dialog" aria-modal="true">
                    <div class="ui-confirm-title">${escHtml(opts.title || 'Confirm action')}</div>
                    <div class="ui-confirm-message">${escHtml(message)}</div>
                    <div class="ui-confirm-actions">
                        <button class="ui-confirm-btn ui-confirm-btn--cancel">${escHtml(opts.cancelLabel || 'Cancel')}</button>
                        <button class="ui-confirm-btn ui-confirm-btn--confirm ${safe ? 'is-safe' : ''}">${escHtml(opts.confirmLabel || 'Delete')}</button>
                    </div>
                </div>`;
            document.body.appendChild(backdrop);
            requestAnimationFrame(() => backdrop.classList.add('is-visible'));

            const close = (v) => {
                backdrop.classList.remove('is-visible');
                document.removeEventListener('keydown', onKey);
                setTimeout(() => backdrop.remove(), 220);
                resolve(v);
            };
            const onKey = e => {
                if (e.key === 'Escape') close(false);
                else if (e.key === 'Enter') close(true);
            };
            backdrop.querySelector('.ui-confirm-btn--cancel').addEventListener('click', () => close(false));
            backdrop.querySelector('.ui-confirm-btn--confirm').addEventListener('click', () => close(true));
            backdrop.addEventListener('click', e => { if (e.target === backdrop) close(false); });
            document.addEventListener('keydown', onKey);
            backdrop.querySelector('.ui-confirm-btn--confirm').focus();
        });
    }

    /* ============================================================
       3. AI PROCESSING OVERLAY (full-screen skeleton)
       ============================================================ */
    let processingOverlay = null;
    function showProcessing(opts) {
        opts = opts || {};
        const title    = opts.title    || 'AI is analyzing your scan';
        const subtitle = opts.subtitle || 'Please wait…';
        const steps    = opts.steps    || ['Uploading image', 'Preprocessing', 'Running models', 'Compiling diagnosis'];

        if (processingOverlay) processingOverlay.remove();
        const overlay = el('div', { class: 'ui-processing-overlay' });
        overlay.innerHTML = `
            <div class="ui-processing-card">
                <div class="ui-processing-title"><span class="ui-pulse-dot"></span>${escHtml(title)}</div>
                <div class="ui-processing-subtitle">${escHtml(subtitle)}</div>
                <div class="ui-processing-steps">
                    ${steps.map((s, i) => `
                        <div class="ui-processing-step" data-step="${i}">
                            <div class="ui-step-marker"></div>
                            <span>${escHtml(s)}</span>
                        </div>`).join('')}
                </div>
                <div class="ui-processing-skeletons">
                    <div class="ui-skeleton" style="width: 92%;"></div>
                    <div class="ui-skeleton" style="width: 70%;"></div>
                    <div class="ui-skeleton" style="width: 84%;"></div>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        processingOverlay = overlay;
        requestAnimationFrame(() => overlay.classList.add('is-visible'));

        const stepEls = overlay.querySelectorAll('.ui-processing-step');
        let active = 0;
        const advance = () => {
            stepEls.forEach((s, i) => {
                s.classList.toggle('is-active', i === active);
                s.classList.toggle('is-done',   i <  active);
            });
        };
        advance();
        const interval = setInterval(() => {
            if (active < stepEls.length - 1) { active += 1; advance(); }
            else clearInterval(interval);
        }, 1400);

        return {
            hide() {
                clearInterval(interval);
                overlay.classList.remove('is-visible');
                setTimeout(() => overlay.remove(), 350);
                processingOverlay = null;
            }
        };
    }

    function attachAISubmissionOverlay(form, opts) {
        if (!form) return;
        form.addEventListener('submit', () => showProcessing(opts));
    }

    /* ============================================================
       4. DEBOUNCED CLIENT-SIDE FILTER
       ============================================================ */
    function debouncedFilter(input, items, getText, opts) {
        opts = opts || {};
        const delay = opts.delay ?? 120;
        const emptyEl = opts.emptyEl;
        const onCount = opts.onCount;
        let timer = null;
        const apply = () => {
            const q = input.value.trim().toLowerCase();
            let shown = 0;
            items.forEach(item => {
                const text = (getText(item) || '').toLowerCase();
                const visible = !q || text.includes(q);
                item.style.display = visible ? '' : 'none';
                if (visible) shown++;
            });
            if (emptyEl) emptyEl.style.display = shown === 0 ? '' : 'none';
            if (onCount) onCount(shown, q);
        };
        input.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(apply, delay);
        });
    }

    /* ============================================================
       5. COMMAND PALETTE
       ============================================================ */
    let paletteCommands = [];
    let paletteEl = null;
    let paletteFiltered = [];
    let paletteIndex = 0;

    function registerCommands(cmds) {
        if (!Array.isArray(cmds)) return;
        paletteCommands = paletteCommands.concat(cmds);
    }

    function openPalette() {
        if (paletteEl) return;
        const backdrop = el('div', { class: 'ui-palette-backdrop' });
        backdrop.innerHTML = `
            <div class="ui-palette" role="dialog" aria-modal="true">
                <div class="ui-palette-input-wrap">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                    <input class="ui-palette-input" type="text" placeholder="Type a command, jump anywhere…" autocomplete="off">
                    <span class="ui-palette-shortcut">ESC</span>
                </div>
                <div class="ui-palette-list" id="ui-palette-list"></div>
            </div>`;
        document.body.appendChild(backdrop);
        paletteEl = backdrop;
        requestAnimationFrame(() => {
            backdrop.classList.add('is-visible');
            backdrop.querySelector('.ui-palette-input').focus();
        });

        const input = backdrop.querySelector('.ui-palette-input');
        const list  = backdrop.querySelector('#ui-palette-list');

        function render(query) {
            query = (query || '').trim().toLowerCase();
            paletteFiltered = paletteCommands.filter(c => {
                if (!query) return true;
                const blob = (c.label + ' ' + (c.keywords || '') + ' ' + (c.section || '')).toLowerCase();
                return blob.includes(query);
            });
            paletteIndex = 0;
            if (paletteFiltered.length === 0) {
                list.innerHTML = `<div class="ui-palette-empty">No matching commands.</div>`;
                return;
            }
            const sections = {};
            paletteFiltered.forEach((c, i) => {
                const sec = c.section || 'Actions';
                (sections[sec] = sections[sec] || []).push({ ...c, _idx: i });
            });
            list.innerHTML = Object.entries(sections).map(([sec, items]) => `
                <div class="ui-palette-section-label">${escHtml(sec)}</div>
                ${items.map(it => `
                    <div class="ui-palette-item" data-idx="${it._idx}">
                        <div class="ui-palette-item-icon">${it.icon || '→'}</div>
                        <div>${escHtml(it.label)}</div>
                        ${it.meta ? `<div class="ui-palette-item-meta">${escHtml(it.meta)}</div>` : ''}
                    </div>`).join('')}
            `).join('');
            updateActive();
            list.querySelectorAll('.ui-palette-item').forEach(node => {
                node.addEventListener('click', () => execute(parseInt(node.dataset.idx, 10)));
                node.addEventListener('mouseenter', () => {
                    paletteIndex = parseInt(node.dataset.idx, 10);
                    updateActive();
                });
            });
        }

        function updateActive() {
            list.querySelectorAll('.ui-palette-item').forEach(n => {
                n.classList.toggle('is-active', parseInt(n.dataset.idx, 10) === paletteIndex);
            });
            const activeNode = list.querySelector('.ui-palette-item.is-active');
            if (activeNode) activeNode.scrollIntoView({ block: 'nearest' });
        }

        function execute(idx) {
            const cmd = paletteFiltered[idx];
            if (!cmd) return;
            closePalette();
            try {
                if (cmd.url) window.location.href = cmd.url;
                else if (typeof cmd.run === 'function') cmd.run();
            } catch (e) {
                console.error('palette command failed:', e);
            }
        }

        input.addEventListener('input', () => render(input.value));
        input.addEventListener('keydown', e => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                paletteIndex = Math.min(paletteFiltered.length - 1, paletteIndex + 1);
                updateActive();
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                paletteIndex = Math.max(0, paletteIndex - 1);
                updateActive();
            } else if (e.key === 'Enter') {
                e.preventDefault();
                execute(paletteIndex);
            } else if (e.key === 'Escape') {
                closePalette();
            }
        });
        backdrop.addEventListener('click', e => { if (e.target === backdrop) closePalette(); });

        render('');
    }

    function closePalette() {
        if (!paletteEl) return;
        const node = paletteEl;
        paletteEl = null;
        node.classList.remove('is-visible');
        setTimeout(() => node.remove(), 220);
    }

    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            if (paletteEl) closePalette();
            else openPalette();
        }
    });

    /* ============================================================
       Declarative hooks: data-ui-confirm + data-ui-ai-submit
       ============================================================ */
    document.addEventListener('submit', e => {
        const form = e.target;
        if (!(form instanceof HTMLFormElement)) return;

        // Guard: block oversized uploads client-side before they hit the
        // network (mirrors MAX_CONTENT_LENGTH) so the user gets an instant,
        // clear message instead of a silent 413.
        if (form.dataset.uiAiSubmit !== undefined) {
            const MAX_UPLOAD_BYTES = 16 * 1024 * 1024;
            const tooBig = Array.from(form.querySelectorAll('input[type="file"]'))
                .flatMap(inp => Array.from(inp.files))
                .find(f => f.size > MAX_UPLOAD_BYTES);
            if (tooBig) {
                e.preventDefault();
                toast(`"${tooBig.name}" is too large (max 16 MB).`, 'error');
                return;
            }
        }

        // 1) data-ui-confirm: intercept and show glass confirm dialog
        const confirmMsg = form.dataset.uiConfirm;
        if (confirmMsg && !form._uiConfirmed) {
            e.preventDefault();
            confirmDialog(confirmMsg, {
                title: form.dataset.uiConfirmTitle || 'Confirm action',
                confirmLabel: form.dataset.uiConfirmLabel || 'Delete',
                cancelLabel: 'Cancel'
            }).then(ok => {
                if (!ok) return;
                form._uiConfirmed = true;
                if (form.dataset.uiAiSubmit !== undefined) {
                    showProcessing();
                    fetch(form.action, { method: form.method || 'POST', body: new FormData(form) })
                        .then(res => res.json())
                        .then(data => {
                            if (data.report_id) pollReportStatus(data.report_id);
                            else window.location.reload();
                        })
                        .catch(() => window.location.reload());
                } else {
                    form.submit();
                }
            });
            return;
        }
        // 2) data-ui-ai-submit (no confirm needed): show overlay then let submit proceed
        if (form.dataset.uiAiSubmit !== undefined) {
            e.preventDefault();
            showProcessing();
            fetch(form.action, { method: form.method || 'POST', body: new FormData(form) })
                .then(res => res.json())
                .then(data => {
                    if (data.report_id) pollReportStatus(data.report_id);
                    else window.location.reload();
                })
                .catch(() => window.location.reload());
        }
    }, true);
    
    function pollReportStatus(reportId) {
        const interval = setInterval(() => {
            fetch(`/upload/status/${reportId}`)
                .then(res => res.json())
                .then(data => {
                    if (data.status === 'COMPLETED' || data.status === 'ERROR') {
                        clearInterval(interval);
                        
                        // Pass toast to the next page load via sessionStorage
                        const msg = data.status === 'COMPLETED' ? (data.result ? `Scan Processed: ${data.result}` : 'Scan processed successfully!') : 'Scan processing failed.';
                        const type = data.status === 'COMPLETED' ? 'success' : 'error';
                        sessionStorage.setItem('toast_msg', msg);
                        sessionStorage.setItem('toast_type', type);
                        
                        if (data.redirect_url) window.location.href = data.redirect_url;
                        else window.location.reload();
                    }
                })
                .catch(err => {
                    clearInterval(interval);
                    window.location.reload();
                });
        }, 1500);
    }

    /* ============================================================
       Boot
       ============================================================ */
    function boot() {
        hydrateFlashesAsToasts();

        const role = (window.UI_ROLE || '').toLowerCase();
        const COMMON = [
            { section: 'Account', label: 'Logout', icon: '⏻', url: '/logout', keywords: 'sign out exit' }
        ];
        const ROLE_CMDS = {
            admin: [
                { section: 'Workspaces', label: 'Register New User',     icon: '+', keywords: 'add staff patient signup', run: () => clickWorkspace('register') },
                { section: 'Workspaces', label: 'Search Current Users',  icon: '⌕', keywords: 'find directory users',     run: () => { clickWorkspace('users'); focusEl('user-search-input'); } },
                { section: 'Workspaces', label: 'View Recent Scans',     icon: '◧', keywords: 'reports radiology scans',  run: () => { clickWorkspace('reports'); focusEl('report-search-input'); } },
                { section: 'Navigate',   label: 'Admin Dashboard',       icon: '⌂', url: '/admin' }
            ],
            doctor: [
                { section: 'Navigate', label: 'Doctor Workstation', icon: '⌂', url: '/doctor' },
                { section: 'Actions',  label: 'Open First Pending Case', icon: '◷', keywords: 'patient report next', run: () => {
                    const first = document.querySelector('.patient-card');
                    if (first) first.click();
                } }
            ],
            secretary: [
                { section: 'Navigate', label: 'Reception Desk',                 icon: '⌂', url: '/secretary' },
                { section: 'Actions',  label: 'Search & Select Patient',        icon: '⌕', keywords: 'upload scan find', run: () => focusEl('patient-search-input') },
                { section: 'Actions',  label: 'Filter Recent Registrations',   icon: '⌕', keywords: 'list patients',     run: () => focusEl('search-input') }
            ],
            patient: [
                { section: 'Navigate', label: 'Patient Portal',         icon: '⌂', url: '/patient' },
                { section: 'Actions',  label: 'Open Smart Assistant',   icon: '◌', keywords: 'chat help bot',     run: () => document.getElementById('chat-toggle')?.click() },
                { section: 'Actions',  label: 'Upload New X-Ray',       icon: '⇪', keywords: 'scan analyze',      run: () => {
                    const f = document.querySelector('form[action="/upload"] [name="scan_target"]');
                    if (f) { f.scrollIntoView({ behavior: 'smooth', block: 'center' }); f.focus(); }
                } }
            ]
        };
        registerCommands([...(ROLE_CMDS[role] || []), ...COMMON]);
        if (Array.isArray(window.UI_COMMANDS)) registerCommands(window.UI_COMMANDS);
    }

    function clickWorkspace(name) {
        const btn = document.querySelector(`[data-workspace="${name}"]`);
        if (btn) btn.click();
    }
    function focusEl(id) {
        const e = document.getElementById(id);
        if (!e) return;
        e.scrollIntoView({ behavior: 'smooth', block: 'center' });
        setTimeout(() => e.focus(), 200);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    /* ---------- Public API ---------- */
    window.UI = {
        toast,
        confirm: confirmDialog,
        showProcessing,
        attachAISubmissionOverlay,
        debouncedFilter,
        registerCommands,
        openPalette,
        closePalette
    };
})();
