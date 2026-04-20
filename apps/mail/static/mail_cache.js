/**
 * MailCache — extensible IndexedDB-backed cache for the mail app.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │  DB ``mail_cache`` — version 2                               │
 *   │                                                              │
 *   │    folders           key="all"             FolderInfo[]      │
 *   │    messages_index    key=[folder_id, id]   row metadata      │
 *   │    message_bodies    key=message_id        body+meta+size    │
 *   │    attachment_blobs  key=[message_id,name] Blob+size+mime    │
 *   │    metadata          arbitrary k/v (sigs, total_bytes)       │
 *   │                                                              │
 *   │  All "binary-ish" stores (message_bodies, attachment_blobs)  │
 *   │  are tracked under a unified ``sizeAccountingStores`` list   │
 *   │  — LRU eviction walks every such store when the total size   │
 *   │  exceeds the cap.                                            │
 *   └──────────────────────────────────────────────────────────────┘
 *
 * Extending the cache
 * -------------------
 *
 * New stores are declared by calling ``MailCache.registerStore`` before
 * ``init()``.  Registrations at module scope (below) cover the built-in
 * layout; hosts can call the same API from their own bootstrapping
 * code if they need additional stores (e.g. an OCR'd-PDF preview
 * cache):
 *
 *   MailCache.registerStore({
 *     name: 'pdf_previews',
 *     keyPath: 'message_id',
 *     indexes: [{ name: 'last_access', keyPath: 'last_access' }],
 *     sizeAccounted: true,
 *   });
 *
 * Registering a new store bumps the schema version automatically, so
 * existing databases are upgraded in-place without nuking cached data.
 *
 * Quota & eviction
 * ----------------
 *
 * The cache claims up to ``navigator.storage.estimate().quota * 0.5``
 * or a hard 200 MB ceiling — whichever is lower (Safari on iOS enforces
 * ~50 MB regardless).  Size is tracked in ``metadata:total_bytes`` and
 * incremented / decremented by every sized write.  LRU uses the
 * ``last_access`` index across all size-accounted stores.
 *
 * No disk I/O escapes the browser; evicted entries are gone.
 */

class MailCache {
  // ── static registry ──────────────────────────────────────────
  // Stores registered here are created at ``init()`` time.  Mutating
  // the registry after init() has no effect; call ``close()`` and
  // re-``init()`` (or just reload the page) to apply changes.
  static _storeRegistry = new Map();

  /** Declare a new store.  Idempotent — re-registering the same name
   *  updates the entry.  ``def.sizeAccounted === true`` opts the store
   *  into the unified LRU + total_bytes accounting. */
  static registerStore(def) {
    if (!def || !def.name) throw new Error('MailCache.registerStore: name required');
    MailCache._storeRegistry.set(def.name, {
      name: def.name,
      keyPath: def.keyPath || null,
      indexes: def.indexes || [],
      sizeAccounted: !!def.sizeAccounted,
    });
  }

  constructor(dbName = 'mail_cache') {
    this._dbName = dbName;
    /** @type {IDBDatabase|null} */
    this._db = null;
    this._maxBytes = 200 * 1024 * 1024;  // 200 MB ceiling
    // Captured at init() from the registry so later registrations
    // don't silently change which stores this instance thinks exist.
    this._stores = null;
  }

  // ── lifecycle ─────────────────────────────────────────────────

  /** Open (or upgrade) the database.  Call once at startup. */
  async init() {
    if (this._db) return;
    // Freeze the store list for this instance.
    this._stores = Array.from(MailCache._storeRegistry.values());
    // Schema version = count of stores — any addition bumps it.
    const version = Math.max(1, this._stores.length);
    if (navigator.storage && navigator.storage.estimate) {
      try {
        const est = await navigator.storage.estimate();
        if (est.quota) {
          this._maxBytes = Math.min(this._maxBytes, Math.floor(est.quota * 0.5));
        }
      } catch { /* ignore — keep default */ }
    }
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(this._dbName, version);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        for (const def of this._stores) {
          let store;
          if (db.objectStoreNames.contains(def.name)) {
            store = req.transaction.objectStore(def.name);
          } else {
            const opts = def.keyPath ? { keyPath: def.keyPath } : {};
            store = db.createObjectStore(def.name, opts);
          }
          const existingIdx = new Set(Array.from(store.indexNames || []));
          for (const idx of (def.indexes || [])) {
            if (existingIdx.has(idx.name)) continue;
            store.createIndex(idx.name, idx.keyPath, { unique: !!idx.unique });
          }
        }
      };
      req.onsuccess = (e) => { this._db = e.target.result; resolve(); };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  close() {
    if (this._db) { this._db.close(); this._db = null; }
  }

