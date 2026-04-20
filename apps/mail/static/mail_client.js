/**
 * MailClient — WebSocket abstraction for the mail app.
 *
 * Single WS connection per tab to /ws/mail. All mail operations go
 * through request(action, params) which returns a Promise resolved
 * by the server's correlation-ID-matched response.
 *
 * Usage:
 *   const client = new MailClient();
 *   client.connect();
 *   const folders = await client.request('folders');
 *   client.onPush(msg => console.log('server push:', msg));
 */
class MailClient {
  constructor() {
    /** @type {WebSocket|null} */
    this._ws = null;
    /** @type {Map<string, {resolve: Function, reject: Function, timer: number}>} */
    this._pending = new Map();
    /** @type {Array<{action: string, params: object, resolve: Function, reject: Function}>} */
    this._queue = [];
    /** @type {Array<Function>} */
    this._pushListeners = [];
    this._idCounter = 0;
    this._retryDelay = 1000;
    this._retryTimer = null;
    this._closed = false;

    // Vue-reactive connection state: 'connecting' | 'open' | 'reconnecting' | 'closed'
    this.connectionState = Vue.ref('connecting');
  }

  /** Open the WebSocket connection. */
  connect() {
    if (this._closed) return;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = proto + '//' + location.host + '/ws/mail';

    this.connectionState.value = this._ws ? 'reconnecting' : 'connecting';
    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      this.connectionState.value = 'open';
      this._retryDelay = 1000;
      this._flushQueue();
    };

    this._ws.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      const id = msg.id;
      if (id && this._pending.has(id)) {
        const entry = this._pending.get(id);
        this._pending.delete(id);
        clearTimeout(entry.timer);
        if (msg.error) {
          entry.reject(new Error(msg.error));
        } else {
          entry.resolve(msg);
        }
      } else {
        // Server-initiated push (no matching correlation ID)
        for (const fn of this._pushListeners) {
          try { fn(msg); } catch (e) { console.error('push listener error:', e); }
        }
      }
    };

    this._ws.onclose = (event) => {
      this._ws = null;
      // Reject all pending requests
      for (const [id, entry] of this._pending) {
        clearTimeout(entry.timer);
        entry.reject(new Error('WebSocket closed'));
      }
      this._pending.clear();

      if (this._closed) {
        this.connectionState.value = 'closed';
        return;
      }

      // 4401 = not authenticated — don't reconnect, reload page
      if (event.code === 4401) {
        this.connectionState.value = 'closed';
        if (!sessionStorage.getItem('mail_reloaded_on_401')) {
          sessionStorage.setItem('mail_reloaded_on_401', '1');
          location.reload();
        }
        return;
      }

      this.connectionState.value = 'reconnecting';
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      // onclose will fire after onerror — reconnection handled there
    };
  }

  /**
   * Send a mail action and wait for the response.
   * @param {string} action — e.g. 'folders', 'messages', 'send', 'delete'
   * @param {object} [params={}] — action-specific parameters
   * @returns {Promise<object>} — server response (without id/action fields)
   */
  request(action, params = {}) {
    return new Promise((resolve, reject) => {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._send(action, params, resolve, reject);
      } else {
        // Queue while disconnected (cap 50)
        if (this._queue.length >= 50) {
          reject(new Error('Request queue full'));
          return;
        }
        this._queue.push({ action, params, resolve, reject });
      }
    });
  }

  /**
   * Register a listener for server-initiated push messages.
   * @param {Function} callback — receives the parsed message object
   * @returns {Function} — call to unsubscribe
   */
  onPush(callback) {
    this._pushListeners.push(callback);
    return () => {
      this._pushListeners = this._pushListeners.filter(fn => fn !== callback);
    };
  }

  /** Permanently close the connection (no reconnect). */
  close() {
    this._closed = true;
    if (this._retryTimer) clearTimeout(this._retryTimer);
    if (this._ws) this._ws.close();
  }

  // ── internal ──────────────────────────────────────────────────

  _send(action, params, resolve, reject) {
    const id = 'r' + (++this._idCounter);
    const timer = setTimeout(() => {
      this._pending.delete(id);
      reject(new Error('Request timeout: ' + action));
    }, 30000);

    this._pending.set(id, { resolve, reject, timer });
    this._ws.send(JSON.stringify({ action, id, ...params }));
  }

  _flushQueue() {
    const queued = this._queue.splice(0);
    for (const { action, params, resolve, reject } of queued) {
      this._send(action, params, resolve, reject);
    }
  }

  _scheduleReconnect() {
    if (this._retryTimer) clearTimeout(this._retryTimer);
    this._retryTimer = setTimeout(() => {
      this._retryTimer = null;
      this.connect();
    }, this._retryDelay);
    // Exponential backoff: 1s, 2s, 4s, 8s, ... cap 30s
    this._retryDelay = Math.min(this._retryDelay * 2, 30000);
  }
}
