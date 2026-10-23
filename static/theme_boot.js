// Theme for pages outside the game, applied before first paint.
//
//   <script src="/static/theme_boot.js" data-surface="engine"></script>
//     Engine-owned pages (admin, gallery, server list): always the AWE brand.
//   <script src="/static/theme_boot.js" data-surface="game" data-skin="player"></script>
//     A game's own login/setup: the active ruleset's ui.theme, read from the
//     server (AWE until it answers, which is also the default when the ruleset
//     sets none). data-skin="player" also applies the player's chosen skin.
//
// Nothing here reads the theme cached by the game page, so these pages never
// inherit whichever game this browser happened to visit last.
// game.html keeps its own inline version (it applies ruleset + player overrides).
(function () {
  var root = document.documentElement;
  var me = document.currentScript;
  var surface = (me && me.getAttribute('data-surface')) || 'engine';

  function applyTheme(theme) {
    if (theme && theme !== 'classic') root.setAttribute('data-theme', theme);
    else root.removeAttribute('data-theme');
  }

  applyTheme('awe');
  if (surface !== 'game') return;

  if (me.getAttribute('data-skin') === 'player') {
    try {
      var skin = localStorage.getItem('engine_skin');
      if (skin && skin !== 'blue-nova') root.setAttribute('data-skin', skin);
    } catch (e) { /* storage blocked: no skin */ }
  }

  fetch('/api/engine-config')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (cfg) { if (cfg) applyTheme((cfg.ui && cfg.ui.theme) || 'awe'); })
    .catch(function () { /* keep AWE */ });
})();
