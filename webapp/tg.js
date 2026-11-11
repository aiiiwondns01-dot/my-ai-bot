'use strict';
// Мини-приложение Трекера в Telegram. app.js - тот же, что в Трекер.exe: он ждёт window.pywebview.api
// (get_data, save_data, mtime). Здесь эти три функции ходят на сервер бота вместо data.json.
(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  // скрипт telegram.org может не загрузиться (блокировки, VPN) - тогда подпись берём из адреса,
  // Telegram сам кладёт её туда при открытии мини-приложения
  const fromHash = () => {
    try { return new URLSearchParams(location.hash.slice(1)).get('tgWebAppData') || ''; } catch (e) { return ''; }
  };
  const initData = (tg && tg.initData) || fromHash();
  let rev = '';
  let lastCheck = 0;

  async function call(path, body) {
    const r = await fetch('/api/tracker' + path, {
      method: body ? 'POST' : 'GET',
      headers: { 'X-Init-Data': initData, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
    });
    if (r.status === 403) throw new Error('forbidden');
    if (!r.ok) throw new Error('http ' + r.status);
    return r.json();
  }

  // вместо "data.json не читается" - понятная причина
  function showError(e) {
    const why = String(e && e.message);
    const text = why === 'forbidden'
      ? 'Бот тебя не узнал. Напиши ему любое сообщение и открой Трекер снова.'
      : why === 'http 503'
        ? 'Бот просыпается - подожди полминуты и открой Трекер снова.'
        : 'Нет связи с ботом (' + why + '). Попробуй через минуту.';
    setTimeout(() => { document.getElementById('main').innerHTML = '<div class="loading">' + text + '</div>'; }, 0);
  }

  window.pywebview = {
    api: {
      async get_data() {
        try {
          const r = await call('');
          rev = r.rev;
          return { ok: true, data: r.data, mtime: r.rev };
        } catch (e) {
          showError(e);
          return { ok: false };
        }
      },
      async save_data(data, base) {
        try {
          const r = await call('', { data, rev: base });
          rev = r.rev;
          return r.conflict ? { conflict: true, data: r.data, mtime: r.rev } : { conflict: false, mtime: r.rev };
        } catch (e) {
          // нет связи - ничего не потеряно на сервере, просим повторить
          return { conflict: true, data: null, mtime: base };
        }
      },
      // app.js спрашивает каждые 2 секунды - на сервер ходим не чаще раза в 8 секунд и только с открытым экраном
      async mtime() {
        const t = Date.now();
        if (t - lastCheck > 8000 && !document.hidden) {
          lastCheck = t;
          try { rev = (await call('/rev')).rev; } catch (e) { /* нет сети - попробуем позже */ }
        }
        return rev;
      },
      test_notify() { return true; },
    },
  };

  // на телефоне нет двойного клика: подробности дела открываются обычным нажатием
  document.addEventListener('click', (e) => {
    if (e.target.closest('button, input, select, textarea, a, label, .modal, .modal-bg')) return;
    const el = e.target.closest('[data-kind][data-id]');
    if (el && typeof DETAIL_LIST !== 'undefined' && DETAIL_LIST[el.dataset.kind]) openDetail(el.dataset.kind, el.dataset.id);
  });

  // после выбора раздела - наверх страницы
  document.addEventListener('click', (e) => {
    if (e.target.closest('.nav button')) window.scrollTo(0, 0);
  });

  // скрипт Telegram грузится без ожидания: если telegram.org недоступен, Трекер всё равно откроется
  function setupTg() {
    const w = window.Telegram && window.Telegram.WebApp;
    if (!w) return;
    w.ready();
    w.expand();
    try { w.setHeaderColor('#1a1d1a'); w.setBackgroundColor('#111311'); } catch (e) { /* старый Telegram */ }
  }
  if (tg) setupTg();
  else { const s = document.getElementById('tgjs'); if (s) s.addEventListener('load', setupTg); }
  if (!initData) {
    document.getElementById('main').innerHTML =
      '<div class="loading">Открой Трекер через бота в Telegram: кнопка Трекер слева от поля ввода или команда /tracker.</div>';
    return;
  }
  window.dispatchEvent(new Event('pywebviewready'));
})();
