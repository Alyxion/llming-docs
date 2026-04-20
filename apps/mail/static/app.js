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
    // ── Host-provided config hooks ─────────────────────────
    // Every hook is optional; ``resolveMailHooks()`` supplies safe
    // defaults.  Hosts can customize index visualization, email body
    // augmentation, attachment prefetching, cache TTLs, theme, and
    // trusted-sender policy by placing an object on
    // ``window.__MAIL_CONFIG__.hooks``.  The mail app is host-neutral
    // — no per-host (e.g. CRM plugin) code in this file.
    const hooks = window.resolveMailHooks ? window.resolveMailHooks() : {};

    // ── Theme state + host subscription ────────────────────
    // The host publishes its current theme via ``hooks.theme`` and can
    // push updates by invoking the callback passed to
    // ``hooks.subscribeTheme``.  We mirror that onto the ``<html>``
    // element as ``data-mail-theme`` so CSS variables flip between
    // light and dark in sync with the surrounding page.
    const theme = ref(hooks.theme === 'dark' ? 'dark' : 'light');
    function _applyTheme(t) {
      document.documentElement.setAttribute('data-mail-theme', t);
    }
    _applyTheme(theme.value);
    let _themeUnsub = null;
    try {
      _themeUnsub = hooks.subscribeTheme((next) => {
        theme.value = next === 'dark' ? 'dark' : 'light';
        _applyTheme(theme.value);
      });
    } catch (e) { console.warn('[mail] subscribeTheme threw:', e); }

    // ── WebSocket client ─────────────────────────────────────
    const mailClient = new MailClient();
    const cache = new MailCache();
    const isOnline = ref(true);

    // ── core state ─────────────────────────────────────────
    // Default to true — the app chrome renders immediately with empty
    // state.  A failed auth probe triggers a redirect to loginUrl; we
    // never show an inline login card that would flash during boot.
    const authenticated = ref(true);
    const csrfToken = ref('');
    const view = ref('mail');

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
      isReplyAll: false,
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
    const soundEnabled = ref(localStorage.getItem('mail_sound') !== 'off');

    // ── Template ref for host-injected extras (below the body) ──
    const mailExtrasSlot = ref(null);

    // ── Per-row extension output (classes, indicators) ──
    // Host-provided ``hooks.renderIndexRow`` decorates each mail row with
    // extra classes and icons (e.g. "order" badge).  We call it from the
    // template; caller is responsible for keeping the function cheap.
    function rowExt(mail) {
      try {
        const res = hooks.renderIndexRow(mail, {
          selectedFolder: selectedFolder.value,
          profile: profile.value,
        });
        return res || {};
      } catch (e) {
        console.warn('[mail] renderIndexRow threw:', e);
        return {};
      }
    }

    // ════════════════════════════════════════════════════════
    // HELPERS
    // ════════════════════════════════════════════════════════

    function _loginUrl() {
      return (window.__MAIL_CONFIG__ && window.__MAIL_CONFIG__.loginUrl) || 'login';
    }

    function _redirectToLogin() {
      // Guard against loops when the login target itself 401s.
      if (sessionStorage.getItem('mail_redirected_to_login')) return;
      sessionStorage.setItem('mail_redirected_to_login', '1');
      window.location.replace(_loginUrl());
    }

    async function api(path, opts) {
      const headers = { 'Content-Type': 'application/json' };
      if (csrfToken.value) headers['X-CSRF-Token'] = csrfToken.value;
      const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts || {}).headers } });
      if (res.status === 401) {
        _redirectToLogin();
        throw new Error('Not authenticated');
      }
      // Successful response — clear any stale redirect guard.
      sessionStorage.removeItem('mail_redirected_to_login');
      if (!res.ok) {
        const t = await res.text();
        let msg = t || res.statusText;
        try { const j = JSON.parse(t); msg = j.error || j.detail || j.message || t; } catch {}
        throw new Error(msg);
      }
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
      // Only tokens that START with a letter count toward the initials.
      // "Miles & More Travel ID" → ["Miles", "More", "Travel", "ID"] → "MM",
      // not "M&".  Non-letter fragments (``&``, ``-``, emoji, digits at the
      // front of a word) are skipped so the avatar always shows two letters.
      const tokens = name.trim().split(/[\s@.,/&+|_\-–—]+/u).filter(Boolean);
      const letterTokens = tokens.filter(t => /^\p{L}/u.test(t));
      if (letterTokens.length >= 2) {
        return (letterTokens[0][0] + letterTokens[1][0]).toUpperCase();
      }
      if (letterTokens.length === 1) {
        return letterTokens[0].slice(0, 2).toUpperCase();
      }
      // No letter-led tokens — fall back to the first two letters anywhere.
      const letters = name.replace(/[^\p{L}]/gu, '');
      return (letters.slice(0, 2) || '?').toUpperCase();
    }

    function folderIcon(name) {
      return FOLDER_ICONS[(name || '').toLowerCase()] || 'ph ph-folder';
    }

    // Avatar photo cache — persists across reloads via Cache API.
    // Returns a blob URL from cache on hit, or triggers async fetch
    // that populates the reactive map (Vue re-renders when ready).
    const _avatarUrls = reactive({});

    function senderPhoto(email) {
      if (!email) return null;
      const key = email.toLowerCase();
      const entry = emailMap.value[key];
      if (!entry || !entry.id) return null;
      if (_avatarUrls[key] !== undefined) return _avatarUrls[key] || null;
      _avatarUrls[key] = null; // mark as loading
      const url = 'api/people/' + encodeURIComponent(entry.id) + '/photo';
      _fetchAvatar(key, url);
      return null;
    }

    // ── Avatar cache TTL ──────────────────────────────────
    // Cache API does not carry expiry metadata, so we pair each entry
    // with a timestamp in localStorage.  Entries older than
    // ``hooks.avatarMaxAgeDays`` (default 14) are evicted and re-fetched.
    // Avatars change rarely — the refresh cost is negligible.
    const _AVATAR_TS_KEY = 'mail_avatar_ts';
    const _AVATAR_TS_LIMIT = 500;  // cap the LS footprint
    const _avatarTsCache = (() => {
      try { return JSON.parse(localStorage.getItem(_AVATAR_TS_KEY) || '{}'); }
      catch { return {}; }
    })();
    function _avatarMaxAgeMs() {
      return Math.max(1, hooks.avatarMaxAgeDays || 14) * 86400 * 1000;
    }
    function _avatarTimestampGet(url) { return _avatarTsCache[url] || 0; }
    function _avatarTimestampSet(url, ts) {
      _avatarTsCache[url] = ts;
      // LRU-trim if the map gets too large.
      const keys = Object.keys(_avatarTsCache);
      if (keys.length > _AVATAR_TS_LIMIT) {
        keys.sort((a, b) => _avatarTsCache[a] - _avatarTsCache[b]);
        const drop = keys.length - _AVATAR_TS_LIMIT;
        for (let i = 0; i < drop; i++) delete _avatarTsCache[keys[i]];
      }
      try { localStorage.setItem(_AVATAR_TS_KEY, JSON.stringify(_avatarTsCache)); }
      catch { /* quota exceeded — drop silently */ }
    }

    async function _fetchAvatar(key, url) {
      try {
        const c = await caches.open('mail-avatars');
        const cached = await c.match(url);
        const age = Date.now() - _avatarTimestampGet(url);
        const stale = age > _avatarMaxAgeMs();
        if (cached && cached.ok && !stale) {
          _avatarUrls[key] = URL.createObjectURL(await cached.blob());
          return;
        }
        if (stale && cached) {
          // Evict expired entry — will be replaced by the fetch below or
          // an initials fallback if the fetch fails.
          c.delete(url).catch(() => {});
        }
        const resp = await fetch(url);
        if (resp.ok) {
          c.put(url, resp.clone()).catch(() => {});
          _avatarTimestampSet(url, Date.now());
          _avatarUrls[key] = URL.createObjectURL(await resp.blob());
        } else {
          _avatarUrls[key] = false;
        }
      } catch {
        _avatarUrls[key] = false;
      }
    }

    async function clearAvatarCache() {
      await caches.delete('mail-avatars');
      for (const key in _avatarUrls) delete _avatarUrls[key];
      try { localStorage.removeItem(_AVATAR_TS_KEY); } catch {}
      for (const k in _avatarTsCache) delete _avatarTsCache[k];
      toast('Avatar cache cleared', 'info');
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

    // ── Search state ──────────────────────────────────────
    // Non-empty queries are debounced through the WS ``search`` action
    // (server-side, hits Graph ``$search``) and display the returned
    // rows directly in ``filteredMessages``, keeping the folder index
    // in ``messages`` untouched.  An empty query falls back to the
    // local filter over the current folder so the user can scrub the
    // inbox without hitting the server every keystroke.
    let _searchDebounce = null;
    const _searchInflight = { token: 0 };   // cancel stale responses

    function filterMessages() {
      const q = mailSearch.value.trim();
      // Local filter whenever the field is empty.
      if (!q) {
        filteredMessages.value = messages.value;
        return;
      }
      // Immediate local filter (gives feedback before the network call).
      const qLower = q.toLowerCase();
      filteredMessages.value = messages.value.filter(m =>
        (m.subject || '').toLowerCase().includes(qLower) ||
        (m.from_name || '').toLowerCase().includes(qLower) ||
        (m.from_email || '').toLowerCase().includes(qLower) ||
        (m.preview || '').toLowerCase().includes(qLower)
      );
      // Debounced server-side search — 300 ms after the user stops typing.
      if (_searchDebounce) clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => _runServerSearch(q), 300);
    }

    async function _runServerSearch(q) {
      const token = ++_searchInflight.token;
      try {
        const data = await mailClient.request('search', { q, limit: 50 });
        if (token !== _searchInflight.token) return;  // superseded
        if (mailSearch.value.trim() !== q) return;    // user kept typing
        if (Array.isArray(data.messages)) {
          filteredMessages.value = data.messages;
        }
      } catch (e) {
        // Keep the local-filter fallback; just note connectivity.
        isOnline.value = false;
      }
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
      if (showReactionPicker.value) showReactionPicker.value = false;
      if (calCtxMenu.show) hideCalContextMenu();
    }

    function ctxMarkRead() {
      if (contextMenu.item) {
        contextMenu.item.is_read = true;
        mailClient.request('mark_read', { message_id: contextMenu.item.id, is_read: true }).catch(() => {});
      }
      hideContextMenu();
    }

    function ctxMarkUnread() {
      if (contextMenu.item) {
        contextMenu.item.is_read = false;
        mailClient.request('mark_read', { message_id: contextMenu.item.id, is_read: false }).catch(() => {});
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
        mailClient.request('delete', { message_id: id }).catch(() => {});
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

    async function paintFromCache() {
      // Read-only cache paint — no network, no auth required.  Keeps the
      // chrome populated across reloads before the auth probe returns.
      try {
        const cachedFolders = await cache.getFolders();
        if (cachedFolders && cachedFolders.length) {
          _applyFolders(cachedFolders);
          const folderId = selectedFolder.value;
          if (folderId) {
            const cachedMsgs = await cache.getMessagesIndex(folderId);
            if (cachedMsgs && cachedMsgs.length) {
              messages.value = cachedMsgs;
              filterMessages();
              // Restore the last-opened mail for this folder so the
              // reading pane is populated on reload without a flicker.
              const wantId = _lastSelected[folderId];
              if (wantId && cachedMsgs.some(m => m.id === wantId)) {
                const cachedBody = await cache.getBody(wantId);
                if (cachedBody) selectedMessage.value = cachedBody;
              }
            }
          }
        }
      } catch { /* cache miss — chrome stays empty */ }
    }

    async function checkAuth() {
      try {
        const data = await api('auth-status');
        if (!data.authenticated) {
          // Not authenticated — redirect to login.  Never flash an inline
          // login card; the chrome stays visible during the redirect.
          _redirectToLogin();
          return;
        }
        authenticated.value = true;
        const csrf = await api('csrf-token');
        csrfToken.value = csrf.token;
        mailClient.connect();
        setupPushHandlers();
        loadProfile();
        await loadEmailMap();
        loadFolders();
      } catch (e) {
        // Network error or `api()` already triggered a redirect — leave
        // the cached chrome visible; the user can retry on reconnect.
      }
    }

    async function loadProfile() {
      try { profile.value = await api('api/profile'); } catch { /* ignore */ }
    }

    async function loadEmailMap() {
      try {
        const data = await api('api/people/email-map');
        emailMap.value = data || {};
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

    function _applyFolders(list) {
      folders.value = list;
      if (!selectedFolder.value) {
        const inbox = list.find(f => f.name.toLowerCase() === 'inbox');
        if (inbox) { selectedFolder.value = inbox.id; currentFolderName.value = inbox.name; }
        else if (list.length) { selectedFolder.value = list[0].id; currentFolderName.value = list[0].name; }
      }
    }

    // ── Movable splitters ─────────────────────────────────
    // Two drag-handles between the three mail panes.  Widths are
    // persisted per-pane in localStorage so they survive reloads.
    // Clamp to sensible min/max so a user can't shrink a pane to zero.
    const _SPLIT_KEY = 'mail_split_widths';
    const _splitDefaults = { sidebar: 240, list: 420 };
    const _splitStored = (() => {
      try { return JSON.parse(localStorage.getItem(_SPLIT_KEY) || '{}'); }
      catch { return {}; }
    })();
    const folderSidebarWidth = ref(_splitStored.sidebar || _splitDefaults.sidebar);
    const messageListWidth   = ref(_splitStored.list    || _splitDefaults.list);

    function _clampWidth(kind, w) {
      if (kind === 'sidebar') return Math.max(160, Math.min(w, 420));
      return Math.max(280, Math.min(w, 720));  // message list
    }

    function _persistSplit() {
      try {
        localStorage.setItem(_SPLIT_KEY, JSON.stringify({
          sidebar: folderSidebarWidth.value,
          list: messageListWidth.value,
        }));
      } catch { /* quota — ignore */ }
    }

    function startSplitDrag(ev, kind) {
      ev.preventDefault();
      const startX = ev.clientX;
      const startW = kind === 'sidebar'
        ? folderSidebarWidth.value
        : messageListWidth.value;

      // Disable pointer events on every iframe while dragging.  The
      // mail-body iframe sits immediately right of the right-hand
      // splitter; without this, once the cursor crosses into it the
      // browser routes ``mousemove`` / ``mouseup`` to the iframe's
      // document and our document-level listeners stop firing — the
      // drag appears to "stick" until the user clicks again.
      const iframes = document.querySelectorAll('iframe');
      const prevIframePE = [];
      iframes.forEach((f) => {
        prevIframePE.push(f.style.pointerEvents);
        f.style.pointerEvents = 'none';
      });

      const onMove = (e) => {
        const delta = e.clientX - startX;
        const next = _clampWidth(kind, startW + delta);
        if (kind === 'sidebar') folderSidebarWidth.value = next;
        else messageListWidth.value = next;
      };
      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        document.removeEventListener('mouseleave', onUp);
        window.removeEventListener('blur', onUp);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        iframes.forEach((f, i) => { f.style.pointerEvents = prevIframePE[i] || ''; });
        _persistSplit();
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
      // Belt-and-braces: end the drag if the cursor leaves the viewport
      // or the window loses focus mid-drag.  Avoids the "stuck" state
      // when the user releases outside the window.
      document.addEventListener('mouseleave', onUp);
      window.addEventListener('blur', onUp);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    }

    // ── Folder tree (hierarchical) ────────────────────────
    // MS Graph returns a flat list of folders with ``parent_id`` pointing
    // at the parent; we build a tree and then flatten to a depth-tagged
    // array for render.  Expanded/collapsed state is persisted per folder
    // id in localStorage — default is ``expanded`` for the inbox and its
    // children, collapsed for everything else at load time.
    const _FOLDER_EXP_KEY = 'mail_folder_expanded';
    const expandedFolders = reactive((() => {
      try { return JSON.parse(localStorage.getItem(_FOLDER_EXP_KEY) || '{}'); }
      catch { return {}; }
    })());

    function toggleFolder(id) {
      expandedFolders[id] = expandedFolders[id] === false;
      try { localStorage.setItem(_FOLDER_EXP_KEY, JSON.stringify(expandedFolders)); }
      catch { /* quota — ignore */ }
    }

    const _ROOT_ORDER = [
      'inbox', 'drafts', 'sent items', 'sent', 'archive',
      'deleted items', 'trash', 'junk email', 'junk', 'spam',
      'outbox', 'notes', 'conversation history', 'rss feeds',
    ];

    function _rootRank(name) {
      const n = (name || '').toLowerCase();
      const i = _ROOT_ORDER.indexOf(n);
      return i === -1 ? 99 : i;
    }

    const folderTree = computed(() => {
      const list = folders.value || [];
      if (!list.length) return [];
      // Graph's top-level mailbox folders have ``parent_id`` pointing at a
      // virtual "msgfolderroot".  Anything whose ``parent_id`` is missing
      // from the response gets promoted to a root node so deep-linked
      // folders don't vanish.
      const byId = new Map(list.map(f => [f.id, f]));
      const children = new Map();
      const roots = [];
      for (const f of list) {
        const p = f.parent_id;
        if (p && byId.has(p)) {
          if (!children.has(p)) children.set(p, []);
          children.get(p).push(f);
        } else {
          roots.push(f);
        }
      }
      // Sort roots by convention, children alphabetically.
      roots.sort((a, b) => {
        const ra = _rootRank(a.name), rb = _rootRank(b.name);
        if (ra !== rb) return ra - rb;
        return (a.name || '').localeCompare(b.name || '');
      });
      const out = [];
      function walk(node, depth) {
        const kids = children.get(node.id) || [];
        const hasChildren = kids.length > 0;
        out.push({
          id: node.id,
          name: node.name,
          unread: node.unread,
          total: node.total,
          depth,
          hasChildren,
        });
        if (hasChildren && expandedFolders[node.id] !== false) {
          kids.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
          for (const kid of kids) walk(kid, depth + 1);
        }
      }
      for (const r of roots) walk(r, 0);
      return out;
    });

    async function loadFolders() {
      // Cache-first: paint from IndexedDB immediately, then refresh via WS.
      try {
        const cached = await cache.getFolders();
        if (cached && cached.length) {
          _applyFolders(cached);
          loadMessages(); // paint cached messages while WS loads
        }
      } catch { /* cache miss — no-op */ }

      try {
        const data = await mailClient.request('folders');
        isOnline.value = true;
        _applyFolders(data.folders);
        cache.setFolders(data.folders).catch(() => {});
        loadMessages();
      } catch (e) {
        isOnline.value = false;
        // If we already painted from cache, don't blank the UI.
        if (!folders.value.length) {
          toast('Failed to load folders: ' + e.message, 'error');
        }
      }
    }

    // ── Last-selected-mail memory ─────────────────────────
    // Remember the most recently opened mail per folder so the reading
    // pane restores on reload / folder revisit.  Stored in
    // localStorage; bounded to the last N folders to keep the footprint
    // small.
    const _LAST_SEL_KEY = 'mail_last_selected';
    const _lastSelected = (() => {
      try { return JSON.parse(localStorage.getItem(_LAST_SEL_KEY) || '{}'); }
      catch { return {}; }
    })();
    function _rememberSelected(folderId, messageId) {
      if (!folderId || !messageId) return;
      _lastSelected[folderId] = messageId;
      // Cap — drop oldest entries if we have more than 50 folders.
      const keys = Object.keys(_lastSelected);
      if (keys.length > 50) delete _lastSelected[keys[0]];
      try { localStorage.setItem(_LAST_SEL_KEY, JSON.stringify(_lastSelected)); }
      catch { /* quota — ignore */ }
    }
    function _restoreSelectedForFolder(folderId) {
      const wantId = _lastSelected[folderId];
      if (!wantId) return;
      if (!messages.value.find(m => m.id === wantId)) return;
      openMessage(wantId);
    }

    async function selectFolder(id) {
      selectedFolder.value = id;
      const f = folders.value.find(x => x.id === id);
      currentFolderName.value = f ? f.name : '';
      selectedMessage.value = null;
      await loadMessages();
      _restoreSelectedForFolder(id);
    }

    // Pagination state per folder.  ``messageTotal`` is the server's
    // authoritative count; ``loadingMore`` gates the scroll handler so
    // we don't spam the server when the user is dragging the scrollbar.
    const MAIL_PAGE_SIZE = 50;
    const messageTotal = ref(0);
    const loadingMore = ref(false);

    // Per-folder load tokens — every folder switch bumps this.  Any
    // stale fetch that lands after a newer switch is dropped so the
    // old folder's rows can't race in on top of the new one's.
    let _loadMessagesToken = 0;

    async function loadMessages() {
      const folderId = selectedFolder.value;
      const token = ++_loadMessagesToken;

      // Clear the list immediately on folder switch.  Without this the
      // previous folder's messages remain visible while the fetch is
      // in flight, and — worse — a since_sig that happens to match an
      // empty-folder hash short-circuits the replace and the stale
      // rows stay forever.
      messages.value = [];
      filteredMessages.value = [];

      // 1. Cache-first: paint from IndexedDB immediately.
      let sinceSig = null;
      let paintedFromCache = false;
      try {
        const cached = await cache.getMessagesIndex(folderId);
        if (token !== _loadMessagesToken) return;
        if (cached && cached.length) {
          messages.value = cached;
          filterMessages();
          paintedFromCache = true;
          sinceSig = await cache.getSinceSig(folderId);
        }
        // When the cache is empty we deliberately skip ``since_sig`` so
        // the server always sends the full payload — otherwise an
        // unrelated sig match from a prior visit would flip the response
        // to ``{unchanged:true}`` and leave the list empty.
      } catch { /* cache miss */ }

      // Spinner only when we truly have nothing to show.
      loadingMail.value = messages.value.length === 0;

      // 2. Delta-sync via WS with since_sig.
      try {
        const params = { folder_id: folderId, limit: MAIL_PAGE_SIZE };
        if (sinceSig) params.since_sig = sinceSig;
        const data = await mailClient.request('messages', params);
        if (token !== _loadMessagesToken) return;  // folder changed mid-fetch
        isOnline.value = true;

        if (!data.unchanged) {
          // Full or delta response — replace the list unconditionally.
          // ``data.messages`` may be an empty array (empty folder) —
          // assigning it explicitly is what clears the display.
          messages.value = Array.isArray(data.messages) ? data.messages : [];
          filterMessages();
          if (data.messages && data.messages.length) {
            cache.mergeMessagesIndex(folderId, data.messages).catch(() => {});
          }
        }
        if (typeof data.total === 'number') messageTotal.value = data.total;
        if (data.sig) {
          cache.setSinceSig(folderId, data.sig).catch(() => {});
        }
      } catch (e) {
        if (token !== _loadMessagesToken) return;
        isOnline.value = false;
        if (!messages.value.length) {
          toast('Failed to load messages: ' + e.message, 'error');
        }
      } finally {
        if (token === _loadMessagesToken) loadingMail.value = false;
      }
    }

    /** Infinite-scroll handler bound to the message-list scroll region.
     *  Fires when the user is within ~400 px of the bottom. */
    function onMessageListScroll(ev) {
      const el = ev.target;
      if (!el) return;
      const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
      if (remaining < 400) loadMoreMessages();
    }

    /** Load the next page of messages when the user scrolls near the
     *  bottom of the list.  Appends to ``messages.value`` and caches
     *  the merged rows.  No-ops when we already have the full folder or
     *  a fetch is already in flight.
     */
    async function loadMoreMessages() {
      if (loadingMore.value) return;
      if (mailSearch.value.trim()) return;   // search results don't paginate
      const folderId = selectedFolder.value;
      if (!folderId) return;
      const have = messages.value.length;
      if (messageTotal.value && have >= messageTotal.value) return;
      loadingMore.value = true;
      try {
        const data = await mailClient.request('messages', {
          folder_id: folderId,
          limit: MAIL_PAGE_SIZE,
          skip: have,
        });
        isOnline.value = true;
        if (data.messages && data.messages.length) {
          // Merge — server may return duplicates if the folder changed
          // underneath us; key by id.
          const seen = new Set(messages.value.map(m => m.id));
          const fresh = data.messages.filter(m => !seen.has(m.id));
          messages.value = messages.value.concat(fresh);
          filterMessages();
          cache.mergeMessagesIndex(folderId, data.messages).catch(() => {});
        }
        if (typeof data.total === 'number') messageTotal.value = data.total;
      } catch (e) {
        isOnline.value = false;
      } finally {
        loadingMore.value = false;
      }
    }

    let _readTimer = null;

    // ── Reactions (Outlook emoji responses) ───────────────
    // Reactions live under ``reactionsByMsgId[email_id]`` as an array
    // of ``{reactionType, user:{displayName, emailAddress}}``.  The
    // reading-pane template groups them by type and renders a pill
    // bar under the header; clicking a pill toggles the current
    // user's reaction of that type (add if absent, clear if present).
    const REACTION_EMOJI = {
      like: '👍', heart: '❤️', laugh: '😂',
      surprised: '😮', sad: '😢', angry: '😡',
      celebrate: '🎉', thumbsdown: '👎',
    };
    const REACTION_PALETTE = ['like', 'heart', 'laugh', 'celebrate', 'surprised', 'sad'];
    const reactionsByMsgId = reactive({});
    const showReactionPicker = ref(false);

    function reactionEmoji(t) { return REACTION_EMOJI[t] || '👍'; }

    const currentReactions = computed(() => {
      const mail = selectedMessage.value;
      if (!mail) return [];
      const entries = reactionsByMsgId[mail.email_id] || [];
      const byType = {};
      for (const r of entries) {
        const t = r.reactionType || 'like';
        if (!byType[t]) byType[t] = { type: t, count: 0, mine: false, users: [] };
        byType[t].count++;
        const who = (r.user && r.user.displayName) || '';
        byType[t].users.push(who);
        if (profile.value && who && (who === profile.value.displayName
            || who === profile.value.givenName)) {
          byType[t].mine = true;
        }
      }
      return Object.values(byType);
    });

    async function loadReactions(messageId) {
      try {
        const resp = await mailClient.request('get_reactions', { message_id: messageId });
        if (resp && Array.isArray(resp.reactions)) {
          reactionsByMsgId[messageId] = resp.reactions;
        }
      } catch { /* silent */ }
    }

    async function toggleReaction(reactionType) {
      const mail = selectedMessage.value;
      if (!mail) return;
      const cur = currentReactions.value.find(r => r.type === reactionType);
      const removing = cur && cur.mine;
      showReactionPicker.value = false;
      try {
        const resp = removing
          ? await mailClient.request('unset_reaction', { message_id: mail.email_id })
          : await mailClient.request('set_reaction', {
              message_id: mail.email_id, reaction_type: reactionType,
            });
        if (resp && resp.error) {
          toast(resp.error, 'error');
          return;
        }
        await loadReactions(mail.email_id);
      } catch (e) {
        toast('Reaction failed: ' + e.message, 'error');
      }
    }

    // Auto-refresh reactions whenever a new mail is opened.
    watch(() => selectedMessage.value && selectedMessage.value.email_id, (id) => {
      if (id) loadReactions(id);
    });

    // ── External-image policy ─────────────────────────────
    // By default, remote ``<img src="https://…">`` links in mail bodies
    // are stripped before rendering (privacy / tracking-pixel defence).
    // The host can whitelist senders via ``hooks.isTrustedSender``; the
    // user can also force-show via the banner button.
    const externalImagesShown = ref(false);   // user override per-message
    const externalImagesBlocked = ref(0);     // count stripped in current body

    // ── User-managed trust list ──────────────────────────
    // Host config contributes a *base* trust list (typically the
    // customer's own domains).  The user can add senders / domains on
    // the fly via the external-image banner; those additions persist
    // in localStorage and override the host list.
    const _USER_TRUST_KEY = 'mail_user_trust';
    const _userTrust = reactive(
      (() => {
        try { return JSON.parse(localStorage.getItem(_USER_TRUST_KEY) || '{"senders":[],"domains":[]}'); }
        catch { return { senders: [], domains: [] }; }
      })(),
    );
    function _persistUserTrust() {
      try { localStorage.setItem(_USER_TRUST_KEY, JSON.stringify(_userTrust)); }
      catch { /* quota exceeded — best-effort */ }
    }

    function _emailDomain(email) {
      if (!email) return '';
      return String(email).toLowerCase().split('@').pop() || '';
    }

    function _domainMatches(domain, trusted) {
      if (!domain || !trusted) return false;
      const d = domain.toLowerCase();
      const t = trusted.toLowerCase();
      return d === t || d.endsWith('.' + t);
    }

    function _senderTrusted(mail) {
      const email = ((mail && mail.from_email) || '').toLowerCase();
      const domain = _emailDomain(email);
      // 1) User-added senders (exact match).
      if (email && _userTrust.senders.includes(email)) return true;
      // 2) User-added domains (suffix match).
      if (domain && _userTrust.domains.some(d => _domainMatches(domain, d))) return true;
      // 3) Host-provided trust hook.
      try { if (hooks.isTrustedSender(email, domain)) return true; }
      catch (e) { console.warn('[mail] isTrustedSender threw:', e); }
      return false;
    }

    function trustCurrentSender() {
      const mail = selectedMessage.value;
      const email = ((mail && mail.from_email) || '').toLowerCase();
      if (!email) return;
      if (!_userTrust.senders.includes(email)) {
        _userTrust.senders.push(email);
        _persistUserTrust();
        toast('Trusted ' + email, 'success');
      }
      externalImagesShown.value = true;
    }

    function trustCurrentDomain() {
      const mail = selectedMessage.value;
      const domain = _emailDomain((mail && mail.from_email) || '');
      if (!domain) return;
      if (!_userTrust.domains.includes(domain)) {
        _userTrust.domains.push(domain);
        _persistUserTrust();
        toast('Trusted domain ' + domain, 'success');
      }
      externalImagesShown.value = true;
    }

    function forgetTrust(kind, value) {
      const key = kind === 'domain' ? 'domains' : 'senders';
      const idx = _userTrust[key].indexOf(value);
      if (idx >= 0) {
        _userTrust[key].splice(idx, 1);
        _persistUserTrust();
      }
    }

    // Derived flag: what's shown above the banner menu ("Trust sender
    // foo@bar.com" / "Trust domain bar.com").  Defensive on missing
    // fields so the menu can still render for senderless mails.
    const currentSenderEmail = computed(() => {
      const m = selectedMessage.value;
      return ((m && m.from_email) || '').toLowerCase();
    });
    const currentSenderDomain = computed(() => _emailDomain(currentSenderEmail.value));

    function _sanitizeBody(rawHtml, trustImages) {
      if (!rawHtml) return { html: '', stripped: 0 };
      const doc = new DOMParser().parseFromString(rawHtml, 'text/html');
      // Drop ``<script>`` and inline event handlers.  The iframe sandbox
      // already blocks them (and Chrome logs every blocked eval); this
      // just makes the console quiet and saves a pointless parse step
      // inside the sandbox.
      for (const s of doc.querySelectorAll('script, object, embed')) s.remove();
      const evtAttrs = [
        'onload', 'onerror', 'onclick', 'onmouseover', 'onmouseout',
        'onfocus', 'onblur', 'onsubmit', 'onreset', 'onchange', 'oninput',
      ];
      for (const el of doc.querySelectorAll('*')) {
        for (const a of evtAttrs) el.removeAttribute(a);
      }
      let stripped = 0;
      for (const img of doc.querySelectorAll('img')) {
        const src = img.getAttribute('src') || '';
        // Allow data: (inlined cid), blob:, and relative URLs unconditionally.
        if (!/^https?:\/\//i.test(src)) continue;
        if (trustImages) continue;
        img.setAttribute('data-original-src', src);
        img.removeAttribute('src');
        img.setAttribute('alt', '[external image blocked]');
        img.style.cssText = 'display:none';
        stripped++;
      }
      return { html: doc.body ? doc.body.innerHTML : '', stripped };
    }

    // ── Mail-body theme (independent of app theme) ────────
    // Tri-state, persisted in localStorage under ``mail_body_theme``:
    //   'auto'   — follows the app chrome (``theme`` ref)
    //   'light'  — force light, regardless of app theme
    //   'dark'   — force dark, regardless of app theme
    // Emails ship with their own inline styles that the app-level
    // CSS-vars flip doesn't reach, so users need a separate lever for
    // the reading pane.  "Auto" is the default so new visitors get the
    // usual dark-desktop → dark-mail behaviour without opt-in.
    const _BODY_THEMES = ['auto', 'light', 'dark'];
    const _storedBodyTheme = (() => {
      const raw = localStorage.getItem('mail_body_theme');
      if (_BODY_THEMES.includes(raw)) return raw;
      // Migrate the old boolean key if present.
      const legacy = localStorage.getItem('mail_body_dark');
      if (legacy === '1') return 'dark';
      if (legacy === '0') return 'light';
      return 'auto';
    })();
    const bodyTheme = ref(_storedBodyTheme);
    const effectiveBodyTheme = computed(() => {
      return bodyTheme.value === 'auto' ? theme.value : bodyTheme.value;
    });
    const bodyDarkMode = computed(() => effectiveBodyTheme.value === 'dark');

    function cycleBodyTheme() {
      const i = _BODY_THEMES.indexOf(bodyTheme.value);
      setBodyTheme(_BODY_THEMES[(i + 1) % _BODY_THEMES.length]);
    }

    function setBodyTheme(next) {
      if (!_BODY_THEMES.includes(next)) return;
      bodyTheme.value = next;
      try {
        localStorage.setItem('mail_body_theme', next);
        // Drop the legacy key so we don't keep two sources of truth.
        localStorage.removeItem('mail_body_dark');
      } catch {}
    }

    // Kept for callers that only care about the boolean.
    function toggleBodyDark() {
      bodyTheme.value = bodyDarkMode.value ? 'light' : 'dark';
      try {
        localStorage.setItem('mail_body_theme', bodyTheme.value);
        localStorage.removeItem('mail_body_dark');
      } catch {}
    }

    // Font + base colours — light by default.
    const BODY_FONT_STYLE_LIGHT = [
      "<style>",
      "html,body{margin:0;padding:16px 4px;",
      "font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,system-ui,'Helvetica Neue',Roboto,Arial,sans-serif;",
      "font-size:15px;line-height:1.55;color:#201f1e;background:#fff;}",
      "body>*:first-child{margin-top:0;}",
      "blockquote{border-left:3px solid #c8c6c4;margin:0 0 0 4px;padding-left:12px;color:#605e5c;}",
      "a{color:#0078d4;}",
      "pre,code{font-family:Menlo,Consolas,'Liberation Mono',monospace;font-size:13px;}",
      "</style>",
    ].join('');

    // Dark mail body — uses the ``invert(1) hue-rotate(180deg)`` pattern
    // on the html root (flips every colour in the email), then re-applies
    // the same filter to media elements so images / videos / embedded
    // SVGs come back out looking normal.  This plays well with inline
    // styled HTML without trying to rewrite every ``style="..."``.
    const BODY_FONT_STYLE_DARK = [
      "<style>",
      "html{color-scheme:dark;background:#242424;",
      "filter:invert(0.92) hue-rotate(180deg);}",
      "html,body{margin:0;padding:16px 4px;",
      "font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,system-ui,'Helvetica Neue',Roboto,Arial,sans-serif;",
      "font-size:15px;line-height:1.55;color:#201f1e;background:#fff;}",
      "body>*:first-child{margin-top:0;}",
      "blockquote{border-left:3px solid #c8c6c4;margin:0 0 0 4px;padding-left:12px;color:#605e5c;}",
      "a{color:#0078d4;}",
      "pre,code{font-family:Menlo,Consolas,'Liberation Mono',monospace;font-size:13px;}",
      "img,video,picture,iframe,embed,object,svg{",
      "filter:invert(1) hue-rotate(180deg);}",
      "</style>",
    ].join('');

    const displayBody = computed(() => {
      const mail = selectedMessage.value;
      if (!mail) return '';
      const trust = externalImagesShown.value || _senderTrusted(mail);
      const { html, stripped } = _sanitizeBody(mail.body || '', trust);
      externalImagesBlocked.value = stripped;
      const style = bodyDarkMode.value ? BODY_FONT_STYLE_DARK : BODY_FONT_STYLE_LIGHT;
      return style + html;
    });

    function showExternalImagesForCurrent() {
      externalImagesShown.value = true;
    }

    // ── Attachment prefetch + virus-scan recheck ──────────
    // Host opt-in: when ``hooks.shouldPrefetchAttachments`` returns
    // ``true`` or a list of filenames, we fire HTTP GETs for those
    // attachments so the browser's disk cache is warm before the user
    // clicks.  Binary blobs are NOT persisted in MailCache (size
    // unpredictable); the download endpoint serves with a 5-min
    // ``Cache-Control`` header, which is sufficient for the "opened
    // the order" scenario.
    function _attachmentUrl(messageId, name) {
      return 'api/mail/messages/' + encodeURIComponent(messageId)
        + '/attachments/' + encodeURIComponent(name);
    }

    /** Fetch one attachment blob and store it in IndexedDB.  Idempotent
     *  — subsequent calls touch ``last_access`` (keeping the blob warm
     *  in the LRU) instead of re-downloading.  The returned Promise
     *  resolves to the cached ``{ blob, content_type }`` or ``null`` on
     *  failure. */
    async function _fetchAttachmentToCache(messageId, name, contentType) {
      try {
        const existing = await cache.getAttachment(messageId, name);
        if (existing && existing.blob) return existing;
      } catch {}
      try {
        const resp = await fetch(_attachmentUrl(messageId, name), { credentials: 'same-origin' });
        if (!resp.ok) return null;
        const blob = await resp.blob();
        const ct = contentType || resp.headers.get('content-type') || blob.type;
        await cache.setAttachment(messageId, name, blob, ct);
        return { blob, content_type: ct, size: blob.size };
      } catch {
        return null;
      }
    }

    function _maybePrefetchAttachments(mail) {
      if (!mail || !mail.email_id || !mail.attachments) return;
      let want;
      try {
        want = hooks.shouldPrefetchAttachments(mail, {
          selectedFolder: selectedFolder.value,
          profile: profile.value,
        });
      } catch (e) {
        console.warn('[mail] shouldPrefetchAttachments threw:', e);
        return;
      }
      if (!want) return;
      const allowList = Array.isArray(want) ? new Set(want) : null;
      for (const att of mail.attachments) {
        if (att.is_embedded) continue;
        if (allowList && !allowList.has(att.name)) continue;
        // Fire-and-forget — fills the IDB cache.  ``getAttachment`` will
        // be hit when the user eventually clicks the link.
        _fetchAttachmentToCache(mail.email_id, att.name, att.content_type);
      }
    }

    /** Click handler for attachment links — returns the cached blob as
     *  an object URL if we have one, otherwise falls through to the
     *  HTTP download endpoint. */
    async function openAttachment(ev, att) {
      if (!selectedMessage.value) return;
      const messageId = selectedMessage.value.email_id;
      try {
        const cached = await cache.getAttachment(messageId, att.name);
        if (cached && cached.blob) {
          ev.preventDefault();
          const url = URL.createObjectURL(cached.blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = att.name;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(() => URL.revokeObjectURL(url), 60000);
          return;
        }
      } catch { /* cache miss — let the browser hit HTTP */ }
      // No override — the ``<a>`` element's native href does the download.
      // Warm the cache in the background so a second click is instant.
      _fetchAttachmentToCache(messageId, att.name, att.content_type);
    }

    // When a mail is opened while still being virus-scanned, the server
    // returns ``scanning:true`` with no real attachments.  Poll until
    // the scan completes; evict the stale body + reload.
    const _scanRecheckTimers = new Map();
    function _scheduleScanRecheck(messageId, attempt) {
      attempt = attempt || 1;
      if (attempt > 12) return;  // ~2 min at the delays below
      const delayMs = Math.min(30000, 3000 * attempt);
      if (_scanRecheckTimers.has(messageId)) {
        clearTimeout(_scanRecheckTimers.get(messageId));
      }
      const t = setTimeout(async () => {
        _scanRecheckTimers.delete(messageId);
        try {
          const detail = await mailClient.request('get_mail', { message_id: messageId });
          if (detail && detail.error) throw new Error(detail.error);
          if (detail.scanning) {
            _scheduleScanRecheck(messageId, attempt + 1);
            return;
          }
          // Scan done — evict stale cached body + re-show if user is
          // still viewing this mail.
          cache.evictBody(messageId).catch(() => {});
          cache.setBody(messageId, detail).catch(() => {});
          if (selectedMessage.value && selectedMessage.value.email_id === messageId) {
            selectedMessage.value = detail;
            _maybePrefetchAttachments(detail);
          }
        } catch { /* transient — drop this attempt */ }
      }, delayMs);
      _scanRecheckTimers.set(messageId, t);
    }

    async function openMessage(id) {
      // Cancel any pending mark-as-read from previous message
      if (_readTimer) { clearTimeout(_readTimer); _readTimer = null; }

      // Reset per-message external-image state on every open.
      externalImagesShown.value = false;
      externalImagesBlocked.value = 0;

      // Cache-first: show cached body instantly if available.
      try {
        const cached = await cache.getBody(id);
        if (cached) { selectedMessage.value = cached; }
      } catch { /* cache miss */ }

      try {
        // Mail body + headers + attachment metadata travel over the
        // WebSocket (llming-com).  Only attachment binaries are on
        // HTTP — see docs/mail-architecture.md.
        const detail = await mailClient.request('get_mail', { message_id: id });
        if (detail && detail.error) throw new Error(detail.error);
        selectedMessage.value = detail;
        _rememberSelected(selectedFolder.value, id);

        // Don't cache bodies that are still being virus-scanned.
        if (!detail.scanning) {
          cache.setBody(id, detail).catch(() => {});
        } else {
          // Still scanning — schedule a re-open so the real body + real
          // attachments replace the placeholder once the scan completes.
          _scheduleScanRecheck(id);
        }

        // Let the host pre-warm attachment blobs (the only HTTP-routed
        // mail data) if it decides this mail warrants it.
        _maybePrefetchAttachments(detail);

        // Mark as read after 3.5s delay (like Outlook) — cancelled if user navigates away
        const msg = messages.value.find(m => m.id === id);
        if (msg && !msg.is_read) {
          _readTimer = setTimeout(() => {
            // Only mark if this message is still the selected one
            if (selectedMessage.value && selectedMessage.value.email_id === id) {
              msg.is_read = true;
              mailClient.request('mark_read', { message_id: id }).catch(() => {});
            }
            _readTimer = null;
          }, 3500);
        }
      } catch (e) {
        // If we showed a cached body, keep it visible.
        if (!selectedMessage.value) {
          toast('Failed to load message: ' + e.message, 'error');
        }
      }
    }

    // ════════════════════════════════════════════════════════
    // PUSH HANDLERS
    // ════════════════════════════════════════════════════════

    let _audioCtx = null;
    function playPing() {
      if (!soundEnabled.value) return;
      try {
        if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const ctx = _audioCtx;
        const now = ctx.currentTime;
        // Two-tone chime: 880 Hz then 1320 Hz, 80ms each
        [880, 1320].forEach((freq, i) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = 'sine';
          osc.frequency.value = freq;
          gain.gain.setValueAtTime(0.3, now + i * 0.08);
          gain.gain.exponentialRampToValueAtTime(0.001, now + i * 0.08 + 0.15);
          osc.connect(gain).connect(ctx.destination);
          osc.start(now + i * 0.08);
          osc.stop(now + i * 0.08 + 0.15);
        });
      } catch { /* Web Audio not available */ }
    }

    function toggleSound() {
      soundEnabled.value = !soundEnabled.value;
      localStorage.setItem('mail_sound', soundEnabled.value ? 'on' : 'off');
    }

    /** Silently prefetch a message body so opening it is instant.
     *  Routes through the WebSocket (``get_mail``) so the HTTP channel
     *  is reserved for attachment binaries only. */
    async function prefetchBody(messageId) {
      try {
        const detail = await mailClient.request('get_mail', { message_id: messageId });
        if (detail && !detail.error && !detail.scanning) {
          cache.setBody(messageId, detail).catch(() => {});
          _maybePrefetchAttachments(detail);
        }
      } catch { /* silent — best effort */ }
    }

    function setupPushHandlers() {
      mailClient.onPush((msg) => {
        const action = msg.action;

        if (action === 'mail.new_mail') {
          playPing();
          const row = msg.message;
          // folder_id from push is "inbox" (literal), selectedFolder is the Graph UUID.
          // Match either by exact ID or by name when push says "inbox".
          const pushFolder = msg.folder_id || 'inbox';
          const isCurrentFolder = pushFolder === selectedFolder.value
            || (pushFolder === 'inbox' && currentFolderName.value.toLowerCase() === 'inbox');
          if (row && isCurrentFolder) {
            messages.value = [row, ...messages.value.filter(m => m.id !== row.id)];
            filterMessages();
          }
          // Cache the index row and silently prefetch the body.
          if (row) {
            cache.mergeMessagesIndex(selectedFolder.value, [row]).catch(() => {});
            prefetchBody(row.id);
          }
        }

        if (action === 'mail.scan_done') {
          const id = msg.message_id;
          // Evict stale body + any attachment blobs harvested during
          // the scanning window (they were placeholders).
          cache.evictBody(id).catch(() => {});
          cache.evictAttachmentsFor(id).catch(() => {});
          // If the user is currently reading this message, re-fetch.
          if (selectedMessage.value && selectedMessage.value.email_id === id) {
            openMessage(id);
          }
        }

        if (action === 'mail.changed') {
          // Generic change — invalidate and refresh.
          loadMessages();
        }
      });
    }

    // ════════════════════════════════════════════════════════
    // COMPOSE
    // ════════════════════════════════════════════════════════

    // Live handle to the rich compose editor (<div contenteditable>).
    const composeEditor = ref(null);

    function onComposeEditorInput() {
      if (composeEditor.value) compose.body = composeEditor.value.innerHTML;
    }

    /** Execute a rich-text formatting command on the current editor
     *  selection.  Uses ``document.execCommand`` — legacy but still the
     *  only cross-browser way to issue Bold/Italic/Underline/List
     *  without writing a full IMEditor.  Keeps the editor focused so
     *  the toolbar doesn't steal the caret. */
    function execFormat(cmd, value) {
      const el = composeEditor.value;
      if (!el) return;
      el.focus();
      try { document.execCommand(cmd, false, value || null); } catch (e) {
        console.warn('[mail] execCommand failed:', cmd, e);
      }
      onComposeEditorInput();
    }

    function insertLink() {
      const url = window.prompt('Link URL');
      if (!url) return;
      // Best-effort validation so ``javascript:`` URIs etc. don't slip in.
      if (!/^(https?:|mailto:)/i.test(url)) {
        toast('Only http(s): and mailto: links are allowed', 'warning');
        return;
      }
      execFormat('createLink', url);
    }

    function attachFile() {
      // Attachments aren't wired through Graph yet — surface a clear
      // stub so the toolbar is visibly consistent until we plug into
      // the /sendMail MIME-attach path.
      toast('Attachment upload coming soon', 'info');
    }

    // Ctrl/⌘+B/I/U shortcuts inside the editor.  Native contenteditable
    // already handles these, but browsers are inconsistent about
    // syncing back to the ``input`` event — force a sync here.
    function onComposeKeyDown(ev) {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      const key = ev.key.toLowerCase();
      if (['b', 'i', 'u', 'k'].includes(key)) {
        // Let the browser apply the format; sync afterwards.
        if (key === 'k') { ev.preventDefault(); insertLink(); return; }
        setTimeout(onComposeEditorInput, 0);
      }
    }

    /** Push HTML into the editor DOM + keep ``compose.body`` in sync.
     *  Waited on via ``nextTick`` so it runs after Vue swaps the
     *  compose view in.  Places the caret at the top so the user can
     *  type their message above the quoted original. */
    function _seedComposeBody(html) {
      compose.body = html || '';
      nextTick(() => {
        const el = composeEditor.value;
        if (!el) return;
        el.innerHTML = html || '';
        el.focus();
        // Place caret at the very start of the editor.
        const sel = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(el);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      });
    }

    /** Build a quoted-block wrapper for reply / forward bodies.  Uses
     *  the same sanitiser as the reading pane so external images are
     *  stripped, scripts removed, etc.  ``header`` is a plain-text
     *  line prefixed before the quoted body (e.g. "On … wrote:"). */
    function _buildQuotedBlock(mail, header) {
      if (!mail || !mail.body) {
        return '<br><br><blockquote style="border-left:3px solid #c8c6c4;margin:0;padding-left:12px;color:#605e5c">'
          + _escHtml(header) + '<br>' + _escHtml(mail && (mail.body_preview || '') || '')
          + '</blockquote>';
      }
      // Sanitize the original body just like we do for display.
      const { html } = _sanitizeBody(mail.body, _senderTrusted(mail));
      return [
        '<br><br>',
        '<div style="color:#605e5c;font-size:12px;margin-bottom:4px">',
        _escHtml(header),
        '</div>',
        '<blockquote style="border-left:3px solid #c8c6c4;margin:0 0 0 2px;padding-left:12px;color:#605e5c">',
        html,
        '</blockquote>',
      ].join('');
    }

    function _escHtml(s) {
      return String(s || '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function startCompose(prefillTo) {
      compose.toList = prefillTo ? [prefillTo] : [];
      compose.toInput = '';
      compose.ccList = [];
      compose.ccInput = '';
      compose.bccList = [];
      compose.bccInput = '';
      compose.subject = '';
      compose.replyTo = null;
      compose.isForward = false;
      compose.isReplyAll = false;
      showCcBcc.value = false;
      toSuggestions.value = [];
      composeMode.value = true;
      _seedComposeBody('');
    }

    function startReply(replyAll) {
      if (!selectedMessage.value) return;
      const m = selectedMessage.value;
      const toAddrs = [m.from_email].filter(Boolean);
      let ccAddrs = [];
      if (replyAll) {
        const meEmail = (profile.value && profile.value.email || '').toLowerCase();
        // Reply-all adds every non-me recipient of the original to Cc.
        ccAddrs = [
          ...((m.to_recipients || []).map(r => typeof r === 'string' ? r : (r && r.email_address && r.email_address.address) || '')),
          ...((m.cc_recipients || []).map(r => typeof r === 'string' ? r : (r && r.email_address && r.email_address.address) || '')),
        ].filter(a => a && a.toLowerCase() !== meEmail && !toAddrs.includes(a));
      }
      compose.toList = toAddrs;
      compose.toInput = '';
      compose.ccList = ccAddrs;
      compose.ccInput = '';
      compose.bccList = [];
      compose.bccInput = '';
      compose.subject = (m.subject || '').match(/^re:/i) ? m.subject : 'Re: ' + (m.subject || '');
      compose.replyTo = m.email_id;
      compose.isForward = false;
      compose.isReplyAll = !!replyAll;
      showCcBcc.value = ccAddrs.length > 0;
      toSuggestions.value = [];
      composeMode.value = true;
      // Show the quoted original in the editor so the user has context
      // while typing.  Everything after the ``ldoc-reply-sep`` marker
      // is stripped before we send — Graph's ``/reply`` endpoint
      // quotes the original itself, so we only ship the user's new
      // text as ``comment`` (no duplicated quote in the delivered mail).
      const header = 'On ' + formatFullDate(m.local_timestamp || m.received)
        + ', ' + (m.from_name || m.from_email || '') + ' wrote:';
      const sep = '<hr class="ldoc-reply-sep" data-ldoc-strip="1">';
      _seedComposeBody(
        '<p><br></p>'
        + sep
        + '<div data-ldoc-strip="1">'
        + _buildQuotedBlock(m, header)
        + '</div>'
      );
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
      compose.subject = (m.subject || '').match(/^fw:/i) ? m.subject : 'Fw: ' + (m.subject || '');
      compose.replyTo = null;
      compose.isForward = true;
      compose.isReplyAll = false;
      showCcBcc.value = false;
      toSuggestions.value = [];
      composeMode.value = true;
      const header = '--------- Forwarded message ---------\n'
        + 'From: ' + (m.from_name || '') + ' <' + (m.from_email || '') + '>\n'
        + 'Date: ' + formatFullDate(m.local_timestamp || m.received) + '\n'
        + 'Subject: ' + (m.subject || '');
      _seedComposeBody(_buildQuotedBlock(m, header));
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

    /** Remove the visible-but-non-sent portion of the compose body
     *  (the quoted original we inject for context on reply).  Anything
     *  marked ``data-ldoc-strip="1"`` is removed. */
    function _stripNonSendable(html) {
      const tmp = document.createElement('div');
      tmp.innerHTML = html || '';
      tmp.querySelectorAll('[data-ldoc-strip="1"]').forEach(n => n.remove());
      return tmp.innerHTML.trim();
    }

    async function sendCompose() {
      if (!compose.toList.length || !compose.subject) {
        toast('To and Subject are required', 'warning'); return;
      }
      sending.value = true;
      try {
        if (compose.replyTo && !compose.isForward) {
          // Reply: send only the user's typed text as ``comment`` —
          // Graph's ``/reply`` endpoint auto-quotes the original.
          const userOnly = _stripNonSendable(compose.body);
          await mailClient.request('reply', {
            message_id: compose.replyTo,
            body: userOnly,
            reply_all: !!compose.isReplyAll,
          });
        } else {
          // New message / forward — send the full HTML, including any
          // quoted original the user has preserved.
          await mailClient.request('send', {
            to: compose.toList, subject: compose.subject, body: compose.body,
            cc: compose.ccList.length ? compose.ccList : undefined,
            bcc: compose.bccList.length ? compose.bccList : undefined,
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

    /** ``YYYY-MM-DD`` in the user's local timezone.  Using
     *  ``toISOString().slice(0, 10)`` here is a bug: it converts the
     *  Date to UTC first, so in UTC+2 the midnight-local cell for Mon
     *  20 Apr carries the string "2026-04-19", and the "today"
     *  selection circle lands on the wrong mini-cal cell.  This
     *  formatter stays in local time so grid cells and selection
     *  values share one calendar day. */
    function _localDateStr(d) {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return y + '-' + m + '-' + day;
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
          const dateStr = _localDateStr(dt);
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
        const dateStr = _localDateStr(dt);
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
      const dateStr = _localDateStr(new Date(ds));
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
          date: _localDateStr(cur),
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
      selectedCalDate.value = _localDateStr(t);
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

    /** Jump to the day view for ``dateStr`` — triggered by clicking the
     *  "+N more" link in a month-view cell.  Matches what Outlook does:
     *  shows the full day so every event is readable without the cell
     *  clipping. */
    function openDayFromCell(dateStr) {
      goToDate(dateStr);
      calViewMode.value = 'day';
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

    function _calRangeKey() {
      // One cache bucket per viewed month.  ``loadEvents`` always fetches
      // the month before and two months after so week/day views in any
      // direction stay populated — the key reflects the *anchor* month.
      const y = calYear.value;
      const m = calMonth.value + 1;
      return y + '-' + (m < 10 ? '0' + m : m);
    }

    async function _paintEventsFromCache(rangeKey) {
      try {
        const cached = await cache.getCalendarEvents(rangeKey);
        if (cached && Array.isArray(cached.events) && cached.events.length) {
          events.value = cached.events;
        }
      } catch { /* cache miss — fall through to network */ }
    }

    async function loadEvents() {
      const rangeKey = _calRangeKey();
      // Cache-first paint — no spinner when we already have events to
      // show, the list is simply replaced in place when the fetch lands.
      await _paintEventsFromCache(rangeKey);
      loadingCal.value = events.value.length === 0;
      try {
        const rangeStart = new Date(calYear.value, calMonth.value - 1, 1);
        const rangeEnd = new Date(calYear.value, calMonth.value + 2, 6);
        const start = _localDateStr(rangeStart);
        const end = _localDateStr(rangeEnd);
        const data = await api('api/calendar/events?start=' + start + '&end=' + end + '&limit=200');
        const fresh = data.events || [];
        events.value = fresh;
        cache.setCalendarEvents(rangeKey, {
          events: fresh,
          fetched_at: Date.now(),
          range_start: start,
          range_end: end,
        }).catch(() => {});
      } catch (e) {
        // Keep cached view visible; only toast when we have nothing to show.
        if (!events.value.length) {
          toast('Failed to load events: ' + e.message, 'error');
        }
      } finally {
        loadingCal.value = false;
      }
    }

    // Auto-load calendar when switching to calendar view.  We always
    // call ``loadEvents`` so the cache-first paint runs (even when
    // events.value already has last month's data) and the network
    // refresh has a chance to catch any updates.
    watch(view, (v) => { if (v === 'calendar') loadEvents(); });
    // Also refresh when the user navigates months in the calendar.
    watch([calYear, calMonth], () => {
      if (view.value === 'calendar') loadEvents();
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

    // ── Mail-view extras watcher ──────────────────────────
    // Imperatively re-mount host-provided DOM fragments (PDF previews,
    // unfolded attachments, inline action bars) every time the user
    // opens a different mail.  We use imperative DOM instead of
    // ``v-html`` so hooks can return real ``HTMLElement`` instances
    // with event listeners, iframes, ShadowDOM, etc.
    watch(selectedMessage, (mail) => {
      nextTick(() => {
        const slot = mailExtrasSlot.value;
        if (!slot) return;
        slot.innerHTML = '';
        if (!mail) return;
        let fragments = [];
        try {
          fragments = hooks.renderMailViewExtras(mail, {
            selectedFolder: selectedFolder.value,
            profile: profile.value,
            dom: { container: slot },
          }) || [];
        } catch (e) {
          console.warn('[mail] renderMailViewExtras threw:', e);
          return;
        }
        for (const frag of fragments) {
          if (frag instanceof HTMLElement) {
            slot.appendChild(frag);
          } else if (typeof frag === 'string') {
            const wrap = document.createElement('div');
            wrap.innerHTML = frag;
            slot.appendChild(wrap);
          }
        }
      });
    });

    onMounted(async () => {
      // Boot order: init cache → paint from cache (so chrome shows real
      // data immediately on reload) → run auth probe in parallel.  The
      // auth probe only triggers a redirect on failure; until it returns
      // the user already sees the cached mail.
      try { await cache.init(); } catch (e) { console.warn('cache init failed:', e); }
      paintFromCache();
      checkAuth();
      document.addEventListener('click', onDocumentClick);
    });

    onUnmounted(() => {
      document.removeEventListener('click', onDocumentClick);
      mailClient.close();
      if (typeof _themeUnsub === 'function') { try { _themeUnsub(); } catch {} }
    });

    return {
      // core
      authenticated, profile, view, wsState: mailClient.connectionState, isOnline,
      // mail
      folders, folderTree, expandedFolders, toggleFolder,
      selectedFolder, currentFolderName, messages, filteredMessages,
      mailSearch, selectedMessage, loadingMail, loadingMore, messageTotal,
      selectFolder, openMessage, openAttachment, filterMessages,
      onMessageListScroll, loadMoreMessages,
      // layout
      folderSidebarWidth, messageListWidth, startSplitDrag,
      // host extension surface
      displayBody, externalImagesBlocked, showExternalImagesForCurrent,
      mailExtrasSlot, rowExt,
      // user-managed trust list
      trustCurrentSender, trustCurrentDomain, forgetTrust,
      currentSenderEmail, currentSenderDomain,
      userTrust: _userTrust,
      // mail-body theme toggle (independent of app theme)
      bodyDarkMode, toggleBodyDark,
      bodyTheme, effectiveBodyTheme, cycleBodyTheme, setBodyTheme,
      theme,
      // reactions
      currentReactions, toggleReaction, reactionEmoji,
      showReactionPicker,
      REACTION_PALETTE,
      reactionsByMsgId,
      // email map / photos
      emailMap, senderPhoto,
      // grouped messages
      groupedMessages,
      // compose
      composeMode, sending, compose, toSuggestions, showCcBcc,
      composeEditor, onComposeEditorInput, onComposeKeyDown,
      execFormat, insertLink, attachFile,
      startCompose, startReply, startForward,
      addRecipient, removeRecipient, pickSuggestion, onToInput,
      sendCompose, discardCompose,
      // calendar
      calYear, calMonth, calMonthName, miniCalYear, miniCalMonth, miniCalMonthName,
      events, loadingCal, selectedCalDate, calendarGrid, miniCalDays,
      calPrev, calNext, miniCalPrev, miniCalNext, goToToday, goToDate, loadEvents,
      openDayFromCell,
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
      soundEnabled, toggleSound, clearAvatarCache,
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
