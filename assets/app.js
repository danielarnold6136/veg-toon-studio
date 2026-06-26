/* Veg-Toon Studio — copy buttons (robust) + TOC active state */
(function () {
  // Robust copy with Clipboard API + execCommand fallback
  function copyText(text) {
    return new Promise(function (resolve, reject) {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(resolve, function () { legacy(); });
      } else { legacy(); }
      function legacy() {
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'fixed';
          ta.style.top = '-9999px';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          ta.setSelectionRange(0, ta.value.length);
          var ok = document.execCommand('copy');
          document.body.removeChild(ta);
          ok ? resolve() : reject(new Error('execCommand failed'));
        } catch (e) { reject(e); }
      }
    });
  }

  function wire(btn) {
    btn.addEventListener('click', function () {
      // Prefer an explicit data-copy-target id; else the <pre> inside the same .block
      var text = '';
      var tgtId = btn.getAttribute('data-copy-target');
      if (tgtId) {
        var el = document.getElementById(tgtId);
        if (el) text = el.textContent;
      } else {
        var block = btn.closest('.block');
        var pre = block && block.querySelector('pre');
        if (pre) text = pre.textContent;
      }
      text = (text || '').replace(/ /g, ' ').trim();
      var label = btn.textContent;
      copyText(text).then(function () {
        btn.textContent = '✓ Copied';
        btn.classList.add('ok');
        setTimeout(function () { btn.textContent = label; btn.classList.remove('ok'); }, 1500);
      }, function () {
        btn.textContent = '⚠ Press Ctrl+C';
        setTimeout(function () { btn.textContent = label; }, 1800);
      });
    });
  }
  document.querySelectorAll('.copy').forEach(wire);

  // TOC scroll-spy
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a[href^="#"]'));
  var map = {};
  links.forEach(function (a) {
    var id = a.getAttribute('href').slice(1);
    var s = document.getElementById(id);
    if (s) map[id] = a;
  });
  var ids = Object.keys(map);
  if (ids.length && 'IntersectionObserver' in window) {
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          links.forEach(function (a) { a.style.color = ''; a.style.background = ''; });
          var a = map[e.target.id];
          if (a) { a.style.color = 'var(--ink)'; a.style.background = 'var(--panel)'; }
        }
      });
    }, { rootMargin: '-10% 0px -80% 0px' });
    ids.forEach(function (id) { obs.observe(document.getElementById(id)); });
  }
})();

/* Collapsible major sections — collapsed by default to keep long story pages short */
(function () {
  var COLLAPSE = ['fullscript', 'cast', 'scenes', 'packs'];
  COLLAPSE.forEach(function (id) {
    var sec = document.getElementById(id);
    if (!sec) return;
    var wrap = sec.querySelector('.wrap');
    var h2 = wrap && wrap.querySelector('h2');
    if (!wrap || !h2) return;
    var body = document.createElement('div');
    body.className = 'sec-body';
    Array.prototype.slice.call(wrap.children).forEach(function (k) {
      if (k !== h2) body.appendChild(k);
    });
    wrap.appendChild(body);
    h2.classList.add('sec-toggle');
    h2.setAttribute('role', 'button');
    h2.tabIndex = 0;
    var caret = document.createElement('span');
    caret.className = 'caret';
    h2.appendChild(caret);
    function set(open) {
      body.style.display = open ? '' : 'none';
      caret.textContent = open ? '▾' : '▸';
      sec.setAttribute('data-open', open ? '1' : '0');
    }
    set(false);
    function toggle() { set(sec.getAttribute('data-open') !== '1'); }
    h2.addEventListener('click', toggle);
    h2.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
    var tl = document.querySelector('.toc a[href="#' + id + '"]');
    if (tl) tl.addEventListener('click', function () { set(true); });
  });
})();
