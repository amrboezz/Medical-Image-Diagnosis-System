(function () {
    /* ── Workspace toggling ───────────────────────────────────────
       One of: 'register' | 'users' | 'reports'. Default = users. */
    const WORKSPACE_PANELS = {
        register: document.getElementById('workspace-register'),
        users:    document.getElementById('workspace-users'),
        reports:  document.getElementById('workspace-reports'),
    };
    const workspaceBtns = document.querySelectorAll('.workspace-btn');

    function toggleWorkspace(name) {
        Object.entries(WORKSPACE_PANELS).forEach(([key, el]) => {
            if (!el) return;
            el.classList.toggle('hidden', key !== name);
        });
        workspaceBtns.forEach(btn => {
            btn.classList.toggle('is-active', btn.dataset.workspace === name);
        });
    }

    workspaceBtns.forEach(btn => {
        btn.addEventListener('click', () => toggleWorkspace(btn.dataset.workspace));
    });

    /* Default state on load: honour ?tab= if present, else show Users. */
    const _initTab = new URLSearchParams(window.location.search).get('tab');
    toggleWorkspace(WORKSPACE_PANELS[_initTab] ? _initTab : 'users');

    const ROLE_BADGES = {
        admin: 'bg-emerald-100 text-emerald-700',
        doctor: 'bg-blue-100 text-blue-700',
        secretary: 'bg-purple-100 text-purple-700',
        patient: 'bg-slate-100 text-slate-700',
    };

    // CSRF token for JS-rebuilt rows. Live-search re-renders the user table in
    // JS, so those delete forms must carry the same per-session token as the
    // server-rendered ones (read from a stable input that isn't re-rendered).
    const CSRF_TOKEN =
        document.querySelector('meta[name="csrf-token"]')?.content ||
        document.querySelector('input[name="csrf_token"]')?.value || '';

    const searchInput = document.getElementById('user-search-input');
    const tableBody = document.getElementById('user-table-body');
    const readMoreUsersContainer = document.getElementById('read-more-users-container');
    const filterLabel = document.getElementById('filter-label');
    const filterTerm = document.getElementById('filter-term');
    const clearBtn = document.getElementById('search-clear-btn');
    const spinner = document.getElementById('search-spinner');
    let debounceTimer = null;

    if (readMoreUsersContainer) {
        readMoreUsersContainer.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                document.querySelectorAll('.extra-user').forEach(row => row.classList.remove('hidden'));
                readMoreUsersContainer.style.display = 'none';
            }
        });
    }

    /* ── HTML escape utility ── */
    function esc(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ── Build a single <tr> from a user object ── */
    function buildRow(u, index) {
        const badgeClass = ROLE_BADGES[u.role] || ROLE_BADGES.patient;
        const roleName = u.role.charAt(0).toUpperCase() + u.role.slice(1);
        const emailHtml = u.email ? `<div class="text-slate-700 text-xs font-medium">${esc(u.email)}</div>` : '';
        const phoneHtml = u.phone ? `<div class="text-slate-400 text-xs mt-0.5">${esc(u.phone)}</div>` : '';
        const contact = (emailHtml || phoneHtml) ? emailHtml + phoneHtml : '<span class="text-slate-300 text-xs">—</span>';
        const genderHtml = u.gender ? `<div class="text-slate-700 text-xs font-bold">${esc(u.gender)}</div>` : '<div class="text-slate-300 text-xs">—</div>';
        const dobHtml = u.dob ? `<div class="text-slate-400 text-[10px] mt-0.5">${esc(u.dob)}</div>` : '';
        const demographics = genderHtml + dobHtml;
        const hiddenClass = index >= 10 ? 'hidden extra-user' : '';

        return `
<tr class="hover:bg-slate-50 transition ${hiddenClass}">
    <td class="px-6 py-4 font-mono text-slate-400 text-xs">#${u.id}</td>
    <td class="px-6 py-4 font-bold text-slate-800">${esc(u.full_name)}</td>
    <td class="px-6 py-4">
        <span class="${badgeClass} px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-wider">${roleName}</span>
    </td>
    <td class="px-6 py-4 font-mono text-slate-500">${esc(u.username)}</td>
    <td class="px-6 py-4">${demographics}</td>
    <td class="px-6 py-4">${contact}</td>
    <td class="px-6 py-4 text-right">
        <form action="/delete_user/${u.id}" method="POST"
              data-ui-confirm="Delete this user permanently? This cannot be undone."
              data-ui-confirm-title="Remove user"
              data-ui-confirm-label="Delete user">
            <input type="hidden" name="csrf_token" value="${CSRF_TOKEN}">
            <button type="submit"
                class="text-red-500 hover:text-red-700 font-bold hover:bg-red-50 px-3 py-1 rounded transition">Remove</button>
        </form>
    </td>
</tr>`;
    }

    /* ── Swap tbody content with a brief fade ── */
    function renderUsers(users, query) {
        tableBody.style.opacity = '0.35';
        tableBody.style.transition = 'opacity 0.12s';
        setTimeout(() => {
            tableBody.innerHTML = users.length
                ? users.map((u, i) => buildRow(u, i)).join('')
                : `<tr><td colspan="5" class="px-6 py-8 text-center text-slate-400 font-medium">No users found${query ? ` matching "<b>${esc(query)}</b>"` : ''}.</td></tr>`;

            if (readMoreUsersContainer) {
                readMoreUsersContainer.style.display = users.length > 10 ? 'block' : 'none';
            }

            tableBody.style.opacity = '1';
        }, 80);
    }

    /* ── Fetch from JSON API and update the page ── */
    async function fetchUsers(query) {
        spinner.classList.remove('hidden');
        try {
            const url = '/api/admin/users' + (query ? `?search=${encodeURIComponent(query)}` : '');
            const data = await fetch(url).then(r => r.json());
            renderUsers(data.users, data.query);

            /* filter label */
            if (query) {
                filterTerm.textContent = query;
                filterLabel.classList.remove('hidden');
            } else {
                filterLabel.classList.add('hidden');
            }

            /* clear button */
            clearBtn.classList.toggle('hidden', !query);

            /* keep URL bookmarkable */
            history.replaceState(null, '', query ? `/admin?search=${encodeURIComponent(query)}` : '/admin');
        } catch (err) {
            console.error('Live search failed:', err);
        } finally {
            spinner.classList.add('hidden');
        }
    }

    /* ── Wire up events ── */
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchUsers(searchInput.value.trim()), 280);
    });

    /* Enter / button click still works, no page reload */
    document.getElementById('user-search-form').addEventListener('submit', e => {
        e.preventDefault();
        clearTimeout(debounceTimer);
        fetchUsers(searchInput.value.trim());
    });

    /* Exposed globally for the Clear button's onclick */
    window.clearSearch = function () {
        searchInput.value = '';
        fetchUsers('');
        searchInput.focus();
    };

    /* ── Report Search Logic ── */
    const reportSearchInput = document.getElementById('report-search-input');
    const reportTableBody = document.getElementById('report-table-body');
    const readMoreReportsContainer = document.getElementById('read-more-reports-container');
    const reportFilterLabel = document.getElementById('report-filter-label');
    const reportFilterTerm = document.getElementById('report-filter-term');
    const reportClearBtn = document.getElementById('report-search-clear-btn');
    const reportSpinner = document.getElementById('report-search-spinner');
    let reportDebounceTimer = null;

    if (readMoreReportsContainer) {
        readMoreReportsContainer.addEventListener('click', (e) => {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                document.querySelectorAll('.extra-report').forEach(row => row.classList.remove('hidden'));
                readMoreReportsContainer.style.display = 'none';
            }
        });
    }

    function buildReportRow(r, index) {
        const hiddenClass = index >= 10 ? 'hidden extra-report' : '';
        let statusBadge = '';
        if (r.status === 'APPROVED') {
            statusBadge = '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-green-100 text-green-800">Approved ✓</span>';
        } else if (r.status === 'PRELIMINARY') {
            statusBadge = '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800">Preliminary ⚠️</span>';
        } else {
            statusBadge = '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold bg-slate-100 text-slate-800">Pending ⏳</span>';
        }

        return `
<tr class="hover:bg-slate-50 transition ${hiddenClass}">
    <td class="px-6 py-4 font-bold text-slate-500">#${r.id}</td>
    <td class="px-6 py-4 font-bold">${esc(r.full_name)}</td>
    <td class="px-6 py-4 uppercase text-slate-500">${esc(r.scan_type)}</td>
    <td class="px-6 py-4">${esc(r.ai_result || '')}</td>
    <td class="px-6 py-4">${statusBadge}</td>
</tr>`;
    }

    function renderReports(reports, query) {
        reportTableBody.style.opacity = '0.35';
        reportTableBody.style.transition = 'opacity 0.12s';
        setTimeout(() => {
            reportTableBody.innerHTML = reports.length
                ? reports.map((r, i) => buildReportRow(r, i)).join('')
                : `<tr><td colspan="5" class="px-6 py-8 text-center text-slate-500">No data available${query ? ` for "<b>${esc(query)}</b>"` : ''}.</td></tr>`;

            if (readMoreReportsContainer) {
                readMoreReportsContainer.style.display = reports.length > 10 ? 'block' : 'none';
            }

            reportTableBody.style.opacity = '1';
        }, 80);
    }

    async function fetchReports(query) {
        reportSpinner.classList.remove('hidden');
        try {
            const url = '/api/admin/reports' + (query ? `?search=${encodeURIComponent(query)}` : '');
            const data = await fetch(url).then(r => r.json());
            renderReports(data.reports, data.query);

            if (query) {
                reportFilterTerm.textContent = query;
                reportFilterLabel.classList.remove('hidden');
            } else {
                reportFilterLabel.classList.add('hidden');
            }

            reportClearBtn.classList.toggle('hidden', !query);

            const urlParams = new URLSearchParams(window.location.search);
            if (query) urlParams.set('reports_search', query);
            else urlParams.delete('reports_search');

            const path = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
            history.replaceState(null, '', path);
        } catch (err) {
            console.error('Live search failed:', err);
        } finally {
            reportSpinner.classList.add('hidden');
        }
    }

    if (reportSearchInput) {
        reportSearchInput.addEventListener('input', () => {
            clearTimeout(reportDebounceTimer);
            reportDebounceTimer = setTimeout(() => fetchReports(reportSearchInput.value.trim()), 280);
        });

        document.getElementById('report-search-form').addEventListener('submit', e => {
            e.preventDefault();
            clearTimeout(reportDebounceTimer);
            fetchReports(reportSearchInput.value.trim());
        });

        window.clearReportSearch = function () {
            reportSearchInput.value = '';
            fetchReports('');
            reportSearchInput.focus();
        };
    }

    /* ── Dynamic System Logs ── */
    const auditLogsWrapper = document.getElementById('audit-logs-wrapper');
    async function fetchLogs() {
        try {
            const data = await fetch('/api/admin/logs').then(r => r.json());
            if (data.logs && data.logs.length > 0) {
                const itemsHtml = data.logs.map(log => {
                    let itemClass = 'text-slate-300';
                    if (log.includes('SECURITY')) itemClass = 'text-emerald-400';
                    else if (log.includes('MEDICAL')) itemClass = 'text-sky-400';

                    return `<li class="${itemClass} border-b border-slate-800/50 pb-2 hover:bg-slate-800/50 px-2 rounded transition"><span class="text-slate-500 mr-2">~</span>${esc(log)}</li>`;
                }).join('');
                auditLogsWrapper.innerHTML = `<ul class="space-y-3 text-left">${itemsHtml}</ul>`;
            } else {
                auditLogsWrapper.innerHTML = `
                    <div class="h-full flex flex-col items-center justify-center text-slate-600 space-y-4">
                        <svg class="w-12 h-12 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
                        </svg>
                        <p>No audit logs available yet. The system is monitoring...</p>
                    </div>
                `;
            }
        } catch (err) {
            console.error('Failed to fetch logs:', err);
        }
    }
    setInterval(fetchLogs, 3000);
})();
