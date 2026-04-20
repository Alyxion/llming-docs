/**
 * MailHooks — host-provided extension surface for the mail app.
 *
 * The mail frontend is packaged inside llming-docs and knows nothing about
 * the host (Lechler shim, standalone demo, future consumers).  Hosts that
 * want to customize behaviour — theme, trusted senders, per-mail render
 * augmentation, cache TTLs, avatar lifetimes — do so by placing an object
 * on ``window.__MAIL_CONFIG__.hooks`` before ``app.js`` boots.
 *
 * Every hook is optional; ``resolveMailHooks()`` fills in safe defaults,
 * so app code never needs to check existence.  Hosts can override a subset.
 *
 * Contract (all optional):
 *
 *   {
 *     // Cache lifetimes
 *     avatarMaxAgeDays: number,           // default 14
 *     bodyMaxAgeDays: number,             // default 30
 *
 *     // Theme — light or dark CSS scope
 *     theme: 'light' | 'dark',            // default 'light'
 *     subscribeTheme: (cb) => unsubscribe,
 *
 *     // External images — default deny.  Host returns true to auto-load
 *     // remote images without showing the "Download external images" banner.
 *     isTrustedSender: (email, domain) => boolean,
 *
 *     // Index rows — host returns an object merged into the row view.
 *     // Allowed keys: ``classes`` (array, appended to the row),
 *     // ``indicators`` (array of { icon, title, color? } appended to the
 *     // right-hand indicator column).
 *     renderIndexRow: (mail, context) => ({ classes?, indicators? }),
 *
 *     // Mail view extras — host returns a list of HTMLElement (or strings
 *     // containing sanitized HTML) injected below the body.  Use for
 *     // unfolding PDFs, showing extracted tables, custom action bars, …
 *     renderMailViewExtras: (mail, context) => HTMLElement[] | string[],
 *
 *     // Attachment prefetch — host decides whether the full attachment
 *     // blobs for a newly-arrived message should be downloaded silently
 *     // in the background (before the user opens the mail).  Host
 *     // returns one of:
 *     //   false                     — skip (default — save bandwidth on phones)
 *     //   true                      — fetch every non-embedded attachment
 *     //   ["invoice.pdf", ...]      — fetch these attachment names only
 *     // The mail frontend invokes this on ``mail.new_mail`` push events
 *     // and ``openMessage`` cache misses.  Embedded images are always
 *     // inlined with the body; this hook only governs real attachments.
 *     shouldPrefetchAttachments: (mail, context) => boolean | string[],
 *   }
 *
 * The ``context`` argument passed to render hooks carries:
 *   { selectedFolder, profile, dom: { container, bodyFrame } }
 *
 * Hosts should never block the render path — all hooks must return
 * synchronously.  Async fetching (e.g. unfolding a PDF) should be kicked
 * off inside the hook and the placeholder element returned immediately.
 */

(function () {
  const DEFAULTS = {
    avatarMaxAgeDays: 14,
    bodyMaxAgeDays: 30,
    theme: 'light',
    subscribeTheme: function (_cb) { return function () {}; },
    isTrustedSender: function (_email, _domain) { return false; },
    renderIndexRow: function (_mail, _ctx) { return {}; },
    renderMailViewExtras: function (_mail, _ctx) { return []; },
    shouldPrefetchAttachments: function (_mail, _ctx) { return false; },
  };

  function resolveMailHooks() {
    const raw = (window.__MAIL_CONFIG__ && window.__MAIL_CONFIG__.hooks) || {};
    const out = {};
    for (const key in DEFAULTS) {
      out[key] = Object.prototype.hasOwnProperty.call(raw, key) ? raw[key] : DEFAULTS[key];
    }
    return out;
  }

  window.resolveMailHooks = resolveMailHooks;
  window.MAIL_HOOK_DEFAULTS = DEFAULTS;
})();
