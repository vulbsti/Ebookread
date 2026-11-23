/**
 * Ebookread reader bridge: a thin layer around foliate-js's <foliate-view>.
 *
 * Page -> Python messages (JSON strings on the "ebookread" handler), each tagged with the
 * token of the book it belongs to:
 *   page_ready, ready, relocate, history, footnote, link_external,
 *   search_progress, search_results, search_done, toggle_chrome, escape, error
 * Python -> page: window.Ebookread.<fn>(...) — see the export at the bottom.
 */

import { FootnoteHandler } from "./foliate-js/footnotes.js";

const host = document.getElementById("foliate-host");
const errorBox = document.getElementById("error");
const notePopover = document.getElementById("footnote");
const noteBody = document.getElementById("footnote-body");
const noteGoto = document.getElementById("footnote-goto");
const noteClose = document.getElementById("footnote-close");

let view = null;
let token = null;
let settings = null;
let searchGeneration = 0;
let sectionPage = null; // { current, total } inside the current chapter
let noteHref = null;
let currentFilename = "";

function post(type, payload = {}) {
  try {
    window.webkit?.messageHandlers?.ebookread?.postMessage(JSON.stringify({ type, token, ...payload }));
  } catch (err) {
    console.error("bridge post failed", err);
  }
}

// ---------------------------------------------------------------- styling

const SPACING = { none: "0", small: "0.6em", large: "1.2em" };

function bookCSS(s) {
  const v = s.css_vars;
  const mine = !s.publisher;
  return `
    @namespace epub "http://www.idpf.org/2007/ops";
    html, body {
      background: ${v["--er-bg"]} !important;
      color: ${v["--er-fg"]} !important;
    }
    /* Size stays the reader's choice even with the book's own formatting. */
    html { font-size: ${v["--er-font-size"]} !important; }
    a:link, a:visited { color: ${v["--er-accent"]} !important; }
    ${s.is_dark ? `
    /* Dark themes: text the book coloured black would be invisible. */
    body :is(p, span, div, li, dd, dt, h1, h2, h3, h4, h5, h6, em, i, b, strong, small, cite, q,
             blockquote, td, th, caption, figcaption, section, article, header, footer, sup, sub) {
      color: inherit !important;
      border-color: ${v["--er-muted"]};
    }
    body :is(table, tr, td, th, div, section, aside, blockquote, pre, code) {
      background-color: transparent !important;
    }` : ""}
    ${mine ? `
    body, body :is(p, li, dd, dt, blockquote, div, span, td) {
      font-family: ${v["--er-font-family"]} !important;
    }
    p, li, blockquote, dd {
      line-height: ${v["--er-line-height"]} !important;
      text-align: ${v["--er-text-align"]} !important;
      -webkit-hyphens: ${v["--er-hyphens"]} !important;
      hyphens: ${v["--er-hyphens"]} !important;
      widows: 2;
      orphans: 2;
    }
    [align="left"] { text-align: left !important; }
    [align="right"] { text-align: right !important; }
    [align="center"] { text-align: center !important; }
    ${SPACING[s.paragraph_spacing] != null
      ? `p { margin-top: 0 !important; margin-bottom: ${SPACING[s.paragraph_spacing]} !important; }`
      : ""}` : ""}
    pre { white-space: pre-wrap !important; }
    img, svg { max-width: 100%; }
    aside[epub|type~="endnote"], aside[epub|type~="footnote"],
    aside[epub|type~="note"], aside[epub|type~="rearnote"] { display: none; }
  `;
}

function applyPageVars(s) {
  const root = document.documentElement;
  for (const [k, v] of Object.entries(s.css_vars || {})) root.style.setProperty(k, v);
  const isPdf = view?.book && /\.pdf$/i.test(currentFilename);
  host.style.filter = (isPdf && s.invert_pdf ? s.filter_inverted : s.filter) || "none";
}

function applyRendererAttrs(s) {
  const r = view?.renderer;
  if (!r) return;
  view.setAttribute("autohide-cursor", "");
  if (r.localName === "foliate-fxl") {
    // PDFs, comics and fixed-layout books: zoom instead of reflowing text.
    const z = s.fxl_zoom;
    r.setAttribute("zoom", z === "fit-page" || z === "fit-width" ? z : String(Number(z) / 100));
    return;
  }
  r.setAttribute("flow", s.layout_mode === "scrolled" ? "scrolled" : "paginated");
  r.setAttribute("max-inline-size", `${s.max_width}px`);
  // `margin` is the space above and below the text; the window's toolbars float there.
  r.setAttribute("margin", `${Math.round(s.chrome_margin ?? 48)}px`);
  r.setAttribute("gap", `${s.margin_pct ?? 6}%`);
  r.setAttribute("max-column-count", s.columns === "single" ? "1" : "2");
  // Without this foliate jumps between pages and adds a fixed 100 ms pause per turn.
  r.setAttribute("animated", "");
  r.setStyles?.(bookCSS(s));
}

