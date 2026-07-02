/*
 * mobile.js - canonical mobile viewport helper for AstroWebEngine.
 *
 * Keep one shared answer for "phone/tablet layout?" so generated UI modules do
 * not drift into different breakpoint checks. CSS can key off html.is-mobile;
 * JS can call window.Mobile.isMobile() when a layout decision cannot be made
 * with CSS alone.
 */
(function () {
  'use strict';

  var MOBILE_BP = 800;
  var mq = window.matchMedia('(max-width: ' + MOBILE_BP + 'px)');

  function isMobile() {
    return mq.matches;
  }

  function isTouch() {
    return (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) ||
      ('ontouchstart' in window) ||
      (navigator.maxTouchPoints > 0);
  }

  function applyMobileClass() {
    document.documentElement.classList.toggle('is-mobile', mq.matches);
  }

  function refreshTokens() {
    var header = document.getElementById('main-header');
    if (!header) return;
    var h = Math.round(header.getBoundingClientRect().height);
    if (h > 0) document.documentElement.style.setProperty('--mobile-header-h', h + 'px');
  }

  function onViewportChange() {
    applyMobileClass();
    refreshTokens();
  }

  function init() {
    applyMobileClass();
    refreshTokens();
    window.addEventListener('resize', refreshTokens, { passive: true });
    window.addEventListener('orientationchange', function () { setTimeout(refreshTokens, 80); });
    if (window.ResizeObserver) {
      var header = document.getElementById('main-header');
      if (header) {
        try { new ResizeObserver(refreshTokens).observe(header); } catch (e) { /* noop */ }
      }
    }
    if (mq.addEventListener) mq.addEventListener('change', onViewportChange);
    else if (mq.addListener) mq.addListener(onViewportChange);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.Mobile = {
    BP: MOBILE_BP,
    isMobile: isMobile,
    isTouch: isTouch,
    refreshTokens: refreshTokens
  };
})();
