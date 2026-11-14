/*
 * 頁面切換由 HTMX（hx-boost）負責，互動元件由 Alpine.js 負責；
 * 這裡只處理兩者與 Bootstrap 元件之間的銜接。
 */
(() => {
    'use strict';

    const isMainTarget = (event) => event.detail.target && event.detail.target.id === 'main';

    /* ------------------------------------------------------------ navigation */

    // 換頁後同步側邊選單的目前頁面（伺服器在完整載入時已經設定好）
    function syncNav() {
        const path = location.pathname.replace(/\/+$/, '') || '/';
        document.querySelectorAll('#primary-nav a.nav-link').forEach((link) => {
            const current = link.pathname.replace(/\/+$/, '') === path;
            link.classList.toggle('active', current);
            if (current) link.setAttribute('aria-current', 'page');
            else link.removeAttribute('aria-current');
        });
    }

    // 換頁時若有開啟的對話框或側邊選單，先把它們關掉，避免殘留背景遮罩
    function cleanupOverlays() {
        if (!window.bootstrap) return;
        document.querySelectorAll('#main .modal').forEach((el) => bootstrap.Modal.getInstance(el)?.dispose());
        document.querySelectorAll('.modal-backdrop').forEach((el) => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');

        const sidebar = document.getElementById('sidebar');
        if (sidebar) bootstrap.Offcanvas.getInstance(sidebar)?.hide();
    }

    document.addEventListener('htmx:beforeRequest', (event) => {
        if (isMainTarget(event)) document.documentElement.classList.add('is-navigating');
    });

    document.addEventListener('htmx:afterRequest', (event) => {
        if (isMainTarget(event)) document.documentElement.classList.remove('is-navigating');
    });

    document.addEventListener('htmx:beforeSwap', (event) => {
        if (isMainTarget(event)) cleanupOverlays();
    });

    document.addEventListener('htmx:afterSettle', (event) => {
        if (!isMainTarget(event)) return;
        syncNav();
        // 讓螢幕閱讀器使用者知道內容已經換了
        const main = document.getElementById('main');
        if (!main.contains(document.activeElement) || document.activeElement === document.body) {
            main.focus({ preventScroll: true });
        }
    });

    document.addEventListener('htmx:historyRestore', () => {
        cleanupOverlays();
        syncNav();
    });

    // 網路中斷等無法取得回應的情況
    document.addEventListener('htmx:sendError', (event) => {
        document.documentElement.classList.remove('is-navigating');
        showToast('無法連線到伺服器，請檢查網路後再試一次。');
    });

    function showToast(message) {
        const region = document.getElementById('toasts');
        if (!region) return;
        const toast = document.createElement('div');
        toast.className = 'toast show align-items-center text-bg-danger border-0';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = '<div class="d-flex"><div class="toast-body"></div>'
            + '<button type="button" class="btn-close btn-close-white me-2 m-auto" aria-label="關閉"></button></div>';
        toast.querySelector('.toast-body').textContent = message;
        toast.querySelector('button').addEventListener('click', () => toast.remove());
        region.append(toast);
        setTimeout(() => toast.remove(), 6000);
    }

    /* ------------------------------------------------------------ Alpine components */

    document.addEventListener('alpine:init', () => {
        let nextId = 0;
        const LESSONS = ['r', '1', '2', '3', '4', 'q', '5', '6', '7', '8'];

        // 新增假單：一張假單可以有多個時段，每個時段各自選日期、星期與節次
        Alpine.data('leaveForm', () => ({
            periods: [],
            allLessons: LESSONS,

            init() {
                this.add();
                this.$el.closest('.modal')?.addEventListener('hidden.bs.modal', () => this.reset());
            },

            add() {
                this.periods.push({
                    id: nextId++,
                    start: '',
                    end: '',
                    weekdays: ['1', '2', '3', '4', '5'],
                    lessons: [],
                });
                this.$nextTick(() => {
                    const body = this.$refs.body;
                    body.scrollTo({ top: body.scrollHeight, behavior: 'smooth' });
                });
            },

            remove(index) {
                this.periods.splice(index, 1);
            },

            get payload() {
                return JSON.stringify(this.periods.map(({ start, end, weekdays, lessons }) => ({
                    start, end, weekdays, lessons,
                })));
            },

            reset() {
                this.$refs.form.reset();
                this.periods = [];
                this.add();
                const feedback = this.$el.querySelector('#leave-feedback');
                if (feedback) feedback.innerHTML = '';
            },

            close() {
                const modal = this.$el.closest('.modal');
                if (modal) bootstrap.Modal.getOrCreateInstance(modal).hide();
            },
        }));
    });
})();