function applySettings(s) {
  settings = s;
  applyPageVars(s);
  applyRendererAttrs(s);
}

// ---------------------------------------------------------------- footnotes

const footnotes = new FootnoteHandler();

footnotes.addEventListener("before-render", ({ detail: { view: mini } }) => {
  closeFootnote();
  // The renderer only lays out once it is in the document, so attach it now; the
  // popover stays invisible until the note has rendered.
  noteBody.replaceChildren(mini);
  notePopover.classList.add("loading");
  notePopover.hidden = false;
});

footnotes.addEventListener("render", ({ detail }) => {
  // Layout attributes only once the note's document exists (earlier, foliate lays out null).
  const r = detail.view.renderer;
  r.setAttribute("flow", "scrolled");
  r.setAttribute("margin", "0px");
  r.setAttribute("gap", "5%");
  if (settings) r.setStyles?.(bookCSS(settings));
  noteHref = detail.href;
  // A note that only exists hidden inside the text has nowhere to "go to".
  noteGoto.hidden = Boolean(detail.hidden);
  // Fit the popover to the note: short notes get a small box, long ones scroll.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const doc = r.getContents?.()[0]?.doc;
    const h = doc ? Math.ceil(doc.documentElement.scrollHeight) : 0;
    const cap = Math.round(window.innerHeight * 0.38);
    noteBody.style.height = h > 0 ? `${Math.max(48, Math.min(h + 8, cap))}px` : "";
    notePopover.classList.remove("loading");
    post("footnote", { href: detail.href, note_type: detail.type ?? null });
  }));
});

function closeFootnote() {
  if (notePopover.hidden) return false;
  notePopover.hidden = true;
  noteBody.querySelector("foliate-view")?.close?.();
  noteBody.replaceChildren();
  noteBody.style.height = "";
  noteHref = null;
  return true;
}

noteClose.addEventListener("click", closeFootnote);
noteGoto.addEventListener("click", () => {
  const href = noteHref;
  closeFootnote();
  if (href) view?.goTo(href);
});

// ---------------------------------------------------------------- input

const turn = (dir) => {
  closeFootnote();
  return dir > 0 ? view?.next() : view?.prev();
};

// A turn the reader made from the page itself (keys, wheel, click): Python may hide the
// toolbars. Turns from the footer buttons don't, since the pointer is on the toolbar.
const userTurn = (dir) => {
  post("user_turn");
  return turn(dir);
};

// Pointer near the top or bottom edge brings the toolbars back.
let atEdge = false;
function onPointerMove(ev) {
  const doc = ev.target?.ownerDocument ?? document;
  const frame = doc.defaultView?.frameElement;
  const y = (frame ? frame.getBoundingClientRect().top : 0) + ev.clientY;
  const edge = y < 64 || y > window.innerHeight - 88;
  if (edge && !atEdge) post("edge");
  atEdge = edge;
}

