/**
 * office-connect sample — Vue 3 + Quasar (Outlook-style)
 *
 * Third-party libraries (bundled in vendor/):
 *   Vue.js v3.5.30    — MIT License    — https://github.com/vuejs/core
 *   Quasar v2.18.6    — MIT License    — https://github.com/quasarframework/quasar
 *   Phosphor Icons     — MIT License    — https://github.com/phosphor-icons/core
 *   Material Icons     — Apache 2.0     — https://github.com/google/material-design-icons
 */

const { createApp, ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } = Vue;

/* ── Avatar colour palette ───────────────────────────────────── */
const AVATAR_COLORS = [
  '#0078d4','#008272','#5c2d91','#c239b3','#e3008c',
  '#986f0b','#498205','#004e8c','#8764b8','#ca5010',
  '#7a7574','#004b50','#69797e','#a4262c','#0063b1',
];

function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/* ── Folder icon mapping ─────────────────────────────────────── */
const FOLDER_ICONS = {
  inbox: 'ph ph-tray',
  drafts: 'ph ph-pencil-simple',
  'sent items': 'ph ph-paper-plane-tilt',
  'deleted items': 'ph ph-trash',
  archive: 'ph ph-archive-box',
  'junk email': 'ph ph-warning-circle',
  spam: 'ph ph-warning-circle',
  outbox: 'ph ph-upload-simple',
  notes: 'ph ph-note',
  'conversation history': 'ph ph-chat-dots',
  rss: 'ph ph-rss',
};

const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];

const APP_VERSION = '1.0.0';

