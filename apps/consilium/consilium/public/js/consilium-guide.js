/* The guide reader (/guide).
   The page works without this file: the contents are links, the search is a
   form, and on a phone the contents are a <details> element. This adds:

   - the contents open beside the chapter on a wide screen and folded into the
     "Contents" button on a narrow one, switching as the window changes;
   - the section being read highlighted in the contents (scroll-spy), and kept
     in view inside the sidebar's own scroll;
   - on a phone, the contents close when a section is chosen;
   - the Print button.
   Plain script, no library: there is no build step in this project. */
(function () {
  "use strict";

  var root = document.querySelector("[data-cns-guide]");
  if (!root) return;

  var WIDE = window.matchMedia("(min-width: 992px)");
  var contents = root.querySelector("[data-cns-guide-contents]");

  // ------------------------------------------------ contents: open or folded
  function fitContents() {
    if (!contents) return;
    contents.open = WIDE.matches;
  }
  fitContents();
  if (WIDE.addEventListener) WIDE.addEventListener("change", fitContents);
  else if (WIDE.addListener) WIDE.addListener(fitContents);

  if (contents) {
    // On a wide screen the sidebar is always open; its summary is hidden, but
    // keep a stray keypress from folding it.
    contents.addEventListener("toggle", function () {
      if (WIDE.matches && !contents.open) contents.open = true;
    });
    contents.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[href]");
      if (link && !WIDE.matches) contents.open = false;
    });
  }

  // ------------------------------------------------------------ scroll-spy
  var links = Array.prototype.slice.call(root.querySelectorAll("[data-cns-toc-link]"));
  var targets = [];
  links.forEach(function (link) {
    var id = decodeURIComponent((link.getAttribute("href") || "").slice(1));
    var heading = id && document.getElementById(id);
    if (heading) targets.push({ link: link, heading: heading });
  });

  var current = null;
  var sideScroll = root.querySelector(".cns-guide-side");

  function offset() {
    // Where a heading counts as "being read": just below the sticky header.
    var header = document.querySelector("[data-cns-header]");
    return (header ? header.getBoundingClientRect().bottom : 0) + 24;
  }

  function setCurrent(entry) {
    if (entry === current) return;
    if (current) {
      current.link.classList.remove("is-current");
      current.link.removeAttribute("aria-current");
    }
    current = entry;
    if (!entry) return;
    entry.link.classList.add("is-current");
    entry.link.setAttribute("aria-current", "location");
    if (WIDE.matches && sideScroll) {
      var box = sideScroll.getBoundingClientRect();
      var at = entry.link.getBoundingClientRect();
      if (at.top < box.top || at.bottom > box.bottom) {
        sideScroll.scrollTop += at.top - box.top - box.height / 3;
      }
    }
  }

  function spy() {
    if (!targets.length) return;
    var line = offset();
    var found = null;
    for (var i = 0; i < targets.length; i++) {
      if (targets[i].heading.getBoundingClientRect().top <= line) found = targets[i];
      else break;
    }
    // At the very bottom the last short section may never reach the line.
    if ((window.innerHeight + window.scrollY) >= document.documentElement.scrollHeight - 2) {
      found = targets[targets.length - 1];
    }
    setCurrent(found);
  }

  var queued = false;
  function onScroll() {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(function () {
      queued = false;
      spy();
    });
  }
  if (targets.length) {
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    window.addEventListener("hashchange", onScroll);
    spy();
  }

  // ---------------------------------------------------------------- print
  var print = root.querySelector("[data-cns-guide-print]");
  if (print) {
    print.addEventListener("click", function () { window.print(); });
  }
})();
