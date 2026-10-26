/* The School Expert™ embeddable widgets.
   <div data-tse-widget="school-search"></div>            school search + AI School Match
   <div data-tse-widget="school-card" data-slug="..."></div>  a verified school badge/card
   <script async src="{{ site }}/widget.js"></script> */
(function () {
  var SITE = {{ site | tojson }};
  var nodes = document.querySelectorAll('[data-tse-widget]');
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i], kind = n.getAttribute('data-tse-widget');
    if (n.getAttribute('data-tse-ready')) continue;
    var src = SITE + '/embed/' + encodeURIComponent(kind) + (n.getAttribute('data-slug') ? '?slug=' + encodeURIComponent(n.getAttribute('data-slug')) : '');
    var f = document.createElement('iframe');
    f.src = src; f.title = 'The School Expert™'; f.loading = 'lazy'; f.style.cssText = 'width:100%;border:0;border-radius:14px;min-height:' + (kind === 'school-card' ? '150px' : '320px');
    f.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    n.appendChild(f); n.setAttribute('data-tse-ready', '1');
  }
})();
