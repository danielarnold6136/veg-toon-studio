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