function onKey(ev) {
  if (ev.defaultPrevented || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  const k = ev.key;
  if (k === "ArrowRight" || k === "PageDown" || (k === " " && !ev.shiftKey)) {
    ev.preventDefault();
    userTurn(1);
  } else if (k === "ArrowLeft" || k === "PageUp" || (k === " " && ev.shiftKey)) {
    ev.preventDefault();
    userTurn(-1);
  } else if (k === "Home" || k === "End") {
    ev.preventDefault();
    closeFootnote();
    k === "Home" ? view?.renderer?.prevSection?.() : view?.renderer?.nextSection?.();
  } else if (k === "Escape") {
    // Handled here, so GTK does not also treat it as "leave the reader".
    ev.preventDefault();
    if (!closeFootnote()) post("escape");
  }
}

// Touchpad swipes and mouse wheels turn pages in paginated mode. One turn per
// gesture: accumulate the delta, turn once past a threshold, then wait for calm.
let wheelSum = 0;
let wheelLockUntil = 0;
let wheelIdle = null;
function onWheel(ev) {
  if (!view || settings?.layout_mode === "scrolled" || ev.ctrlKey) return;
  ev.preventDefault();
  const now = performance.now();
  clearTimeout(wheelIdle);
  wheelIdle = setTimeout(() => { wheelSum = 0; }, 160);
  if (now < wheelLockUntil) return;
  const d = Math.abs(ev.deltaX) > Math.abs(ev.deltaY) ? ev.deltaX : ev.deltaY;
  wheelSum += ev.deltaMode === 1 ? d * 30 : d;
  if (Math.abs(wheelSum) >= 60) {
    userTurn(Math.sign(wheelSum));
    wheelSum = 0;
    wheelLockUntil = now + 350;
  }
}

// Clicks: outer quarters turn pages, the middle shows/hides the window chrome.
function onDocClick(ev) {
  if (ev.defaultPrevented || ev.button !== 0) return;
  const doc = ev.target?.ownerDocument;
  if (ev.target?.closest?.("a[href]")) return;
  if (doc?.getSelection && String(doc.getSelection()).length > 0) return;
  if (closeFootnote()) return;
  const frame = doc?.defaultView?.frameElement;
  const left = (frame ? frame.getBoundingClientRect().left : 0) + ev.clientX;
  const x = left / Math.max(1, window.innerWidth);
  if (settings?.layout_mode !== "scrolled" && x < 0.25) userTurn(-1);
  else if (settings?.layout_mode !== "scrolled" && x > 0.75) userTurn(1);
  else post("toggle_chrome");
}

document.addEventListener("keydown", onKey);
document.addEventListener("wheel", onWheel, { passive: false });
document.addEventListener("mousemove", onPointerMove);

// ---------------------------------------------------------------- search

async function search(query) {
  const gen = ++searchGeneration;
  view?.clearSearch();
  const q = String(query || "").trim();
  if (!view || !q) {
    post("search_done", { query: q, generation: gen, count: 0 });
    return;
  }
  let count = 0;
  try {
    for await (const result of view.search({ query: q })) {
      if (gen !== searchGeneration) return; // superseded by a newer search
      if (result === "done") break;
      if (result.progress != null) {
        post("search_progress", { generation: gen, progress: result.progress });
      } else if (result.subitems) {
        const items = result.subitems.map(({ cfi, excerpt }) => ({
          cfi,
          pre: excerpt?.pre ?? "",
          match: excerpt?.match ?? "",
          post: excerpt?.post ?? "",
        }));
        count += items.length;
        post("search_results", { generation: gen, label: result.label ?? "", items });
      }
    }
  } catch (err) {
    console.error(err);
  }
  if (gen === searchGeneration) post("search_done", { query: q, generation: gen, count });
}

function clearSearch() {
  searchGeneration++;
  view?.clearSearch();
}

// ---------------------------------------------------------------- book

function tocTree(items, fractions) {
  return (items || []).map((t) => {
    let fraction = null;
    try {
      const idx = t.href != null ? view.resolveNavigation(t.href)?.index : null;
      if (idx != null && fractions[idx] != null) fraction = Number(fractions[idx].toFixed(5));
    } catch { /* unresolvable entry */ }
    return {
      label: String(t.label ?? "").trim() || "Untitled",
      href: t.href ?? null,
      fraction,
      subitems: tocTree(t.subitems, fractions),
    };
  });
}

// init() resolves before layout is final: fonts load, foliate re-lays out and re-anchors,
// which can move the view by a page. Wait until relocates go quiet (bounded), so the
// first reported position is the real one and the reader never sees the jump.
function settle(v, quietMs = 250, maxMs = 2000) {
  return new Promise((resolve) => {
    let quiet;
    const done = () => {
      clearTimeout(quiet);
      clearTimeout(cap);
      v.removeEventListener("relocate", bump);
      resolve();
    };
    const bump = () => {
      clearTimeout(quiet);
      quiet = setTimeout(done, quietMs);
    };
    const cap = setTimeout(done, maxMs);
    v.addEventListener("relocate", bump);
    bump();
  });
}

function visibleText(range) {
  if (!range) return "";
  try {
    const frag = range.cloneContents();
    for (const el of frag.querySelectorAll?.("script, style") ?? []) el.remove();
    return (frag.textContent || "").replace(/\s+/g, " ").trim();
  } catch {
    return "";
  }
}

function textOf(x) {
  if (!x) return "";
  if (typeof x === "string") return x;
  if (Array.isArray(x)) return x.map(textOf).filter(Boolean).join(", ");
  if (typeof x === "object") return textOf(x.name ?? Object.values(x)[0]);
  return String(x);
}

function showError(message) {
  host.hidden = true;
  errorBox.hidden = false;
  errorBox.querySelector("p").textContent = message;
  post("error", { message });
}

// The book's cover as a small JPEG (base64), for books the importer couldn't get one for.
async function captureCover(book) {
  const blob = await book.getCover?.();
  if (!blob) return null;
  const bitmap = await createImageBitmap(blob);
  const scale = Math.min(1, 360 / bitmap.width, 540 / bitmap.height);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  return canvas.toDataURL("image/jpeg", 0.88).split(",", 2)[1] ?? null;
}

async function open({ token: t, filename = "book", lastLocation = null, settings: s, wantCover = false }) {
  token = t;
  settings = s;
  currentFilename = filename;
  applyPageVars(s);
  try {
    await import("./foliate-js/view.js");
    const resp = await fetch("book/raw");
    if (!resp.ok) throw new Error(`could not read the book file (${resp.status})`);
    const blob = await resp.blob();
    const file = new File([blob], filename, { type: blob.type });

    view = document.createElement("foliate-view");
    host.replaceChildren(view);

    view.addEventListener("load", ({ detail: { doc } }) => {
      doc.addEventListener("keydown", onKey);
      doc.addEventListener("wheel", onWheel, { passive: false });
      doc.addEventListener("click", onDocClick);
      doc.addEventListener("mousemove", onPointerMove);
    });

    // foliate fires relocates while it is still moving to the saved spot (e.g. the start
    // of the section first). Reporting those would overwrite the saved position, so the
    // page stays quiet until init() has settled, then reports the real location once.
    let settled = false;
    const report = (d) => {
      if (!settled || !d) return;
      const text = visibleText(d.range);
      post("relocate", {
        cfi: d.cfi ?? null,
        fraction: Number((d.fraction ?? 0).toFixed(5)),
        section: d.section ?? null,
        section_page: sectionPage,
        time: d.time ?? null,
        toc_item: d.tocItem ? { label: String(d.tocItem.label ?? "").trim(), href: d.tocItem.href ?? null } : null,
        page_item: d.pageItem ? { label: String(d.pageItem.label ?? "") } : null,
        excerpt: text.slice(0, 200),
      });
    };
    view.addEventListener("relocate", ({ detail }) => report(detail));
    view.addEventListener("external-link", (ev) => {
      ev.preventDefault();
      post("link_external", { url: ev.detail.href_ });
    });
    view.addEventListener("link", (ev) => {
      closeFootnote();
      footnotes.handle(view.book, ev)?.catch((err) => {
        console.warn("footnote failed, following link", err);
        view.goTo(ev.detail.href);
      });
    });
    view.history.addEventListener("index-change", () => {
      post("history", { can_back: view.history.canGoBack, can_forward: view.history.canGoForward });
    });

    await view.open(file);
    view.renderer.addEventListener("relocate", ({ detail: { fraction, size } }) => {
      // Page n of m inside the current chapter (paginated); null when unknown.
      if (size > 0 && size < 1 && Number.isFinite(fraction)) {
        const total = Math.max(1, Math.round(1 / size));
        sectionPage = { current: Math.min(total, Math.round(fraction / size) + 1), total };
      } else sectionPage = null;
    });
    applySettings(s); // before init, so the first page is already themed
    await view.init({ lastLocation, showTextStart: !lastLocation });
    await settle(view);
    host.classList.add("shown");

    const meta = view.book.metadata || {};
    const fractions = view.getSectionFractions();
    post("ready", {
      toc: tocTree(view.book.toc, fractions),
      section_count: view.book.sections?.length ?? 0,
      section_fractions: fractions.map((f) => Number(f.toFixed(5))),
      metadata: { title: textOf(meta.title), author: textOf(meta.author), language: textOf(meta.language) },
    });
    settled = true;
    report(view.lastLocation);
    if (wantCover) {
      captureCover(view.book)
        .then((data) => data && post("cover", { data }))
        .catch((err) => console.warn("no cover", err));
    }
  } catch (err) {
    console.error(err);
    showError(`This book could not be opened: ${err?.message || err}`);
  }
}

window.Ebookread = {
  open,
  applySettings,
  next: () => turn(1),
  prev: () => turn(-1),
  goTo: (target) => { closeFootnote(); return view?.goTo(target); },
  goToFraction: (f) => { closeFootnote(); return view?.goToFraction(Math.min(1, Math.max(0, Number(f) || 0))); },
  back: () => view?.history.back(),
  forward: () => view?.history.forward(),
  search,
  clearSearch,
  closeFootnote,
  focus: () => view?.renderer?.focusView?.(),
};

post("page_ready");