const app = createApp({
  setup() {
    // ── core state ─────────────────────────────────────────
    const authenticated = ref(false);
    const csrfToken = ref('');
    const view = ref('mail');

    // ── theme (light/dark) ─────────────────────────────────
    // Initialise from localStorage → prefers-color-scheme → 'light'.
    function _initialTheme() {
      try {
        const stored = localStorage.getItem('mail_theme');
        if (stored === 'dark' || stored === 'light') return stored;
      } catch { /* storage may be blocked */ }
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        return 'dark';
      }
      return 'light';
    }
    const theme = ref(_initialTheme());
    function applyTheme(t) {
      document.documentElement.setAttribute('data-theme', t);
      try { localStorage.setItem('mail_theme', t); } catch {}
    }
    function toggleTheme() { theme.value = theme.value === 'dark' ? 'light' : 'dark'; }
    // Apply immediately so there's no flash before the watcher fires.
    applyTheme(theme.value);
    watch(theme, applyTheme);

    // ── mail state ─────────────────────────────────────────
    const folders = ref([]);
    const selectedFolder = ref('');
    const currentFolderName = ref('Inbox');
    const messages = ref([]);
    const filteredMessages = ref([]);
    const mailSearch = ref('');
    const selectedMessage = ref(null);
    const loadingMail = ref(false);

    // ── email map for photos ──────────────────────────────
    const emailMap = ref({});

    // ── compose state ──────────────────────────────────────
    const composeMode = ref(false);
    const sending = ref(false);
    const compose = reactive({
      toList: [],
      toInput: '',
      ccList: [],
      ccInput: '',
      bccList: [],
      bccInput: '',
      subject: '',
      body: '',
      replyTo: null,
      isForward: false,
    });
    const showCcBcc = ref(false);
    const toSuggestions = ref([]);
    let toSearchTimer = null;

    // ── calendar state ─────────────────────────────────────
    const now = new Date();
    const calYear = ref(now.getFullYear());
    const calMonth = ref(now.getMonth());
    const miniCalYear = ref(now.getFullYear());
    const miniCalMonth = ref(now.getMonth());
    const events = ref([]);
    const loadingCal = ref(false);
    const selectedCalDate = ref('');
    const selectedEvent = ref(null);
    const showEventDialog = ref(false);
    const calViewMode = ref('month');   // 'month' | 'week' | 'day'
    // Week view: Monday of the viewed week
    const calWeekStart = ref((() => { const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); d.setHours(0,0,0,0); return d; })());
    // Day view: the viewed day
    const calSelectedDay = ref(new Date());
    // New event dialog
    const showNewEventDialog = ref(false);
    const newEvent = reactive({ subject: '', date: '', startTime: '09:00', endTime: '10:00', location: '' });
    // Calendar context menu
    const calCtxMenu = reactive({ show: false, x: 0, y: 0, date: '' });

    // ── chat state ─────────────────────────────────────────
    const chats = ref([]);
    const selectedChat = ref(null);
    const chatMessages = ref([]);
    const chatInput = ref('');
    const chatSearch = ref('');
    const loadingChat = ref(false);

    // ── teams state ────────────────────────────────────────
    const teams = ref([]);
    const selectedTeam = ref(null);
    const selectedChannel = ref(null);
    const channelMessages = ref([]);
    const loadingTeams = ref(false);
    const expandedTeams = ref([]);

    // ── files state ────────────────────────────────────────
    const filesView = ref('my');
    const filesNav = ref('my');
    const fileItems = ref([]);
    const loadingFiles = ref(false);
    const filePath = ref([{name: 'My Files', id: 'root'}]);

    // ── people state ───────────────────────────────────────
    const people = ref([]);
    const peopleQuery = ref('');
    const loadingPeople = ref(false);
    const failedPhotos = ref(new Set());
    let peopleTimer = null;

    // ── profile ────────────────────────────────────────────
    const profile = ref(null);

    // ── context menu state ─────────────────────────────────
    const contextMenu = reactive({
      show: false,
      x: 0,
      y: 0,
      type: '',
      item: null,
    });

    // ── settings panel ─────────────────────────────────────
    const showSettings = ref(false);

    // ════════════════════════════════════════════════════════
    // HELPERS
    // ════════════════════════════════════════════════════════

    async function api(path, opts) {
      const headers = { 'Content-Type': 'application/json' };
      if (csrfToken.value) headers['X-CSRF-Token'] = csrfToken.value;
      const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts || {}).headers } });
      if (res.status === 401) {
        // Mail session expired (in-memory registry) but identity cookie may still
        // be valid — a page reload re-registers the mail session via /mailview.
        // First 401 triggers reload; if that still 401s, show login screen.
        if (window.__MAIL_CONFIG__ && !sessionStorage.getItem('mail_reloaded_on_401')) {
          sessionStorage.setItem('mail_reloaded_on_401', '1');
          location.reload();
          throw new Error('Not authenticated — reloading');
        }
        sessionStorage.removeItem('mail_reloaded_on_401');
        authenticated.value = false;
        throw new Error('Not authenticated');
      }
      if (!res.ok) {
        const t = await res.text();
        // Surface a readable message: prefer a JSON `error`/`detail` field over
        // the raw JSON body, which would otherwise appear inside an error toast.
        let msg = t || res.statusText;
        try {
          const j = JSON.parse(t);
          msg = j.error || j.detail || j.message || t;
        } catch { /* not JSON */ }
        throw new Error(msg);
      }
      // Successful response — clear any stale reload-retry flag so a later
      // 401 can trigger a fresh reload attempt.
      sessionStorage.removeItem('mail_reloaded_on_401');
      return res.json();
    }

    function toast(msg, type) {
      Quasar.Notify.create({
        message: msg,
        color: type === 'error' ? 'negative' : type === 'warning' ? 'warning' : 'positive',
        position: 'bottom-right', timeout: 3000,
      });
    }

    function avatarColor(name) { return AVATAR_COLORS[hashStr(name || '?') % AVATAR_COLORS.length]; }

    function initials(name) {
      if (!name) return '?';
      const parts = name.trim().split(/[\s@.]+/);
      if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
      return name.slice(0, 2).toUpperCase();
    }

    function folderIcon(name) {
      return FOLDER_ICONS[(name || '').toLowerCase()] || 'ph ph-folder';
    }

    function senderPhoto(email) {
      if (!email) return null;
      const entry = emailMap.value[email.toLowerCase()];
      if (!entry || !entry.id) return null;
      return 'api/people/' + encodeURIComponent(entry.id) + '/photo';
    }

    function formatShortDate(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      const today = new Date();
      if (d.toDateString() === today.toDateString()) {
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
      }
      const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
      if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }

    function formatFullDate(iso) {
      if (!iso) return '';
      return new Date(iso).toLocaleString(undefined, {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    }

    function formatTime(iso) {
      if (!iso) return '';
      return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    }

    function formatSize(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      let i = 0;
      let size = bytes;
      while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
      return (i === 0 ? size : size.toFixed(1)) + ' ' + units[i];
    }

    function filterMessages() {
      const q = mailSearch.value.toLowerCase().trim();
      if (!q) { filteredMessages.value = messages.value; return; }
      filteredMessages.value = messages.value.filter(m =>
        (m.subject || '').toLowerCase().includes(q) ||
        (m.from_name || '').toLowerCase().includes(q) ||
        (m.from_email || '').toLowerCase().includes(q) ||
        (m.preview || '').toLowerCase().includes(q)
      );
    }

    // ── Date grouping helper ──────────────────────────────
    function getDateGroup(iso) {
      if (!iso) return 'Older';
      const d = new Date(iso);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const msgDate = new Date(d);
      msgDate.setHours(0, 0, 0, 0);

      const diffDays = Math.floor((today - msgDate) / (1000 * 60 * 60 * 24));

      if (diffDays === 0) return 'Today';
      if (diffDays === 1) return 'Yesterday';

      // This week: within last 7 days (but not today/yesterday)
      const dayOfWeek = today.getDay() || 7; // Mon=1..Sun=7
      if (diffDays < dayOfWeek) return 'This Week';

      // Last week
      if (diffDays < dayOfWeek + 7) return 'Last Week';

      // This month
      if (d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear()) return 'This Month';

      return 'Older';
    }

    // Wrap the current message's HTML with a theme-aware prelude so the
    // iframe body picks up the dark palette.  Emails author their own colors
    // (inline tables, bgcolor attrs, explicit CSS), so we use !important on
    // the base body + catch-all to override without mangling layout.  Images
    // keep a neutral light backdrop so sender logos on white stay legible.
    const messageBodyDoc = computed(() => {
      const html = (selectedMessage.value && selectedMessage.value.body) || '';
      if (theme.value !== 'dark') return html;
      const prelude = `<style>
        html, body { background: #181c22 !important; color: #e6e8eb !important; }
        body, body table, body td, body div, body span, body p, body li,
        body h1, body h2, body h3, body h4, body h5, body h6,
        body strong, body em, body blockquote {
          background-color: transparent !important;
          color: #e6e8eb !important;
        }
        body a { color: #4aa3ec !important; }
        body hr { border-color: #2a2f38 !important; }
        body img { background-color: #fff; }
        body pre, body code { background-color: #0e1116 !important; color: #e6e8eb !important; }
      </style>`;
      return prelude + html;
    });

    const groupedMessages = computed(() => {
      const order = ['Today', 'Yesterday', 'This Week', 'Last Week', 'This Month', 'Older'];
      const groups = {};
      order.forEach(label => { groups[label] = []; });

      filteredMessages.value.forEach(m => {
        const label = getDateGroup(m.received);
        if (!groups[label]) groups[label] = [];
        groups[label].push(m);
      });

      return order
        .filter(label => groups[label] && groups[label].length > 0)
        .map(label => ({ label, messages: groups[label] }));
    });

    // ════════════════════════════════════════════════════════
    // CONTEXT MENU
    // ════════════════════════════════════════════════════════

    function showContextMenuFn(event, type, item) {
      event.preventDefault();
      contextMenu.show = true;
      contextMenu.x = event.clientX;
      contextMenu.y = event.clientY;
      contextMenu.type = type;
      contextMenu.item = item;
    }

    function hideContextMenu() {
      contextMenu.show = false;
      contextMenu.type = '';
      contextMenu.item = null;
    }

    function onDocumentClick() {
      if (contextMenu.show) hideContextMenu();
      if (calCtxMenu.show) hideCalContextMenu();
    }

    function ctxMarkRead() {
      if (contextMenu.item) {
        contextMenu.item.is_read = true;
      }
      hideContextMenu();
    }

    function ctxMarkUnread() {
      if (contextMenu.item) {
        contextMenu.item.is_read = false;
      }
      hideContextMenu();
    }

    function ctxDelete() {
      if (contextMenu.item) {
        const id = contextMenu.item.id;
        messages.value = messages.value.filter(m => m.id !== id);
        filterMessages();
        if (selectedMessage.value && selectedMessage.value.email_id === id) {
          selectedMessage.value = null;
        }
        toast('Message deleted');
      }
      hideContextMenu();
    }

    function ctxReply() {
      if (contextMenu.item) {
        openMessage(contextMenu.item.id).then(() => {
          startReply(false);
        });
      }
      hideContextMenu();
    }

    function ctxReplyAll() {
      if (contextMenu.item) {
        openMessage(contextMenu.item.id).then(() => {
          startReply(true);
        });
      }
      hideContextMenu();
    }

    function ctxForward() {
      if (contextMenu.item) {
        openMessage(contextMenu.item.id).then(() => {
          startForward();
        });
      }
      hideContextMenu();
    }

    function ctxCopyEvent() {
      if (contextMenu.item) {
        const ev = contextMenu.item;
        const text = ev.subject + '\n' + formatFullDate(ev.start_time) + ' - ' + formatFullDate(ev.end_time);
        navigator.clipboard.writeText(text).then(() => toast('Copied to clipboard'));
      }
      hideContextMenu();
    }

    function ctxOpenEvent() {
      if (contextMenu.item) {
        openEvent(contextMenu.item);
      }
      hideContextMenu();
    }

    // ════════════════════════════════════════════════════════
    // AUTH
    // ════════════════════════════════════════════════════════

    async function checkAuth() {
      try {
        const data = await api('auth-status');
        authenticated.value = data.authenticated;
        if (data.authenticated) {
          const csrf = await api('csrf-token');
          csrfToken.value = csrf.token;
          loadProfile();
          // Await the email map BEFORE folders so messages render with the
          // correct sender photos on first paint (avoids a flash of initials
          // while the directory populates in the background).
          await loadEmailMap();
          loadFolders();
        }
      } catch { /* not logged in */ }
    }

    async function loadProfile() {
      try { profile.value = await api('api/profile'); } catch { /* ignore */ }
    }

    async function loadEmailMap() {
      try {
        const data = await api('api/people/email-map');
        emailMap.value = data || {};
        // If empty (directory still populating server-side), retry once
        // after a delay so inbox avatars replace initials with real photos.
        if (Object.keys(emailMap.value).length === 0) {
          setTimeout(async () => {
            try {
              const retry = await api('api/people/email-map');
              if (retry && Object.keys(retry).length > 0) emailMap.value = retry;
            } catch {}
          }, 5000);
        }
      } catch { /* ignore - feature may not be available */ }
    }

    // ════════════════════════════════════════════════════════
    // MAIL
    // ════════════════════════════════════════════════════════

    async function loadFolders() {
      try {
        folders.value = await api('api/mail/folders');
        const inbox = folders.value.find(f => f.name.toLowerCase() === 'inbox');
        if (inbox) { selectedFolder.value = inbox.id; currentFolderName.value = inbox.name; }
        else if (folders.value.length) { selectedFolder.value = folders.value[0].id; currentFolderName.value = folders.value[0].name; }
        loadMessages();
      } catch (e) { toast('Failed to load folders: ' + e.message, 'error'); }
    }

    async function selectFolder(id) {
      selectedFolder.value = id;
      const f = folders.value.find(x => x.id === id);
      currentFolderName.value = f ? f.name : '';
      selectedMessage.value = null;
      await loadMessages();
    }

    async function loadMessages() {
      loadingMail.value = true;
      try {
        const data = await api('api/mail/folders/' + encodeURIComponent(selectedFolder.value) + '/messages?limit=50');
        messages.value = data.messages;
        filterMessages();
      } catch (e) { toast('Failed to load messages: ' + e.message, 'error'); }
      finally { loadingMail.value = false; }
    }

    let _readTimer = null;

    async function openMessage(id) {
      // Cancel any pending mark-as-read from previous message
      if (_readTimer) { clearTimeout(_readTimer); _readTimer = null; }
      try {
        selectedMessage.value = await api('api/mail/messages/' + encodeURIComponent(id));
        // Mark as read after 3.5s delay (like Outlook) — cancelled if user navigates away
        const msg = messages.value.find(m => m.id === id);
        if (msg && !msg.is_read) {
          _readTimer = setTimeout(() => {
            // Only mark if this message is still the selected one
            if (selectedMessage.value && selectedMessage.value.email_id === id) {
              msg.is_read = true;
              api('api/mail/messages/' + encodeURIComponent(id) + '/read', { method: 'PATCH' }).catch(() => {});
            }
            _readTimer = null;
          }, 3500);
        }
      } catch (e) { toast('Failed to load message: ' + e.message, 'error'); }
    }

    // ════════════════════════════════════════════════════════
    // COMPOSE
    // ════════════════════════════════════════════════════════

    function startCompose(prefillTo) {
      compose.toList = prefillTo ? [prefillTo] : [];
      compose.toInput = '';
      compose.ccList = [];
      compose.ccInput = '';
      compose.bccList = [];
      compose.bccInput = '';
      compose.subject = '';
      compose.body = '';
      compose.replyTo = null;
      compose.isForward = false;
      showCcBcc.value = false;
      toSuggestions.value = [];
      composeMode.value = true;
    }

    function startReply(replyAll) {
      if (!selectedMessage.value) return;
      const m = selectedMessage.value;
      compose.toList = [m.from_email];
      compose.toInput = '';
      compose.ccList = [];
      compose.ccInput = '';
      compose.bccList = [];
      compose.bccInput = '';
      compose.subject = 'Re: ' + (m.subject || '');
      compose.body = '';
      compose.replyTo = m.email_id;
      compose.isForward = false;
      showCcBcc.value = false;
      toSuggestions.value = [];
      composeMode.value = true;
    }

    function startForward() {
      if (!selectedMessage.value) return;
      const m = selectedMessage.value;
      compose.toList = [];
      compose.toInput = '';
      compose.ccList = [];
      compose.ccInput = '';
      compose.bccList = [];
      compose.bccInput = '';
      compose.subject = 'Fw: ' + (m.subject || '');
      compose.body = '\n\n--- Forwarded message ---\n' + (m.body_preview || m.body || '');
      compose.replyTo = null;
      compose.isForward = true;
      showCcBcc.value = false;
      toSuggestions.value = [];
      composeMode.value = true;
    }

    function addRecipient(field) {
      const f = field || 'to';
      let val, list;
      if (f === 'cc') { val = compose.ccInput.trim(); list = compose.ccList; compose.ccInput = ''; }
      else if (f === 'bcc') { val = compose.bccInput.trim(); list = compose.bccList; compose.bccInput = ''; }
      else { val = compose.toInput.trim(); list = compose.toList; compose.toInput = ''; }
      if (val && !list.includes(val)) list.push(val);
      toSuggestions.value = [];
    }

    function removeRecipient(field, index) {
      if (field === 'cc') compose.ccList.splice(index, 1);
      else if (field === 'bcc') compose.bccList.splice(index, 1);
      else compose.toList.splice(index, 1);
    }

    function pickSuggestion(p) {
      if (p.email && !compose.toList.includes(p.email)) compose.toList.push(p.email);
      compose.toInput = '';
      toSuggestions.value = [];
    }

    async function onToInput() {
      clearTimeout(toSearchTimer);
      const q = compose.toInput.trim();
      if (q.length < 2) { toSuggestions.value = []; return; }
      toSearchTimer = setTimeout(async () => {
        try {
          toSuggestions.value = await api('api/people/search?q=' + encodeURIComponent(q));
        } catch { toSuggestions.value = []; }
      }, 300);
    }

    async function sendCompose() {
      if (!compose.toList.length || !compose.subject) {
        toast('To and Subject are required', 'warning'); return;
      }
      sending.value = true;
      try {
        if (compose.replyTo && !compose.isForward) {
          await api('api/mail/messages/' + encodeURIComponent(compose.replyTo) + '/reply', {
            method: 'POST',
            body: JSON.stringify({ comment: compose.body, replyAll: false }),
          });
        } else {
          await api('api/mail/send', {
            method: 'POST',
            body: JSON.stringify({
              to: compose.toList, cc: compose.ccList, bcc: compose.bccList,
              subject: compose.subject, body: compose.body,
            }),
          });
        }
        toast('Message sent');
        composeMode.value = false;
        loadMessages();
      } catch (e) { toast('Send failed: ' + e.message, 'error'); }
      finally { sending.value = false; }
    }

    function discardCompose() { composeMode.value = false; }

    // ════════════════════════════════════════════════════════
    // CALENDAR
    // ════════════════════════════════════════════════════════

    const calMonthName = computed(() => MONTHS[calMonth.value]);
    const miniCalMonthName = computed(() => MONTHS[miniCalMonth.value]);
    const CAL_HOURS = [7,8,9,10,11,12,13,14,15,16,17,18,19];

    function isSameDay(a, b) {
      return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }

    function eventsForDate(dateStr) {
      const dayEvs = events.value.filter(e => {
        const eStart = new Date(e.start_time);
        const eEnd = new Date(e.end_time);
        const dt = new Date(dateStr + 'T00:00:00');
        return dt >= new Date(eStart.getFullYear(), eStart.getMonth(), eStart.getDate()) &&
               dt <= new Date(eEnd.getFullYear(), eEnd.getMonth(), eEnd.getDate());
      });
      // All-day events first, then timed events sorted by start time
      return dayEvs.sort((a, b) => {
        if (a.is_all_day && !b.is_all_day) return -1;
        if (!a.is_all_day && b.is_all_day) return 1;
        return new Date(a.start_time) - new Date(b.start_time);
      });
    }

    function eventShowAsClass(ev) {
      const sa = ev.show_as || 'busy';
      if (sa === 'oof') return 'cal-event-oof';
      if (sa === 'tentative') return 'cal-event-tentative';
      if (sa === 'free') return 'cal-event-free';
      return 'cal-event-busy';
    }

    function timeEventStyle(ev) {
      const s = new Date(ev.start_time);
      const e = new Date(ev.end_time);
      const startMin = s.getHours() * 60 + s.getMinutes();
      const endMin = e.getHours() * 60 + e.getMinutes();
      const topMin = startMin - 7 * 60; // 7:00 is row 0
      const dur = Math.max(endMin - startMin, 15);
      const pxPerMin = 48 / 60; // 48px per hour
      return {
        top: (topMin * pxPerMin) + 'px',
        height: (dur * pxPerMin) + 'px',
      };
    }

    function currentTimeTop() {
      const n = new Date();
      const min = n.getHours() * 60 + n.getMinutes() - 7 * 60;
      return (min * 48 / 60) + 'px';
    }

    function buildMonthGrid(year, month) {
      const first = new Date(year, month, 1);
      const last = new Date(year, month + 1, 0);
      const start = new Date(first);
      start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
      const today = new Date();
      const weeks = [];
      const cur = new Date(start);
      for (let w = 0; w < 6; w++) {
        const week = [];
        for (let d = 0; d < 7; d++) {
          const dt = new Date(cur);
          const dateStr = dt.toISOString().slice(0, 10);
          week.push({
            date: dateStr,
            day: dt.getDate(),
            currentMonth: dt.getMonth() === month,
            isToday: isSameDay(dt, today),
            events: eventsForDate(dateStr),
          });
          cur.setDate(cur.getDate() + 1);
        }
        weeks.push(week);
      }
      return weeks;
    }

    const calendarGrid = computed(() => buildMonthGrid(calYear.value, calMonth.value));

    // ── Week view computed ──────────────────────────────────
    const calWeekGrid = computed(() => {
      const ws = new Date(calWeekStart.value);
      const today = new Date();
      const cols = [];
      for (let d = 0; d < 7; d++) {
        const dt = new Date(ws);
        dt.setDate(ws.getDate() + d);
        const dateStr = dt.toISOString().slice(0, 10);
        const dayEvs = eventsForDate(dateStr);
        const timed = dayEvs.filter(e => !e.is_all_day);
        const allDay = dayEvs.filter(e => e.is_all_day);
        cols.push({
          date: dateStr,
          day: dt.getDate(),
          weekday: ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][d],
          isToday: isSameDay(dt, today),
          timedEvents: timed,
          allDayEvents: allDay,
        });
      }
      return cols;
    });

    const calWeekLabel = computed(() => {
      const ws = new Date(calWeekStart.value);
      const we = new Date(ws); we.setDate(ws.getDate() + 6);
      const sMonth = MONTHS[ws.getMonth()];
      const eMonth = MONTHS[we.getMonth()];
      if (ws.getMonth() === we.getMonth()) {
        return sMonth + ' ' + ws.getDate() + ' - ' + we.getDate() + ', ' + ws.getFullYear();
      }
      return sMonth + ' ' + ws.getDate() + ' - ' + eMonth + ' ' + we.getDate() + ', ' + we.getFullYear();
    });

    // ── Day view computed ───────────────────────────────────
    const calDayEvents = computed(() => {
      const ds = calSelectedDay.value;
      const dateStr = new Date(ds).toISOString().slice(0, 10);
      const dayEvs = eventsForDate(dateStr);
      return {
        timed: dayEvs.filter(e => !e.is_all_day),
        allDay: dayEvs.filter(e => e.is_all_day),
      };
    });

    const calDayLabel = computed(() => {
      const d = new Date(calSelectedDay.value);
      return d.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    });

    const calDayIsToday = computed(() => {
      return isSameDay(new Date(calSelectedDay.value), new Date());
    });

    function buildMiniCal(year, month) {
      const first = new Date(year, month, 1);
      const start = new Date(first);
      start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
      const today = new Date();
      const days = [];
      const cur = new Date(start);
      for (let i = 0; i < 42; i++) {
        days.push({
          date: cur.toISOString().slice(0, 10),
          day: cur.getDate(),
          currentMonth: cur.getMonth() === month,
          isToday: isSameDay(cur, today),
        });
        cur.setDate(cur.getDate() + 1);
      }
      return days;
    }

    const miniCalDays = computed(() => buildMiniCal(miniCalYear.value, miniCalMonth.value));

    function calPrev() {
      if (calViewMode.value === 'day') {
        const d = new Date(calSelectedDay.value);
        d.setDate(d.getDate() - 1);
        calSelectedDay.value = d;
        calYear.value = d.getFullYear(); calMonth.value = d.getMonth();
        miniCalYear.value = d.getFullYear(); miniCalMonth.value = d.getMonth();
        loadEvents();
      } else if (calViewMode.value === 'week') {
        const ws = new Date(calWeekStart.value);
        ws.setDate(ws.getDate() - 7);
        calWeekStart.value = ws;
        calYear.value = ws.getFullYear(); calMonth.value = ws.getMonth();
        miniCalYear.value = ws.getFullYear(); miniCalMonth.value = ws.getMonth();
        loadEvents();
      } else {
        calMonth.value--;
        if (calMonth.value < 0) { calMonth.value = 11; calYear.value--; }
        miniCalMonth.value = calMonth.value;
        miniCalYear.value = calYear.value;
        loadEvents();
      }
    }
    function calNext() {
      if (calViewMode.value === 'day') {
        const d = new Date(calSelectedDay.value);
        d.setDate(d.getDate() + 1);
        calSelectedDay.value = d;
        calYear.value = d.getFullYear(); calMonth.value = d.getMonth();
        miniCalYear.value = d.getFullYear(); miniCalMonth.value = d.getMonth();
        loadEvents();
      } else if (calViewMode.value === 'week') {
        const ws = new Date(calWeekStart.value);
        ws.setDate(ws.getDate() + 7);
        calWeekStart.value = ws;
        calYear.value = ws.getFullYear(); calMonth.value = ws.getMonth();
        miniCalYear.value = ws.getFullYear(); miniCalMonth.value = ws.getMonth();
        loadEvents();
      } else {
        calMonth.value++;
        if (calMonth.value > 11) { calMonth.value = 0; calYear.value++; }
        miniCalMonth.value = calMonth.value;
        miniCalYear.value = calYear.value;
        loadEvents();
      }
    }
    function miniCalPrev() {
      miniCalMonth.value--;
      if (miniCalMonth.value < 0) { miniCalMonth.value = 11; miniCalYear.value--; }
    }
    function miniCalNext() {
      miniCalMonth.value++;
      if (miniCalMonth.value > 11) { miniCalMonth.value = 0; miniCalYear.value++; }
    }
    function goToToday() {
      const t = new Date();
      calYear.value = t.getFullYear(); calMonth.value = t.getMonth();
      miniCalYear.value = t.getFullYear(); miniCalMonth.value = t.getMonth();
      selectedCalDate.value = t.toISOString().slice(0, 10);
      calSelectedDay.value = t;
      const ws = new Date(t); ws.setDate(ws.getDate() - ((ws.getDay() + 6) % 7)); ws.setHours(0,0,0,0);
      calWeekStart.value = ws;
      loadEvents();
    }
    function goToDate(dateStr) {
      const d = new Date(dateStr);
      calYear.value = d.getFullYear(); calMonth.value = d.getMonth();
      selectedCalDate.value = dateStr;
      calSelectedDay.value = d;
      const ws = new Date(d); ws.setDate(ws.getDate() - ((ws.getDay() + 6) % 7)); ws.setHours(0,0,0,0);
      calWeekStart.value = ws;
      loadEvents();
    }

    function openEvent(ev) {
      selectedEvent.value = ev;
      showEventDialog.value = true;
    }

    function closeEventDialog() {
      showEventDialog.value = false;
      selectedEvent.value = null;
    }

    // ── Calendar context menu (right-click to create) ─────
    function showCalContextMenu(event, dateStr) {
      event.preventDefault();
      calCtxMenu.show = true;
      calCtxMenu.x = event.clientX;
      calCtxMenu.y = event.clientY;
      calCtxMenu.date = dateStr;
    }

    function hideCalContextMenu() {
      calCtxMenu.show = false;
    }

    function openNewEventFromCtx() {
      newEvent.subject = '';
      newEvent.date = calCtxMenu.date;
      newEvent.startTime = '09:00';
      newEvent.endTime = '10:00';
      newEvent.location = '';
      hideCalContextMenu();
      showNewEventDialog.value = true;
    }

    async function submitNewEvent() {
      if (!newEvent.subject) { toast('Subject is required', 'warning'); return; }
      try {
        await api('api/calendar/events', {
          method: 'POST',
          body: JSON.stringify({
            subject: newEvent.subject,
            date: newEvent.date,
            start_time: newEvent.startTime,
            end_time: newEvent.endTime,
            location: newEvent.location,
          }),
        });
      } catch { /* mock — ignore errors */ }
      toast('Event created');
      showNewEventDialog.value = false;
    }

    async function loadEvents() {
      loadingCal.value = true;
      try {
        // Load a wide range so week/day views outside current month work
        const rangeStart = new Date(calYear.value, calMonth.value - 1, 1);
        const rangeEnd = new Date(calYear.value, calMonth.value + 2, 6);
        const start = rangeStart.toISOString().slice(0, 10);
        const end = rangeEnd.toISOString().slice(0, 10);
        const data = await api('api/calendar/events?start=' + start + '&end=' + end + '&limit=200');
        events.value = data.events || [];
      } catch (e) { toast('Failed to load events: ' + e.message, 'error'); }
      finally { loadingCal.value = false; }
    }

    // auto-load calendar when switching to calendar view
    watch(view, (v) => {
      if (v === 'calendar' && events.value.length === 0) loadEvents();
    });

    // ════════════════════════════════════════════════════════
    // PEOPLE
    // ════════════════════════════════════════════════════════

    async function loadPeople(q) {
      loadingPeople.value = true;
      try {
        people.value = await api('api/people/search?q=' + encodeURIComponent(q || ''));
      } catch (e) { toast('Search failed: ' + e.message, 'error'); }
      finally { loadingPeople.value = false; }
    }

    function debouncePeopleSearch() {
      clearTimeout(peopleTimer);
      peopleTimer = setTimeout(() => loadPeople(peopleQuery.value), 400);
    }

    function personPhotoUrl(p) {
      if (failedPhotos.value.has(p.id)) return null;
      return 'api/people/' + encodeURIComponent(p.id) + '/photo';
    }

    function onPhotoError(p) {
      failedPhotos.value.add(p.id);
    }

    function startMailTo(p) {
      view.value = 'mail';
      startCompose(p.email);
    }

    // ════════════════════════════════════════════════════════
    // CHAT
    // ════════════════════════════════════════════════════════

    const filteredChats = computed(() => {
      const q = (chatSearch.value || '').toLowerCase().trim();
      if (!q) return chats.value;
      return chats.value.filter(c => (c.name || '').toLowerCase().includes(q));
    });

    const chatMessageGroups = computed(() => {
      const order = ['Today', 'Yesterday', 'Older'];
      const groups = {};
      order.forEach(label => { groups[label] = []; });
      chatMessages.value.forEach(m => {
        const label = getDateGroup(m.timestamp);
        if (!groups[label]) groups[label] = [];
        groups[label].push(m);
      });
      return order
        .filter(label => groups[label] && groups[label].length > 0)
        .map(label => ({ label, messages: groups[label] }));
    });

    async function loadChats() {
      loadingChat.value = true;
      try {
        const raw = await api('api/chat/list');
        chats.value = raw.map(c => {
          // Derive display name: topic for groups, other member for 1:1
          let name = c.topic;
          if (!name && c.members) {
            const other = c.members.find(m => m.email && m.email.toLowerCase() !== 'mock@example.com');
            name = other ? other.displayName : (c.members[0] || {}).displayName || 'Chat';
          }
          return {
            id: c.id,
            name: name || 'Chat',
            type: c.chatType === 'oneOnOne' ? 'oneOnOne' : c.chatType === 'meeting' ? 'meeting' : 'group',
            lastMessage: c.lastMessage ? c.lastMessage.content : '',
            lastMessageTime: c.lastMessage ? c.lastMessage.timestamp : '',
            memberCount: (c.members || []).length,
          };
        });
      } catch { chats.value = []; }
      finally { loadingChat.value = false; }
    }

    async function openChat(chatId) {
      const chat = chats.value.find(c => c.id === chatId);
      if (chat) selectedChat.value = chat;
      loadingChat.value = true;
      try {
        const raw = await api('api/chat/' + chatId);
        chatMessages.value = (raw.messages || []).map(m => ({
          id: m.id,
          senderName: m.isFromMe ? 'You' : m.senderName,
          text: m.content,
          timestamp: m.timestamp,
          isMine: m.isFromMe || false,
          reactions: m.reactions || [],
        }));
      } catch { chatMessages.value = []; }
      finally { loadingChat.value = false; }
    }

    function sendChat() {
      const text = chatInput.value.trim();
      if (!text) return;
      chatMessages.value.push({
        id: 'msg-' + Date.now(),
        senderName: 'You',
        text: text,
        timestamp: new Date().toISOString(),
        isMine: true,
        reactions: [],
      });
      chatInput.value = '';
    }

    // ════════════════════════════════════════════════════════
    // TEAMS
    // ════════════════════════════════════════════════════════

    async function loadTeams() {
      loadingTeams.value = true;
      try {
        const raw = await api('api/teams/list');
        teams.value = raw.map(t => ({
          id: t.id,
          name: t.displayName || t.name || 'Team',
          channels: (t.channels || []).map(ch => ({
            id: ch.id || ch.displayName,
            name: ch.displayName || ch.name || 'Channel',
            lastActivity: ch.lastActivity || '',
          })),
        }));
      } catch { teams.value = []; }
      finally { loadingTeams.value = false; }
      // Auto-expand first team
      if (teams.value.length && !expandedTeams.value.length) {
        expandedTeams.value.push(teams.value[0].id);
      }
    }

    function toggleTeam(teamId) {
      const idx = expandedTeams.value.indexOf(teamId);
      if (idx >= 0) expandedTeams.value.splice(idx, 1);
      else expandedTeams.value.push(teamId);
    }

    async function openChannel(teamId, channelId) {
      const team = teams.value.find(t => t.id === teamId);
      selectedTeam.value = team;
      const ch = team ? team.channels.find(c => c.id === channelId) : null;
      selectedChannel.value = ch;
      loadingTeams.value = true;
      try {
        const raw = await api('api/teams/' + teamId + '/channels/' + channelId + '/messages');
        channelMessages.value = (Array.isArray(raw) ? raw : raw.messages || []).map(m => ({
          id: m.id,
          senderName: m.senderName || '',
          text: m.content || m.text || '',
          timestamp: m.timestamp || '',
          reactions: m.reactions || [],
          replyCount: m.replies || m.replyCount || 0,
        }));
      } catch { channelMessages.value = []; }
      finally { loadingTeams.value = false; }
    }

    function postInChannel() {
      toast('Post dialog coming soon');
    }

    // ════════════════════════════════════════════════════════
    // FILES
    // ════════════════════════════════════════════════════════

    async function loadFiles(viewType) {
      filesView.value = viewType || 'my';
      loadingFiles.value = true;
      try {
        const raw = await api('api/files/' + filesView.value);
        fileItems.value = (Array.isArray(raw) ? raw : []).map(f => ({
          id: f.id,
          name: f.name,
          isFolder: f.type === 'folder',
          modified: f.modifiedAt || '',
          modifiedBy: f.modifiedBy || 'Mock User',
          size: f.size || 0,
        }));
      } catch { fileItems.value = []; }
      finally { loadingFiles.value = false; }
    }

    function fileIcon(f) {
      if (f.isFolder) return 'ph ph-folder';
      const name = (f.name || '').toLowerCase();
      if (name.endsWith('.docx') || name.endsWith('.doc')) return 'ph ph-file-doc';
      if (name.endsWith('.xlsx') || name.endsWith('.xls')) return 'ph ph-file-xls';
      if (name.endsWith('.pptx') || name.endsWith('.ppt')) return 'ph ph-file-ppt';
      if (name.endsWith('.pdf')) return 'ph ph-file-pdf';
      if (name.endsWith('.py') || name.endsWith('.js') || name.endsWith('.ts')) return 'ph ph-file-code';
      return 'ph ph-file';
    }

    function onFileClick(f) {
      if (f.isFolder) {
        filePath.value.push({ name: f.name, id: f.id });
        // In a real app, load the folder contents
        fileItems.value = [];
        loadFiles(filesView.value);
      }
    }

    function navigateFilePath(index) {
      filePath.value = filePath.value.slice(0, index + 1);
      loadFiles(filesView.value);
    }

    // ════════════════════════════════════════════════════════
    // VIEW SWITCHER
    // ════════════════════════════════════════════════════════

    function switchView(v) {
      view.value = v;
      if (v === 'chat' && !chats.value.length) loadChats();
      if (v === 'teams' && !teams.value.length) loadTeams();
      if (v === 'files' && !fileItems.value.length) loadFiles('my');
    }

    // ════════════════════════════════════════════════════════
    // SETTINGS
    // ════════════════════════════════════════════════════════

    function openSettings() {
      showSettings.value = true;
    }

    function closeSettings() {
      showSettings.value = false;
    }

    // ════════════════════════════════════════════════════════
    // LIFECYCLE
    // ════════════════════════════════════════════════════════

    // Keyboard shortcuts (top-level only for now: T toggles theme).
    function onGlobalKeydown(e) {
      // Ignore when typing in inputs, textareas or contentEditable elements.
      const t = e.target;
      const tag = t && t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (t && t.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 't' || e.key === 'T') {
        toggleTheme();
        e.preventDefault();
      }
    }

    onMounted(() => {
      checkAuth();
      document.addEventListener('click', onDocumentClick);
      document.addEventListener('keydown', onGlobalKeydown);
    });

    onUnmounted(() => {
      document.removeEventListener('click', onDocumentClick);
      document.removeEventListener('keydown', onGlobalKeydown);
    });

    return {
      // core
      authenticated, profile, view, theme, toggleTheme,
      // mail
      folders, selectedFolder, currentFolderName, messages, filteredMessages,
      mailSearch, selectedMessage, loadingMail,
      selectFolder, openMessage, filterMessages,
      // email map / photos
      emailMap, senderPhoto,
      // theme-aware iframe source
      messageBodyDoc,
      // grouped messages
      groupedMessages,
      // compose
      composeMode, sending, compose, toSuggestions, showCcBcc,
      startCompose, startReply, startForward,
      addRecipient, removeRecipient, pickSuggestion, onToInput,
      sendCompose, discardCompose,
      // calendar
      calYear, calMonth, calMonthName, miniCalYear, miniCalMonth, miniCalMonthName,
      events, loadingCal, selectedCalDate, calendarGrid, miniCalDays,
      calPrev, calNext, miniCalPrev, miniCalNext, goToToday, goToDate, loadEvents,
      selectedEvent, showEventDialog, openEvent, closeEventDialog,
      calViewMode, calWeekStart, calWeekGrid, calWeekLabel,
      calSelectedDay, calDayEvents, calDayLabel, calDayIsToday,
      CAL_HOURS, eventShowAsClass, timeEventStyle, currentTimeTop,
      showCalContextMenu, hideCalContextMenu, calCtxMenu,
      openNewEventFromCtx, showNewEventDialog, newEvent, submitNewEvent,
      // chat
      chats, selectedChat, chatMessages, chatInput, chatSearch, loadingChat,
      filteredChats, chatMessageGroups,
      loadChats, openChat, sendChat,
      // teams
      teams, selectedTeam, selectedChannel, channelMessages, loadingTeams,
      expandedTeams,
      loadTeams, toggleTeam, openChannel, postInChannel,
      // files
      filesView, filesNav, fileItems, loadingFiles, filePath,
      loadFiles, fileIcon, onFileClick, navigateFilePath,
      // view switcher
      switchView,
      // people
      people, peopleQuery, loadingPeople,
      loadPeople, debouncePeopleSearch, personPhotoUrl, onPhotoError, startMailTo,
      // context menu
      contextMenu, showContextMenu: showContextMenuFn, hideContextMenu,
      ctxMarkRead, ctxMarkUnread, ctxDelete, ctxReply, ctxReplyAll, ctxForward,
      ctxCopyEvent, ctxOpenEvent,
      // settings
      showSettings, openSettings, closeSettings, APP_VERSION: APP_VERSION,
      // helpers
      avatarColor, initials, folderIcon,
      formatShortDate, formatFullDate, formatTime, formatSize,
    };
  },
});

app.use(Quasar, {
  config: { notify: { position: 'bottom-right', timeout: 3000 } },
});
app.mount('#q-app');
