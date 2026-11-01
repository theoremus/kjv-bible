(() => {
  "use strict";

  const KEYS = {
    settings: "kjv-reader-settings-v1",
    bookmarks: "kjv-reader-bookmarks-v1",
    notes: "kjv-reader-notes-v1",
    highlights: "kjv-reader-highlights-v1",
  };

  const read = (key, fallback) => {
    try {
      return JSON.parse(localStorage.getItem(key)) ?? fallback;
    } catch {
      return fallback;
    }
  };

  const write = (key, value) => localStorage.setItem(key, JSON.stringify(value));
  const slug = (value) => String(value || "reading").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  function mainContent() {
    return document.querySelector("main.content") || document.querySelector("main") || document.body;
  }

  function currentScripture() {
    const blocks = [...document.querySelectorAll(".scripture[data-book][data-chapter]")];
    if (!blocks.length) return null;
    const active = blocks.find((block) => {
      const rect = block.getBoundingClientRect();
      return rect.top <= 180 && rect.bottom > 110;
    });
    return active || blocks.find((block) => block.getBoundingClientRect().top > 0) || blocks[0];
  }

  function labelFor(block) {
    if (!block) return document.title.replace(/\s*[|—-].*$/, "");
    return `${block.dataset.book} ${block.dataset.chapter}`;
  }

  function locationKey(block = currentScripture()) {
    return `${location.pathname}::${block?.dataset.book || "reading"}::${block?.dataset.chapter || "start"}`;
  }

  function addCover() {
    const title = document.querySelector("#title-block-header h1.title, .quarto-title-block h1.title");
    if (!title || title.textContent.trim().toLowerCase() !== "the holy bible") return;

    const cover = document.createElement("section");
    cover.className = "reader-front-cover";
    cover.setAttribute("aria-label", "The Holy Bible, King James Version");
    cover.innerHTML = "<div><h2>The Holy Bible</h2><p>King James Version · Old and New Testaments</p><a class=\"reader-cover-download\" href=\"ebooks/The-Holy-Bible.epub\" download>Download the complete Bible · EPUB</a></div><img src=\"cover-vector.svg\" alt=\"Antique engraved title-page illustration\">";
    const titleBlock = title.closest("#title-block-header, .quarto-title-block");
    titleBlock?.after(cover);
  }

  function rangeAtOffsets(paragraph, start, end) {
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let node;
    let total = 0;
    while ((node = walker.nextNode())) {
      const length = node.nodeValue.length;
      nodes.push({ node, start: total, end: total + length });
      total += length;
    }
    if (start < 0 || end <= start || end > total) return null;
    const startNode = nodes.find((item) => start >= item.start && start <= item.end);
    const endNode = nodes.find((item) => end >= item.start && end <= item.end);
    if (!startNode || !endNode) return null;

    const range = document.createRange();
    range.setStart(startNode.node, start - startNode.start);
    range.setEnd(endNode.node, end - endNode.start);
    return range;
  }

  function wrapRange(range) {
    const mark = document.createElement("mark");
    mark.className = "reader-highlight";
    mark.append(range.extractContents());
    range.insertNode(mark);
  }

  function applySavedHighlights() {
    const highlights = read(KEYS.highlights, []).filter((item) => item.path === location.pathname);
    highlights.sort((left, right) => right.start - left.start);
    for (const item of highlights) {
      const block = [...document.querySelectorAll(".scripture")].find((candidate) =>
        candidate.dataset.book === item.book && candidate.dataset.chapter === item.chapter,
      );
      const paragraph = block?.querySelector("p");
      const range = paragraph && rangeAtOffsets(paragraph, item.start, item.end);
      if (range) wrapRange(range);
    }
  }

  function setupToolbar() {
    const root = mainContent();
    const toolbar = document.createElement("nav");
    toolbar.className = "reader-toolbar";
    toolbar.setAttribute("aria-label", "E-reader controls");
    toolbar.innerHTML = `
      <button type="button" data-action="font-down" aria-label="Decrease font size" title="Decrease font size">A−</button>
      <button type="button" data-action="font-up" aria-label="Increase font size" title="Increase font size">A+</button>
      <button type="button" data-action="theme" aria-pressed="false">Dark mode</button>
      <button type="button" data-action="toc" aria-pressed="false">Table of contents</button>
      <button type="button" data-action="reader-toolbar" aria-pressed="false">Hide reader controls</button>
      <button type="button" data-action="highlight" title="Select text first">Highlight selection</button>
      <button type="button" data-action="remove-highlight" title="Select any part of a highlighted passage">Remove highlight</button>
      <a class="reader-image-index-link" href="images.html">Image index</a>
      <button type="button" data-action="notes" aria-expanded="false">Notes</button>
      <button type="button" data-action="bookmarks" aria-expanded="false">Bookmarks</button>
      <button type="button" data-action="add-bookmark">Bookmark chapter</button>
      <a class="reader-ebook-link" href="#" download>Download this book · EPUB</a>
      <span class="reader-spacer" aria-hidden="true"></span>
      <button type="button" data-action="export">Export notes</button>
      <button type="button" data-action="print">Print</button>`;

    const notes = document.createElement("section");
    notes.className = "reader-panel";
    notes.dataset.panel = "notes";
    notes.hidden = true;
    notes.innerHTML = `<strong>Reading note</strong><span class="reader-note-location"></span><textarea aria-label="Personal reading notes" placeholder="Your notes are saved in this browser only."></textarea><small class="reader-note-status" role="status">Saved locally on this device.</small>`;

    const bookmarks = document.createElement("section");
    bookmarks.className = "reader-panel";
    bookmarks.dataset.panel = "bookmarks";
    bookmarks.hidden = true;
    bookmarks.innerHTML = `<strong>Bookmarks</strong><ul class="reader-list"></ul>`;

    root.insertBefore(bookmarks, root.firstChild);
    root.insertBefore(notes, root.firstChild);
    root.insertBefore(toolbar, root.firstChild);

    toolbar.addEventListener("mousedown", (event) => {
      if (event.target.closest('[data-action="highlight"], [data-action="remove-highlight"]')) {
        event.preventDefault();
      }
    });

    const ebookLink = toolbar.querySelector(".reader-ebook-link");
    const currentPage = location.pathname.split("/").pop().replace(/\.html$/i, "");
    if (currentPage && currentPage !== "index") {
      ebookLink.href = `ebooks/${currentPage}.epub`;
      ebookLink.setAttribute("aria-label", `Download ${document.title.split(/[|–-]/)[0].trim()} as EPUB`);
    } else {
      ebookLink.href = "ebooks/The-Holy-Bible.epub";
      ebookLink.textContent = "Download the whole Bible · EPUB";
      ebookLink.setAttribute("aria-label", "Download the complete King James Bible as EPUB");
    }

    const settings = read(KEYS.settings, { fontSize: 1.12, theme: "light", tocHidden: false, toolbarHidden: false });
    const toolbarRestore = document.createElement("button");
    toolbarRestore.className = "reader-toolbar-restore";
    toolbarRestore.type = "button";
    toolbarRestore.textContent = "Show reader controls";
    toolbarRestore.setAttribute("aria-label", "Show reader controls");
    toolbarRestore.hidden = true;
    document.body.append(toolbarRestore);

    const setToolbarHidden = (hidden) => {
      settings.toolbarHidden = hidden;
      document.documentElement.classList.toggle("reader-toolbar-hidden", hidden);
      toolbarRestore.hidden = !hidden;
      const toggle = toolbar.querySelector('[data-action="reader-toolbar"]');
      toggle.textContent = hidden ? "Hide controls" : "Hide reader controls";
      toggle.setAttribute("aria-pressed", String(hidden));
      write(KEYS.settings, settings);
    };
    toolbarRestore.addEventListener("click", () => setToolbarHidden(false));

    const setFontSize = (value) => {
      settings.fontSize = Math.max(0.9, Math.min(1.8, value));
      document.documentElement.style.setProperty("--reader-font-size", `${settings.fontSize}rem`);
      write(KEYS.settings, settings);
    };
    setFontSize(Number(settings.fontSize) || 1.12);
    document.documentElement.dataset.readerTheme = settings.theme === "dark" ? "dark" : "light";
    document.documentElement.classList.toggle("reader-toc-hidden", Boolean(settings.tocHidden));
    setToolbarHidden(Boolean(settings.toolbarHidden));
    toolbar.querySelector('[data-action="theme"]').textContent = settings.theme === "dark" ? "Light mode" : "Dark mode";
    toolbar.querySelector('[data-action="theme"]').setAttribute("aria-pressed", String(settings.theme === "dark"));
    toolbar.querySelector('[data-action="toc"]').setAttribute("aria-pressed", String(settings.tocHidden));

    const noteText = notes.querySelector("textarea");
    const noteLocation = notes.querySelector(".reader-note-location");
    const noteStatus = notes.querySelector(".reader-note-status");
    const refreshNotes = () => {
      const block = currentScripture();
      noteLocation.textContent = block ? ` — ${labelFor(block)}` : "";
      noteText.value = read(KEYS.notes, {})[locationKey(block)] || "";
    };

    const refreshBookmarks = () => {
      const list = bookmarks.querySelector(".reader-list");
      list.replaceChildren();
      const entries = read(KEYS.bookmarks, []);
      if (!entries.length) {
        const empty = document.createElement("li");
        empty.textContent = "No bookmarks saved yet.";
        list.append(empty);
        return;
      }
      entries.forEach((entry, index) => {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = entry.href;
        link.textContent = entry.label;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "Remove";
        remove.setAttribute("aria-label", `Remove bookmark ${entry.label}`);
        remove.addEventListener("click", () => {
          const updated = read(KEYS.bookmarks, []);
          updated.splice(index, 1);
          write(KEYS.bookmarks, updated);
          refreshBookmarks();
        });
        item.append(link, remove);
        list.append(item);
      });
    };

    const closePanels = () => {
      notes.hidden = true;
      bookmarks.hidden = true;
      toolbar.querySelector('[data-action="notes"]').setAttribute("aria-expanded", "false");
      toolbar.querySelector('[data-action="bookmarks"]').setAttribute("aria-expanded", "false");
    };

    toolbar.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;

      if (action === "font-up" || action === "font-down") {
        setFontSize(settings.fontSize + (action === "font-up" ? 0.1 : -0.1));
      } else if (action === "theme") {
        settings.theme = settings.theme === "dark" ? "light" : "dark";
        document.documentElement.dataset.readerTheme = settings.theme;
        button.textContent = settings.theme === "dark" ? "Light mode" : "Dark mode";
        button.setAttribute("aria-pressed", String(settings.theme === "dark"));
        write(KEYS.settings, settings);
      } else if (action === "toc") {
        settings.tocHidden = !settings.tocHidden;
        document.documentElement.classList.toggle("reader-toc-hidden", settings.tocHidden);
        button.setAttribute("aria-pressed", String(settings.tocHidden));
        write(KEYS.settings, settings);
      } else if (action === "reader-toolbar") {
        setToolbarHidden(true);
      } else if (action === "highlight") {
        const selection = window.getSelection();
        if (!selection || selection.isCollapsed || !selection.rangeCount) {
          button.title = "Select a passage first, then choose Highlight selection.";
          return;
        }
        const range = selection.getRangeAt(0);
        const paragraph = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
          ? range.commonAncestorContainer.closest("p")
          : range.commonAncestorContainer.parentElement?.closest("p");
        const scripture = paragraph?.closest(".scripture[data-book][data-chapter]");
        if (!paragraph || !scripture || range.startContainer.parentElement?.closest("mark.reader-highlight")) {
          button.title = "Select text within a Bible passage to highlight it.";
          return;
        }
        const startRange = document.createRange();
        startRange.selectNodeContents(paragraph);
        startRange.setEnd(range.startContainer, range.startOffset);
        const start = startRange.toString().length;
        const quote = range.toString();
        const end = start + quote.length;
        const record = {
          path: location.pathname,
          book: scripture.dataset.book,
          chapter: scripture.dataset.chapter,
          start,
          end,
          quote,
        };
        const all = read(KEYS.highlights, []);
        all.push(record);
        write(KEYS.highlights, all);
        wrapRange(range);
        selection.removeAllRanges();
      } else if (action === "remove-highlight") {
        const selection = window.getSelection();
        const range = selection?.rangeCount ? selection.getRangeAt(0) : null;
        const anchor = range?.commonAncestorContainer;
        const mark = anchor?.nodeType === Node.ELEMENT_NODE
          ? anchor.closest("mark.reader-highlight")
          : anchor?.parentElement?.closest("mark.reader-highlight");
        const paragraph = mark?.closest("p");
        const scripture = paragraph?.closest(".scripture[data-book][data-chapter]");
        if (!mark || !paragraph || !scripture) {
          button.title = "Place the cursor in or select part of a highlighted passage first.";
          return;
        }

        const offsetBefore = document.createRange();
        offsetBefore.selectNodeContents(paragraph);
        offsetBefore.setEndBefore(mark);
        const start = offsetBefore.toString().length;
        const end = start + mark.textContent.length;
        const highlights = read(KEYS.highlights, []);
        write(KEYS.highlights, highlights.filter((item) => !(
          item.path === location.pathname
          && item.book === scripture.dataset.book
          && item.chapter === scripture.dataset.chapter
          && item.start === start
          && item.end === end
        )));
        const text = document.createTextNode(mark.textContent);
        mark.replaceWith(text);
        paragraph.normalize();
        selection?.removeAllRanges();
      } else if (action === "notes") {
        const shouldOpen = notes.hidden;
        closePanels();
        notes.hidden = !shouldOpen;
        button.setAttribute("aria-expanded", String(shouldOpen));
        if (shouldOpen) {
          refreshNotes();
          noteText.focus();
        }
      } else if (action === "bookmarks") {
        const shouldOpen = bookmarks.hidden;
        closePanels();
        bookmarks.hidden = !shouldOpen;
        button.setAttribute("aria-expanded", String(shouldOpen));
        refreshBookmarks();
      } else if (action === "add-bookmark") {
        const block = currentScripture();
        const anchor = block?.id || "top";
        const href = `${location.pathname}${location.search}#${anchor}`;
        const label = labelFor(block);
        const entries = read(KEYS.bookmarks, []);
        if (!entries.some((entry) => entry.href === href)) entries.unshift({ href, label });
        write(KEYS.bookmarks, entries);
        refreshBookmarks();
      } else if (action === "export") {
        const payload = {
          exportedAt: new Date().toISOString(),
          notes: read(KEYS.notes, {}),
          bookmarks: read(KEYS.bookmarks, []),
          highlights: read(KEYS.highlights, []),
        };
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "kjv-reader-notes.json";
        link.click();
        URL.revokeObjectURL(url);
      } else if (action === "print") {
        window.print();
      }
    });

    noteText.addEventListener("input", () => {
      const all = read(KEYS.notes, {});
      all[locationKey()] = noteText.value;
      write(KEYS.notes, all);
      noteStatus.textContent = "Saved locally on this device.";
    });

    document.addEventListener("scroll", () => {
      if (!notes.hidden) refreshNotes();
    }, { passive: true });

    refreshBookmarks();
    refreshNotes();
  }

  function setupImageViewer() {
    const dialog = document.createElement("dialog");
    dialog.className = "reader-image-viewer";
    dialog.setAttribute("aria-label", "Enlarged Bible illustration");
    dialog.innerHTML = `
      <button class="reader-image-viewer-close" type="button" aria-label="Close enlarged image">×</button>
      <img class="reader-image-viewer-image" alt="">
      <p class="reader-image-viewer-caption"></p>`;
    document.body.append(dialog);

    const enlargedImage = dialog.querySelector(".reader-image-viewer-image");
    const caption = dialog.querySelector(".reader-image-viewer-caption");
    const closeButton = dialog.querySelector(".reader-image-viewer-close");
    let opener = null;

    document.querySelectorAll(".reader-illustration img").forEach((image) => {
      const description = image.closest(".reader-illustration")
        ?.querySelector(".illustration-caption")?.textContent.trim() || image.alt;
      image.tabIndex = 0;
      image.setAttribute("role", "button");
      image.setAttribute("aria-label", `Enlarge image: ${description}`);
    });

    const openImage = (image) => {
      opener = image;
      enlargedImage.src = image.currentSrc || image.src;
      enlargedImage.alt = image.alt;
      caption.textContent = image.closest(".reader-illustration")
        ?.querySelector(".illustration-caption")?.textContent.trim() || image.alt;
      dialog.showModal();
      closeButton.focus();
    };

    document.addEventListener("click", (event) => {
      const image = event.target.closest?.(".reader-illustration img");
      if (image) openImage(image);
    });

    document.addEventListener("keydown", (event) => {
      const image = event.target.closest?.(".reader-illustration img");
      if (image && (event.key === "Enter" || event.key === " ")) {
        event.preventDefault();
        openImage(image);
      }
    });

    closeButton.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => opener?.focus());
  }

  function init() {
    document.querySelectorAll(".scripture[data-book][data-chapter]").forEach((block) => {
      block.id = `${slug(block.dataset.book)}-${slug(block.dataset.chapter)}`;
    });
    addCover();
    applySavedHighlights();
    setupToolbar();
    setupImageViewer();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