  // ── folders ───────────────────────────────────────────────────

  async getFolders()        { return this._get('folders', 'all'); }
  async setFolders(list)    { return this._put('folders', list, 'all'); }

  // ── messages index ────────────────────────────────────────────

  async getMessagesIndex(folderId) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction('messages_index', 'readonly');
      const idx = tx.objectStore('messages_index').index('folder_id');
      const req = idx.getAll(folderId);
      req.onsuccess = () => {
        const rows = req.result || [];
        rows.sort((a, b) => (b.received || '').localeCompare(a.received || ''));
        resolve(rows);
      };
      req.onerror = (e) => reject(e.target.error);
    });
  }

  async mergeMessagesIndex(folderId, rows) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction('messages_index', 'readwrite');
      const store = tx.objectStore('messages_index');
      for (const row of rows) store.put({ ...row, folder_id: folderId });
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e.target.error);
    });
  }

  async getSinceSig(folderId)       { return this._get('metadata', 'sig:' + folderId); }
  async setSinceSig(folderId, sig)  { return this._put('metadata', sig, 'sig:' + folderId); }

  // ── message bodies ────────────────────────────────────────────

  async getBody(messageId) {
    const row = await this._get('message_bodies', messageId);
    if (!row) return null;
    row.last_access = Date.now();
    await this._put('message_bodies', row);
    return row.data;
  }

  async setBody(messageId, data) {
    const size = _estimateSize(data);
    const row = { message_id: messageId, data, last_access: Date.now(), size };
    await this._put('message_bodies', row);
    await this._evictIfNeeded(size);
  }

  async evictBody(messageId) {
    return this._evictRow('message_bodies', messageId);
  }

  // ── attachment blobs ──────────────────────────────────────────

  /** Return ``{ blob, content_type, size }`` or ``null``.  Touches
   *  ``last_access`` so the blob survives LRU eviction after a read. */
  async getAttachment(messageId, name) {
    const row = await this._getByKey('attachment_blobs', [messageId, name]);
    if (!row) return null;
    row.last_access = Date.now();
    await this._put('attachment_blobs', row);
    return { blob: row.blob, content_type: row.content_type, size: row.size || 0 };
  }

  async setAttachment(messageId, name, blob, contentType) {
    const size = blob && blob.size ? blob.size : 0;
    const row = {
      message_id: messageId,
      name,
      blob,
      content_type: contentType || (blob && blob.type) || 'application/octet-stream',
      size,
      last_access: Date.now(),
    };
    await this._put('attachment_blobs', row);
    await this._evictIfNeeded(size);
  }

  async evictAttachment(messageId, name) {
    return this._evictRow('attachment_blobs', [messageId, name]);
  }

  /** Evict every attachment bound to a message — called on
   *  ``mail.scan_done`` and when a mail is moved/deleted. */
  async evictAttachmentsFor(messageId) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction(['attachment_blobs', 'metadata'], 'readwrite');
      const store = tx.objectStore('attachment_blobs');
      const idx = store.index('message_id');
      const req = idx.openCursor(IDBKeyRange.only(messageId));
      let freed = 0;
      req.onsuccess = (e) => {
        const c = e.target.result;
        if (!c) {
          if (freed) {
            const meta = tx.objectStore('metadata');
            const tr = meta.get('total_bytes');
            tr.onsuccess = () => meta.put(Math.max(0, (tr.result || 0) - freed), 'total_bytes');
          }
          return;
        }
        freed += (c.value.size || 0);
        c.delete();
        c.continue();
      };
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e.target.error);
    });
  }

  // ── diagnostics ───────────────────────────────────────────────

  /** Return ``{ totalBytes, maxBytes }`` for the settings panel. */
  async usage() {
    const total = (await this._get('metadata', 'total_bytes')) || 0;
    return { totalBytes: total, maxBytes: this._maxBytes };
  }

  // ── internal ──────────────────────────────────────────────────

  async _evictRow(storeName, key) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction([storeName, 'metadata'], 'readwrite');
      const store = tx.objectStore(storeName);
      const getReq = store.get(key);
      getReq.onsuccess = () => {
        const row = getReq.result;
        if (row) {
          store.delete(key);
          const meta = tx.objectStore('metadata');
          const tr = meta.get('total_bytes');
          tr.onsuccess = () => {
            const cur = tr.result || 0;
            meta.put(Math.max(0, cur - (row.size || 0)), 'total_bytes');
          };
        }
      };
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e.target.error);
    });
  }

  async _evictIfNeeded(addedSize) {
    // Update the running total first, in its own tiny transaction.
    // IDB auto-commits transactions whose request queue drains, so we
    // *cannot* hold one open across the multi-store cursor walk that
    // follows — each store evicts in its own short-lived transaction.
    const prev = (await this._get('metadata', 'total_bytes')) || 0;
    const total = prev + addedSize;
    await this._put('metadata', total, 'total_bytes');
    if (total <= this._maxBytes) return;

    // Priority: evict attachment blobs first (large, cheap to re-fetch
    // from the server), then message bodies (smaller, more expensive
    // to re-fetch — they ride the WS).  Other size-accounted stores
    // registered by hosts are evicted last in registration order.
    const accounted = this._stores.filter(s => s.sizeAccounted).map(s => s.name);
    const priority = ['attachment_blobs', 'message_bodies'];
    const ordered = [
      ...priority.filter(n => accounted.includes(n)),
      ...accounted.filter(n => !priority.includes(n)),
    ];
    let overBy = total - this._maxBytes;
    for (const name of ordered) {
      if (overBy <= 0) break;
      const freed = await this._evictOldestFromStore(name, overBy);
      overBy -= freed;
    }
  }

  /** Walk the ``last_access`` index of ``storeName`` from oldest to
   *  newest, deleting rows until ``targetBytes`` have been freed (or
   *  the store is empty).  Returns bytes actually freed so the caller
   *  can decrement the running total in a separate transaction. */
  _evictOldestFromStore(storeName, targetBytes) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction(storeName, 'readwrite');
      const idx = tx.objectStore(storeName).index('last_access');
      let freed = 0;
      idx.openCursor().onsuccess = (e) => {
        const c = e.target.result;
        if (!c || freed >= targetBytes) return;
        freed += c.value.size || 0;
        c.delete();
        c.continue();
      };
      tx.oncomplete = async () => {
        if (freed > 0) {
          try {
            const cur = (await this._get('metadata', 'total_bytes')) || 0;
            await this._put('metadata', Math.max(0, cur - freed), 'total_bytes');
          } catch { /* best-effort accounting */ }
        }
        resolve(freed);
      };
      tx.onerror = (e) => reject(e.target.error);
    });
  }

  _get(storeName, key) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction(storeName, 'readonly');
      const req = tx.objectStore(storeName).get(key);
      req.onsuccess = () => resolve(req.result ?? null);
      req.onerror = (e) => reject(e.target.error);
    });
  }

  _getByKey(storeName, key) { return this._get(storeName, key); }

  _put(storeName, value, key) {
    return new Promise((resolve, reject) => {
      const tx = this._db.transaction(storeName, 'readwrite');
      const store = tx.objectStore(storeName);
      key !== undefined ? store.put(value, key) : store.put(value);
      tx.oncomplete = () => resolve();
      tx.onerror = (e) => reject(e.target.error);
    });
  }
}

/** Rough byte-size estimate for a JS value (used for eviction accounting). */
function _estimateSize(obj) {
  try {
    const s = JSON.stringify(obj);
    return s ? s.length * 2 : 0;
  } catch {
    return 0;
  }
}

// ── Built-in store layout ──────────────────────────────────────
// Registered at module scope so it's available before any client
// extension points (plugins may call ``MailCache.registerStore(...)``
// after this file loads but before ``cache.init()``).

MailCache.registerStore({ name: 'folders' });
MailCache.registerStore({
  name: 'messages_index',
  keyPath: ['folder_id', 'id'],
  indexes: [
    { name: 'folder_id', keyPath: 'folder_id' },
    { name: 'received',  keyPath: 'received'  },
  ],
});
MailCache.registerStore({
  name: 'message_bodies',
  keyPath: 'message_id',
  indexes: [{ name: 'last_access', keyPath: 'last_access' }],
  sizeAccounted: true,
});
MailCache.registerStore({
  name: 'attachment_blobs',
  keyPath: ['message_id', 'name'],
  indexes: [
    { name: 'message_id', keyPath: 'message_id' },
    { name: 'last_access', keyPath: 'last_access' },
  ],
  sizeAccounted: true,
});
MailCache.registerStore({
  // key = month range key ("YYYY-MM"); value = { events, fetched_at, range_start, range_end }.
  // Not size-accounted — payloads are small and eviction-on-quota is
  // better handled by MailCache's ``attachment_blobs`` + ``message_bodies``.
  name: 'calendar_events',
});
MailCache.registerStore({ name: 'metadata' });

// Convenience methods — thin wrappers so callers don't touch store
// names directly (safer for future refactors).
MailCache.prototype.getCalendarEvents = function (rangeKey) {
  return this._get('calendar_events', rangeKey);
};
MailCache.prototype.setCalendarEvents = function (rangeKey, payload) {
  return this._put('calendar_events', payload, rangeKey);
};

window.MailCache = MailCache;
