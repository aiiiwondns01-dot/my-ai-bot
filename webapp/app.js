'use strict';

// ---------- состояние и константы ----------
const S = {
  data: null, mtime: '', page: 'today', ym: null, charts: {},
  filter: { status: 'all', cat: 'all', q: '' },
};
const DOW = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const DOW_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const STATUS = { todo: 'Не начато', doing: 'В работе', done: 'Выполнено' };
const PRIO = { low: 'Низкий', mid: 'Средний', high: 'Высокий', crit: 'Критичный' };
const PRIO_ORDER = { crit: 0, high: 1, mid: 2, low: 3 };
const REPEAT = { none: 'Один раз', daily: 'Каждый день', weekdays: 'По будням', weekly: 'Каждую неделю' };
// заметки: переписка Вовы и ассистента
const NOTE_KIND = { task: 'Задание', note: 'Заметка', report: 'Отчёт', question: 'Нужен ответ' };
const NOTE_STATUS = { new: 'Ждёт ассистента', taken: 'В работе', done: 'Сделано', failed: 'Не сделано' };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ---------- мелкие помощники ----------
const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const today = () => iso(new Date());
const nowHM = () => { const d = new Date(); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const dow = (d) => (d.getDay() + 6) % 7;
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (p) => (p * 100).toFixed(1).replace('.', ',') + '%';
const pct0 = (p) => Math.round(p * 100) + '%';
const fmtDate = (s) => { if (!s) return ''; const [, m, d] = s.split('-'); return `${+d} ${MONTHS_GEN[+m - 1]}`; };
const opts = (obj, sel) => Object.entries(obj).map(([k, v]) => `<option value="${k}"${k === sel ? ' selected' : ''}>${v}</option>`).join('');
const optList = (arr, sel) => arr.map((v) => `<option${v === sel ? ' selected' : ''}>${esc(v)}</option>`).join('');

function isOverdue(t) {
  if (t.status === 'done' || !t.due) return false;
  return t.due < today() || (t.due === today() && t.time && t.time < nowHM());
}
const statusOf = (t) => (isOverdue(t) ? 'overdue' : t.status);

function remOn(r, date) {
  if (r.off || !r.time) return false;
  const wd = dow(date);
  if (r.repeat === 'daily') return true;
  if (r.repeat === 'weekdays') return wd < 5;
  if (r.repeat === 'weekly') return r.day === wd;
  return r.date === iso(date);
}

// цвета блоков в календаре по категории
const CAT_COLORS = { 'Учёба': '#7fb0e0', 'Торты': '#e891ad', 'Работа': '#86b77f', 'Соцсети': '#a59be6', 'Личное': '#d9b48f', 'Здоровье': '#e5866b' };
const REM_COLOR = '#e3c35a';
const catColor = (c) => CAT_COLORS[c] || '#d9b48f';
const toMin = (hm) => { const [h, m] = hm.split(':').map(Number); return h * 60 + m; };
const monday = (d) => { const x = new Date(d.getFullYear(), d.getMonth(), d.getDate()); x.setDate(x.getDate() - dow(x)); return x; };
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

function normalize(d) {
  d.settings = d.settings || {};
  d.settings.categories = d.settings.categories || ['Учёба', 'Торты', 'Работа', 'Соцсети', 'Личное', 'Здоровье'];
  for (const k of ['habits', 'tasks', 'schedule', 'reminders', 'notes']) d[k] = d[k] || [];
  d.checks = d.checks || {};
  return d;
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove('show'), 2600);
}

// ---------- связь с Python ----------
const api = () => window.pywebview.api;

async function load() {
  const r = await api().get_data();
  if (!r.ok) return false;
  S.data = normalize(r.data);
  S.mtime = r.mtime;
  return true;
}

async function commit() {
  const r = await api().save_data(S.data, S.mtime);
  if (r.conflict) {
    if (r.data) S.data = normalize(r.data);
    S.mtime = r.mtime;
    toast('Файл только что обновился - повтори последнее действие');
  } else {
    S.mtime = r.mtime;
  }
  render();
}

// файл правит и ассистент - подхватываем его изменения
async function poll() {
  try {
    const m = await api().mtime();
    if (m !== S.mtime && await load()) {
      const a = document.activeElement;
      if (!(a && a.matches('input, select, textarea'))) render();
    }
  } catch (e) { /* окно закрывается */ }
}

// ---------- общие куски разметки ----------
function ring(p, big, small, color) {
  const r = 52, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(1, p || 0)));
  return `<div class="ring"><svg viewBox="0 0 120 120">
    <circle cx="60" cy="60" r="${r}" class="ring-bg"/>
    <circle cx="60" cy="60" r="${r}" class="ring-fg" style="stroke:${color || 'var(--green)'}"
      stroke-dasharray="${c}" stroke-dashoffset="${off}" transform="rotate(-90 60 60)"/>
  </svg><div class="ring-t"><b>${big}</b><span>${small}</span></div></div>`;
}
const tile = (n, label, warn) => `<div class="tile${warn && n ? ' warn' : ''}"><b>${n}</b><span>${label}</span></div>`;
const cb = (on, act, id, extra = '') => `<button class="cb${on ? ' on' : ''}" data-act="${act}" data-id="${id}" ${extra}></button>`;

function chartBase() {
  Chart.defaults.color = css('--muted');
  Chart.defaults.font.family = '"Monocraft", "Consolas", monospace';
  Chart.defaults.font.size = 12;
  Chart.defaults.borderColor = css('--line');
}

// ---------- страница: сегодня ----------
function pageToday() {
  const d = S.data, t = today(), wd = dow(new Date());
  const items = [
    ...d.schedule.filter((s) => s.day === wd).map((s) => ({ time: s.start, end: s.end, title: s.title, sub: s.place, kind: 'Расписание' })),
    ...d.reminders.filter((r) => remOn(r, new Date())).map((r) => ({ time: r.time, title: r.title, kind: 'Напоминание' })),
  ].sort((a, b) => (a.time || '').localeCompare(b.time || ''));

  const tasks = d.tasks.filter((x) => (x.status !== 'done' && (isOverdue(x) || x.due === t || x.status === 'doing')) || (x.status === 'done' && x.done_at === t))
    .sort(taskSort);
  const doneToday = d.tasks.filter((x) => x.done_at === t && x.status === 'done').length;
  const openToday = tasks.filter((x) => x.status !== 'done').length;
  const overdue = d.tasks.filter(isOverdue).length;
  const unread = unreadNotes().length;
  const asks = d.notes.filter(needsAnswer);

  const scheduleHtml = items.length ? items.map((i) => `<div class="li">
      <div class="time">${esc(i.time)}${i.end ? '-' + esc(i.end) : ''}</div>
      <div class="t">${esc(i.title)}${i.sub ? `<small>${esc(i.sub)}</small>` : ''}</div>
      <span class="tag">${i.kind}</span></div>`).join('')
    : '<div class="empty">На сегодня ничего не запланировано.</div>';

  const tasksHtml = tasks.length ? tasks.map((x) => `<div class="li${x.status === 'done' ? ' done' : ''}" data-kind="task" data-id="${x.id}" title="Двойной клик - подробности">
      ${cb(x.status === 'done', 'task-toggle', x.id)}
      <div class="t"><span class="dot p-${x.priority}"></span>${esc(x.title)}<small>${esc(x.category || '')}${x.due ? ' · ' + fmtDate(x.due) : ''}${x.time ? ' ' + esc(x.time) : ''}</small></div>
      ${isOverdue(x) ? '<span class="tag red">просрочено</span>' : x.status === 'doing' ? '<span class="tag">в работе</span>' : ''}
    </div>`).join('')
    : '<div class="empty">Дел на сегодня нет. Добавить можно во вкладке "Дела".</div>';

  const fresh = d.notes.filter((n) => n.from === 'claude' && (!n.read || needsAnswer(n))).sort(noteSort).slice(0, 4);
  const notesHtml = fresh.length ? fresh.map((n) => `<div class="li note-mini">
      <div class="t">${esc(n.text.split('\n')[0])}<small>${fmtStamp(n.at)}</small></div>
      <span class="tag${needsAnswer(n) ? ' amber' : ''}">${NOTE_KIND[n.kind] || ''}</span></div>`).join('')
    : '<div class="empty">Новых записок нет.</div>';

  const now = new Date();
  return `<h1>${DOW_FULL[wd]}, ${now.getDate()} ${MONTHS_GEN[now.getMonth()]}</h1>
  <div class="sub">План на день</div>
  <div class="row cols-4">
    ${tile(openToday, 'Дел осталось')}${tile(doneToday, 'Сделано сегодня')}
    ${tile(overdue, 'Просрочено', true)}${tile(asks.length, 'Ждут ответа', true)}
  </div>
  <div class="row cols-main">
    <div>
      <div class="card" style="margin-bottom:16px"><div class="card-h">Расписание и напоминания</div><div class="card-b list">${scheduleHtml}</div></div>
      <div class="card"><div class="card-h clay">Дела<span class="right">сегодня, в работе и просроченные</span></div><div class="card-b list">${tasksHtml}</div></div>
    </div>
    <div>
      <div class="card" style="margin-bottom:16px"><div class="card-h">Итоги дня</div><div class="card-b rings">
        <div>${ring(doneToday + openToday ? doneToday / (doneToday + openToday) : 0, `${doneToday}/${doneToday + openToday}`, 'дела', 'var(--clay)')}</div>
      </div></div>
      <div class="card"><div class="card-h">Записки ассистента<span class="right">${unread ? `новых: ${unread}` : ''}</span></div>
        <div class="card-b list go-notes" data-act="go-notes">${notesHtml}</div></div>
    </div>
  </div>`;
}

// ---------- страница: заметки ----------
// Переписка: Вова пишет задания и заметки, ассистент - отчёты и вопросы.
// Ассистент видит новые задания при каждом сообщении в чате (хук в .claude/settings.json).
const pad2 = (s) => s.slice(0, 16).replace('T', ' ');
function fmtStamp(s) {
  if (!s) return '';
  const [d, tm] = pad2(s).split(' ');
  return `${d === today() ? 'сегодня' : fmtDate(d)} ${tm || ''}`.trim();
}
const needsAnswer = (n) => n.from === 'claude' && n.kind === 'question' && !n.answered;
const unreadNotes = () => S.data.notes.filter((n) => n.from === 'claude' && !n.read);
const noteSort = (a, b) => (b.at || '').localeCompare(a.at || '');
const nowStamp = () => `${today()}T${nowHM()}`;
const textHtml = (s) => esc(s).replace(/\n/g, '<br>');

function noteHtml(n, all) {
  const me = n.from === 'vova';
  const parent = n.reply_to && byId(all, n.reply_to);
  const status = me && n.kind === 'task' ? `<span class="tag st-${n.status}">${NOTE_STATUS[n.status] || ''}</span>` : '';
  const kind = `<span class="tag${needsAnswer(n) ? ' amber' : ''}${n.kind === 'report' && n.result === 'failed' ? ' red' : ''}">${n.kind === 'report' ? (n.result === 'failed' ? 'Не сделано' : 'Сделано') : NOTE_KIND[n.kind] || ''}</span>`;
  return `<div class="note ${me ? 'mine' : 'theirs'}${!me && !n.read ? ' unread' : ''}">
    <div class="note-h"><b>${me ? 'Я' : 'Ассистент'}</b><span>${fmtStamp(n.at)}</span>${kind}${status}
      <span class="note-act">${!me ? `<button class="btn ghost sm" data-act="note-reply" data-id="${n.id}">Ответить</button>` : ''}
      <button class="x" data-act="note-del" data-id="${n.id}" title="Удалить">×</button></span></div>
    ${parent ? `<div class="note-quote">${esc(parent.text.slice(0, 140))}${parent.text.length > 140 ? '…' : ''}</div>` : ''}
    <div class="note-t">${textHtml(n.text)}</div></div>`;
}

function pageNotes() {
  const d = S.data, f = S.noteFilter || 'all';
  const list = d.notes.filter((n) => f === 'all'
    || (f === 'ask' && needsAnswer(n))
    || (f === 'task' && n.from === 'vova' && n.kind === 'task')).sort(noteSort);
  const reply = S.replyTo && byId(d.notes, S.replyTo);
  const counts = { ask: d.notes.filter(needsAnswer).length, task: d.notes.filter((n) => n.from === 'vova' && n.kind === 'task' && ['new', 'taken'].includes(n.status)).length };
  return `<h1>Заметки</h1><div class="sub">Переписка с ассистентом</div>
  <div class="card"><div class="card-h">${reply ? 'Ответ ассистенту' : 'Написать ассистенту'}</div><div class="card-b">
    ${reply ? `<div class="note-quote">${esc(reply.text.slice(0, 200))}<button class="x" data-act="note-unreply" title="Не отвечать">×</button></div>` : ''}
    <textarea class="inp area" id="nnText" placeholder="${reply ? 'Твой ответ' : 'Задание или заметка. Задание ассистент увидит при следующем сообщении в чате.'}"></textarea>
    <div class="form" style="margin-top:8px">
      ${reply ? '' : `<select class="inp" id="nnKind">${opts({ task: 'Задание ассистенту', note: 'Просто заметка' }, 'task')}</select>`}
      <button class="btn" data-act="note-add">Отправить</button>
      <span class="hint">Ctrl+Enter - отправить</span>
    </div></div></div>
  <div class="card" style="margin-top:16px"><div class="card-h clay">Лента
    <span class="right form">
      <select class="inp" data-act="note-filter">${opts({ all: 'Все', ask: `Ждут моего ответа (${counts.ask})`, task: `Мои задания (${counts.task} в работе)` }, f)}</select>
    </span></div>
    <div class="card-b notes">${list.length ? list.map((n) => noteHtml(n, d.notes)).join('') : '<div class="empty">Пока пусто.</div>'}</div></div>`;
}

// открыл вкладку - записки ассистента прочитаны
function afterNotes() {
  const un = unreadNotes();
  if (!un.length) return;
  for (const n of un) n.read = true;
  commit();
}

// ---------- страница: дела ----------
function taskSort(a, b) {
  const da = a.status === 'done', db = b.status === 'done';
  if (da !== db) return da ? 1 : -1;
  if ((a.due || '9') !== (b.due || '9')) return (a.due || '9').localeCompare(b.due || '9');
  if ((a.time || '99') !== (b.time || '99')) return (a.time || '99').localeCompare(b.time || '99');
  return (PRIO_ORDER[a.priority] ?? 9) - (PRIO_ORDER[b.priority] ?? 9);
}

function taskCounts() {
  const c = { done: 0, doing: 0, todo: 0, overdue: 0 };
  for (const t of S.data.tasks) c[statusOf(t)]++;
  return c;
}

function pageTasks() {
  const d = S.data, f = S.filter, c = taskCounts(), total = d.tasks.length, cats = d.settings.categories;
  const list = d.tasks.filter((t) => (f.status === 'all' || statusOf(t) === f.status)
    && (f.cat === 'all' || t.category === f.cat)
    && (!f.q || t.title.toLowerCase().includes(f.q.toLowerCase()))).sort(taskSort);

  const rows = list.map((t) => `<tr class="${statusOf(t)}">
    <td style="width:34px">${cb(t.status === 'done', 'task-toggle', t.id)}</td>
    <td><input class="cell title" value="${esc(t.title)}" data-act="task-set" data-f="title" data-id="${t.id}"></td>
    <td style="width:130px"><select class="cell" data-act="task-set" data-f="category" data-id="${t.id}">${optList(cats.includes(t.category) ? cats : [...cats, t.category], t.category)}</select></td>
    <td style="width:150px"><div style="display:flex;align-items:center"><span class="dot p-${t.priority}"></span><select class="cell" data-act="task-set" data-f="priority" data-id="${t.id}">${opts(PRIO, t.priority)}</select></div></td>
    <td style="width:130px"><select class="cell" data-act="task-set" data-f="status" data-id="${t.id}">${opts(STATUS, t.status)}</select></td>
    <td style="width:140px"><input class="cell" type="date" value="${esc(t.due)}" data-act="task-set" data-f="due" data-id="${t.id}"></td>
    <td style="width:100px"><input class="cell" type="time" value="${esc(t.time)}" data-act="task-set" data-f="time" data-id="${t.id}"></td>
    <td style="width:30px"><button class="note-btn${t.details ? ' on' : ''}" data-act="detail-open" data-kind="task" data-id="${t.id}" title="Подробности">≡</button></td>
    <td style="width:30px"><button class="x" data-act="task-del" data-id="${t.id}" title="Удалить">×</button></td>
  </tr>`).join('');

  const legendItem = (key, label, color) => `<div><span class="sw" style="background:${color}"></span>${label}<b>${c[key]}</b></div>`;
  return `<h1>Дела</h1><div class="sub">Задачи и дедлайны</div>
  <div class="row cols-4">${tile(total, 'Всего задач')}${tile(c.doing, 'В работе')}${tile(c.done, 'Выполнено')}${tile(c.overdue, 'Просрочено', true)}</div>
  <div class="row cols-2">
    <div class="card"><div class="card-h">Прогресс</div><div class="card-b">${ring(total ? c.done / total : 0, total ? pct(c.done / total) : '-', `${c.done} из ${total}`)}</div></div>
    <div class="card"><div class="card-h clay">Статусы</div><div class="card-b donut-wrap">
      <div class="chart-box"><canvas id="statusChart"></canvas></div>
      <div class="legend">${legendItem('done', 'Выполнено', css('--green'))}${legendItem('doing', 'В работе', css('--amber'))}${legendItem('todo', 'Не начато', css('--gray'))}${legendItem('overdue', 'Просрочено', css('--red'))}</div>
    </div></div>
  </div>
  <div class="card"><div class="card-h">Новая задача</div><div class="card-b">
    <div class="form">
      <input class="inp grow" id="ntTitle" placeholder="Что сделать">
      <select class="inp" id="ntCat">${optList(cats, cats[0])}</select>
      <select class="inp" id="ntPrio">${opts(PRIO, 'mid')}</select>
      <input class="inp" type="date" id="ntDue" value="${today()}">
      <input class="inp" type="time" id="ntTime" title="Время напоминания (необязательно)">
      <button class="btn" data-act="task-add">Добавить</button>
    </div></div></div>
  <div class="card" style="margin-top:16px"><div class="card-h clay">Список
      <span class="right form">
        <select class="inp" data-act="filter" data-f="status">${opts({ all: 'Все статусы', todo: 'Не начато', doing: 'В работе', done: 'Выполнено', overdue: 'Просрочено' }, f.status)}</select>
        <select class="inp" data-act="filter" data-f="cat"><option value="all">Все категории</option>${optList(cats, f.cat)}</select>
        <input class="inp" placeholder="Поиск" value="${esc(f.q)}" data-act="filter" data-f="q">
      </span></div>
    <div class="card-b">${rows ? `<table><thead><tr><th></th><th>Задача</th><th>Категория</th><th>Приоритет</th><th>Статус</th><th>Срок</th><th>Время</th><th></th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : '<div class="empty">Задач нет.</div>'}</div></div>`;
}

function afterTasks() {
  const el = document.getElementById('statusChart');
  if (!el) return;
  const c = taskCounts();
  chartBase();
  const empty = !S.data.tasks.length;
  S.charts.status = new Chart(el, {
    type: 'doughnut',
    data: {
      labels: empty ? ['Нет задач'] : ['Выполнено', 'В работе', 'Не начато', 'Просрочено'],
      datasets: [{
        data: empty ? [1] : [c.done, c.doing, c.todo, c.overdue],
        backgroundColor: empty ? [css('--panel2')] : [css('--green'), css('--amber'), css('--gray'), css('--red')],
        borderColor: css('--panel'), borderWidth: 2,
      }],
    },
    options: { maintainAspectRatio: false, animation: false, cutout: '72%', plugins: { legend: { display: false }, tooltip: { enabled: !empty } } },
  });
}

// ---------- страница: расписание ----------
// масштаб календаря: S.hourH - пикселей на час, null = "вся неделя в экран" (S.fitH)
const ZOOM_MAX = 160;
const hourH = () => S.hourH || S.fitH || 48;

// всё, что попадает в день: пары/события, дела со временем, напоминания
function dayEvents(date) {
  const d = S.data, ds = iso(date), wd = dow(date), ev = [];
  for (const s of d.schedule) {
    if (s.day !== wd || !s.start) continue;
    const a = toMin(s.start), b = s.end ? Math.max(toMin(s.end), a + 20) : a + 60;
    ev.push({ kind: 'sched', id: s.id, a, b, title: s.title, sub: `${s.start}${s.end ? '-' + s.end : ''}${s.place ? ' · ' + s.place : ''}`, color: catColor(s.category) });
  }
  for (const t of d.tasks) {
    if (t.due !== ds || !t.time) continue;
    const a = toMin(t.time);
    ev.push({ kind: 'task', id: t.id, a, b: a + 45, title: t.title, sub: t.time, color: catColor(t.category), done: t.status === 'done' });
  }
  for (const r of d.reminders) {
    if (!remOn(r, date)) continue;
    const a = toMin(r.time);
    ev.push({ kind: 'rem', id: r.id, a, b: a + 25, title: r.title, sub: r.time, color: REM_COLOR, thin: true });
  }
  return layoutDay(ev);
}

// пересекающиеся блоки делят ширину колонки на дорожки
function layoutDay(ev) {
  ev.sort((x, y) => x.a - y.a || y.b - x.b);
  let cluster = [], end = -1;
  const flush = () => {
    const lanes = [];
    for (const e of cluster) {
      let i = lanes.findIndex((l) => l <= e.a);
      if (i < 0) { i = lanes.length; lanes.push(0); }
      lanes[i] = e.b;
      e.lane = i;
    }
    for (const e of cluster) e.lanes = lanes.length;
    cluster = [];
  };
  for (const e of ev) {
    if (cluster.length && e.a >= end) flush();
    cluster.push(e);
    end = Math.max(end, e.b);
  }
  if (cluster.length) flush();
  return ev;
}

// ужимаем текст блока под его размер: сначала убираем детали, потом сокращаем слова
const LINE = 16, SUB_LINE = 14;
const shortWords = (s, max, keep) => s.split(' ').map((w) => (w.length > max ? w.slice(0, keep) + '.' : w)).join(' ');
const shortKind = (s) => s.replace('Лекция', 'Лек.').replace('Практика', 'Пр.');

// сколько строк займёт текст при переносе по словам; Infinity - если слово не влезает целиком
const measureCtx = document.createElement('canvas').getContext('2d');
function wrapLines(text, font, width) {
  if (!text) return 0;
  measureCtx.font = font;
  const space = measureCtx.measureText(' ').width;
  let lines = 1, cur = 0;
  for (const word of text.split(' ')) {
    const ww = measureCtx.measureText(word).width;
    if (ww > width) return Infinity;
    if (cur && cur + space + ww > width) { lines++; cur = ww; } else cur += (cur ? space : 0) + ww;
  }
  return lines;
}

function fitText(e, w, h) {
  const parts = e.sub.split(' · ');
  const subs = [e.sub, parts.slice(0, 3).join(' · '), shortKind(parts.slice(0, 3).join(' · ')), parts[0], ''];
  const titles = [e.title, shortWords(e.title, 10, 7), shortWords(e.title, 8, 6), shortWords(e.title, 7, 4), shortWords(e.title, 4, 3)];
  const tw = w - 14 - (e.kind === 'task' ? 22 : 0);
  const tLines = (t) => wrapLines(t, '700 13px "Segoe UI"', tw);
  const sLines = (s) => wrapLines(s, '400 11px Monocraft', w - 14);
  const maxLines = Math.max(1, Math.floor((h - 6) / LINE));
  for (const t of titles) {
    const tl = tLines(t);
    if (tl > maxLines) continue;
    for (const s of t === e.title ? subs : ['']) {
      if (6 + tl * LINE + sLines(s) * SUB_LINE <= h) return { t, s, clamp: tl };
    }
  }
  // совсем мелко: самое короткое название в одну-две строки с многоточием
  return { t: titles[4], s: '', clamp: maxLines };
}

function evHtml(e, startH, hh, colW) {
  const top = (e.a - startH * 60) / 60 * hh + 1;
  const h = Math.max(e.thin ? 18 : 20, (e.b - e.a) / 60 * hh - 2);
  const w = colW / e.lanes - 6;
  const left = `calc(${(e.lane / e.lanes) * 100}% + 3px)`, width = `calc(${100 / e.lanes}% - 6px)`;
  const ctrl = e.kind === 'task' ? cb(e.done, 'task-toggle', e.id, 'title="Сделано"') : '';
  const del = e.kind === 'sched' ? `<button class="x" data-act="sched-del" data-id="${e.id}" title="Удалить из расписания">×</button>`
    : e.kind === 'rem' ? `<button class="x" data-act="rem-del" data-id="${e.id}" title="Удалить напоминание">×</button>` : '';
  const f = e.thin ? { t: e.title, s: '', clamp: 1 } : fitText(e, w, h);
  const tight = h < 30 ? ' tight' : '';
  const hasNote = detailsOf(e.kind, e.id) ? ' has-note' : '';
  return `<div class="ev${e.thin ? ' thin' : ''}${e.done ? ' done' : ''}${tight}${hasNote}" data-kind="${e.kind}" data-id="${e.id}" title="${esc(e.title + ' · ' + e.sub)}&#10;Двойной клик - подробности"
    style="top:${top}px;height:${h}px;left:${left};width:${width};background:${e.color}">
    ${ctrl}<div class="t"><span class="tt" style="-webkit-line-clamp:${f.clamp}">${e.kind === 'rem' ? '🔔 ' : ''}${esc(f.t)}</span>${f.s ? `<small>${esc(f.s)}</small>` : ''}</div>${del}</div>`;
}

function pageSchedule() {
  const d = S.data, wd = dow(new Date()), t = today(), cats = d.settings.categories;
  const days = Array.from({ length: 7 }, (_, i) => addDays(S.weekStart, i));
  const events = days.map(dayEvents);
  // диапазон часов: от первого события (но не позже 8:00) до полуночи
  const all = events.flat();
  const inWeek = days.some((dd) => iso(dd) === t);
  const startH = Math.min(8, Math.floor(Math.min(...all.map((e) => e.a), 24 * 60) / 60));
  const endH = 24;
  S.calHours = endH - startH;
  const hh = hourH();
  const gridH = (endH - startH) * hh;
  const colW = (document.getElementById('main').clientWidth - 62 - 64) / 7;

  const mid = addDays(S.weekStart, 3), last = days[6];
  const range = S.weekStart.getMonth() === last.getMonth()
    ? `${S.weekStart.getDate()}-${last.getDate()} ${MONTHS_GEN[last.getMonth()]}`
    : `${S.weekStart.getDate()} ${MONTHS_GEN[S.weekStart.getMonth()]} - ${last.getDate()} ${MONTHS_GEN[last.getMonth()]}`;

  const head = days.map((dd, i) => `<div class="ch${iso(dd) === t ? ' today' : ''}${i > 4 ? ' weekend' : ''}"><span>${DOW[i]}</span><b>${dd.getDate()}</b></div>`).join('');
  const now = new Date(), nowMin = now.getHours() * 60 + now.getMinutes();
  const nowTop = (nowMin - startH * 60) / 60 * hh;
  const showNow = inWeek && nowTop >= 0 && nowTop <= gridH;

  // при сильном отдалении подписываем каждый второй час; подпись под плашкой "сейчас" прячем
  const step = hh < 26 ? 2 : 1;
  const hours = Array.from({ length: endH - startH }, (_, i) => (i && i % step === 0 && !(showNow && Math.abs(i * hh - nowTop) < 16)
    ? `<div class="hour" style="top:${i * hh}px">${pad(startH + i)}:00</div>` : '')).join('');

  const cols = days.map((dd, i) => `<div class="col${iso(dd) === t ? ' today' : ''}">
      ${events[i].map((e) => evHtml(e, startH, hh, colW)).join('')}
      ${showNow && iso(dd) === t ? `<div class="now-line" style="top:${nowTop}px"></div>` : ''}
    </div>`).join('');

  const lines = `background-image:linear-gradient(to bottom, var(--line) 1px, transparent 1px);background-size:100% ${hh}px;`;
  const legend = cats.map((c) => `<span><i style="background:${catColor(c)}"></i>${esc(c)}</span>`).join('') + `<span><i style="background:${REM_COLOR}"></i>Напоминание</span>`;

  const rems = [...d.reminders].sort((a, b) => (a.time || '').localeCompare(b.time || '')).map((r) => {
    const when = r.repeat === 'none' ? fmtDate(r.date) : r.repeat === 'weekly' ? DOW_FULL[r.day] : REPEAT[r.repeat];
    return `<div class="li${r.off ? ' done' : ''}">
      ${cb(!r.off, 'rem-toggle', r.id, 'title="Включено"')}
      <div class="time">${esc(r.time)}</div>
      <div class="t">${esc(r.title)}<small>${esc(when)}</small></div>
      <button class="x" data-act="rem-del" data-id="${r.id}" title="Удалить">×</button></div>`;
  }).join('') || '<div class="empty">Напоминаний пока нет.</div>';

  const dayOpts = DOW_FULL.map((n, i) => `<option value="${i}"${i === wd ? ' selected' : ''}>${n}</option>`).join('');
  return `<div class="cal-top">
      <button class="btn ghost" data-act="week" data-d="-1">‹</button>
      <h1>${MONTHS[mid.getMonth()]} ${mid.getFullYear()}</h1>
      <button class="btn ghost" data-act="week" data-d="1">›</button>
      <button class="btn ghost" data-act="week" data-d="0">Сегодня</button>
      <div class="zoom">
        <span class="hint">Ctrl + колесо - масштаб</span>
        <button class="btn ghost" data-act="zoom" data-d="-1" title="Отдалить">−</button>
        <button class="btn ghost${S.hourH ? '' : ' on'}" data-act="zoom" data-d="0" title="Вся неделя в экран">Вся неделя</button>
        <button class="btn ghost" data-act="zoom" data-d="1" title="Приблизить">+</button>
      </div>
    </div>
    <div class="sub">${range}</div>
  <div class="card cal">
    <div class="cal-head"><div></div>${head}</div>
    <div class="cal-body" id="calBody">
      <div class="cal-grid" style="height:${gridH}px;${lines}">
        <div class="gut">${hours}${showNow ? `<div class="now-pill" style="top:${nowTop}px">${pad(now.getHours())}:${pad(now.getMinutes())}</div>` : ''}</div>
        ${cols}
      </div>
    </div>
    <div class="card-b legend-row" style="border-top:1px solid var(--line)">${legend}</div>
  </div>
  <div class="card" style="margin-bottom:16px"><div class="card-h">Добавить в расписание<span class="right">повторяется каждую неделю · напомню за ${d.settings.schedule_remind_min ?? 15} мин</span></div><div class="card-b">
    <div class="form">
      <select class="inp" id="nsDay">${dayOpts}</select>
      <input class="inp" type="time" id="nsStart" value="09:00">
      <input class="inp" type="time" id="nsEnd" value="10:30">
      <input class="inp grow" id="nsTitle" placeholder="Что: пара, смена, встреча">
      <input class="inp" id="nsPlace" placeholder="Где (необязательно)">
      <select class="inp" id="nsCat">${optList(cats, cats[0])}</select>
      <button class="btn" data-act="sched-add">Добавить</button>
    </div></div></div>
  <div class="card"><div class="card-h clay">Напоминания
      <span class="right"><button class="btn ghost" style="padding:3px 10px" data-act="test-notify">Проверить уведомление</button></span></div>
    <div class="card-b"><div class="list">${rems}</div>
    <div class="form" style="margin-top:14px">
      <input class="inp grow" id="nrTitle" placeholder="О чём напомнить">
      <select class="inp" id="nrRepeat">${opts(REPEAT, 'none')}</select>
      <input class="inp" type="date" id="nrDate" value="${today()}">
      <select class="inp" id="nrDay" style="display:none">${dayOpts}</select>
      <input class="inp" type="time" id="nrTime" value="${nowHM()}">
      <button class="btn" data-act="rem-add">Добавить</button>
    </div></div></div>`;
}

// ---------- подробности дела, пары или напоминания ----------
// Двойной клик по блоку календаря или делу открывает полную заметку (поле details).
// Заметки пишет и ассистент - пошаговые инструкции к делам.
const DETAIL_LIST = { task: 'tasks', sched: 'schedule', rem: 'reminders' };
const itemOf = (kind, id) => DETAIL_LIST[kind] && byId(S.data[DETAIL_LIST[kind]], id);
const detailsOf = (kind, id) => (itemOf(kind, id) || {}).details || '';

// лёгкая разметка: "## заголовок", "- пункт", "[ ] шаг", "[x] сделано", пустая строка - абзац
function detailsHtml(text) {
  let html = '', list = false;
  const close = () => { if (list) { html += '</ul>'; list = false; } };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    const m = line.match(/^\s*(?:[-*]|\[( |x|х)\])\s+(.*)$/i);
    if (m) {
      if (!list) { html += '<ul class="dl">'; list = true; }
      const box = m[1] === undefined ? '' : `<span class="dbox${m[1].trim() ? ' on' : ''}"></span>`;
      html += `<li${box ? ' class="step"' : ''}>${box}${esc(m[2])}</li>`;
      continue;
    }
    close();
    if (/^#{1,3}\s/.test(line)) html += `<h3>${esc(line.replace(/^#+\s/, ''))}</h3>`;
    else if (line.trim()) html += `<p>${esc(line)}</p>`;
  }
  close();
  return html;
}

function detailModal() {
  if (!S.detail) return '';
  const { kind, id } = S.detail, it = itemOf(kind, id);
  if (!it) { S.detail = null; return ''; }
  const when = kind === 'task' ? `${it.due ? fmtDate(it.due) : 'без срока'}${it.time ? ' ' + it.time : ''}`
    : kind === 'sched' ? `${DOW_FULL[it.day]}, ${it.start}${it.end ? '-' + it.end : ''}${it.place ? ' · ' + it.place : ''}`
    : `${it.repeat === 'none' ? fmtDate(it.date) : it.repeat === 'weekly' ? DOW_FULL[it.day] : REPEAT[it.repeat]} ${it.time}`;
  const meta = [kind === 'task' ? 'Дело' : kind === 'sched' ? 'Расписание' : 'Напоминание', when,
    it.category, kind === 'task' ? STATUS[it.status] : ''].filter(Boolean).map((s) => `<span class="tag">${esc(s)}</span>`).join('');
  const body = S.detailEdit
    ? `<textarea class="inp area big" id="detailText" placeholder="Описание, шаги, ссылки. Строка с '- ' - пункт списка, '[ ] ' - шаг, '## ' - заголовок.">${esc(it.details || '')}</textarea>`
    : it.details ? `<div class="dtext">${detailsHtml(it.details)}</div>` : '<div class="empty">Описания пока нет. Нажми "Редактировать", чтобы добавить.</div>';
  const btns = S.detailEdit
    ? '<button class="btn" data-act="detail-save">Сохранить</button><button class="btn ghost" data-act="detail-cancel">Отмена</button>'
    : `${kind === 'task' ? `<button class="btn${it.status === 'done' ? ' ghost' : ''}" data-act="detail-done">${it.status === 'done' ? 'Вернуть в работу' : 'Сделано'}</button>` : ''}
       <button class="btn ghost" data-act="detail-edit">Редактировать</button>`;
  return `<div class="modal-bg"><div class="modal" role="dialog">
    <div class="modal-h"><h2>${esc(it.title)}</h2><button class="x big" data-act="detail-close" title="Закрыть (Esc)">×</button></div>
    <div class="modal-meta">${meta}</div>
    <div class="modal-b">${body}</div>
    <div class="modal-f form">${btns}<span class="hint">Esc - закрыть</span></div>
  </div></div>`;
}

function openDetail(kind, id) {
  S.detail = { kind, id };
  S.detailEdit = false;
  render();
}

// ---------- отрисовка ----------
const PAGES = { today: pageToday, notes: pageNotes, tasks: pageTasks, schedule: pageSchedule };
const AFTER = { notes: afterNotes, tasks: afterTasks, schedule: afterSchedule };

// календарь: высота под окно, режим "вся неделя" подгоняет масштаб без прокрутки
function afterSchedule() {
  const body = document.getElementById('calBody');
  const avail = Math.max(300, window.innerHeight - body.getBoundingClientRect().top - 70 + document.getElementById('main').scrollTop);
  body.style.maxHeight = avail + 'px';
  const fit = Math.max(20, Math.floor(avail / S.calHours));
  if (fit !== S.fitH) {
    S.fitH = fit;
    if (!S.hourH) { render(); return; }
  }
  if (S.calScroll == null) {
    const nowLine = body.querySelector('.now-line');
    S.calScroll = S.hourH && nowLine ? Math.max(0, nowLine.offsetTop - 2 * hourH()) : 0;
  }
  body.scrollTop = S.calScroll;
  body.addEventListener('scroll', () => { S.calScroll = body.scrollTop; });
  // Ctrl + колесо / щипок на тачпаде - масштаб вокруг точки под курсором
  body.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    zoomAt(Math.exp(-e.deltaY * 0.0025), e.clientY - body.getBoundingClientRect().top);
  }, { passive: false });
}

function zoomAt(factor, anchorY) {
  const body = document.getElementById('calBody');
  const old = hourH();
  const next = Math.min(ZOOM_MAX, Math.max(S.fitH, old * factor));
  if (Math.abs(next - old) < 0.5) return;
  const minute = (body.scrollTop + anchorY) / old * 60;
  S.hourH = next <= S.fitH + 0.5 ? null : next;
  S.calScroll = Math.max(0, minute / 60 * hourH() - anchorY);
  render();
}

function render() {
  for (const c of Object.values(S.charts)) c.destroy();
  S.charts = {};
  document.querySelectorAll('.nav button').forEach((b) => b.classList.toggle('active', b.dataset.page === S.page));
  const un = unreadNotes().length, asks = S.data.notes.filter(needsAnswer).length;
  document.querySelector('.nav [data-page="notes"]').innerHTML = `Заметки${un || asks ? `<span class="badge">${un || asks}</span>` : ''}`;
  const now = new Date();
  document.getElementById('todayDate').textContent = `${now.getDate()} ${MONTHS_GEN[now.getMonth()]} ${now.getFullYear()}, ${DOW[dow(now)]}`;
  const main = document.getElementById('main');
  const scroll = main.scrollTop;
  main.innerHTML = PAGES[S.page]();
  main.scrollTop = scroll;
  document.getElementById('modal').innerHTML = detailModal();
  if (AFTER[S.page]) AFTER[S.page]();
}

// ---------- действия ----------
const val = (id) => document.getElementById(id).value.trim();
const byId = (arr, id) => arr.find((x) => x.id === id);

const CLICK = {
  'detail-open'(el) {
    openDetail(el.dataset.kind, el.dataset.id);
    return false;
  },
  'detail-close'() {
    S.detail = null;
    render();
    return false;
  },
  'detail-edit'() {
    S.detailEdit = true;
    render();
    document.getElementById('detailText').focus();
    return false;
  },
  'detail-cancel'() {
    S.detailEdit = false;
    render();
    return false;
  },
  'detail-save'() {
    const it = itemOf(S.detail.kind, S.detail.id);
    const text = document.getElementById('detailText').value.trimEnd();
    if (text) it.details = text; else delete it.details;
    S.detailEdit = false;
    return true;
  },
  'detail-done'() {
    const t = itemOf(S.detail.kind, S.detail.id);
    setStatus(t, t.status === 'done' ? 'todo' : 'done');
    return true;
  },
  'note-add'() {
    const text = document.getElementById('nnText').value.trim();
    if (!text) return false;
    const n = { id: uid(), from: 'vova', text, at: nowStamp() };
    const parent = S.replyTo && byId(S.data.notes, S.replyTo);
    if (parent) {
      n.kind = 'note';
      n.reply_to = parent.id;
      parent.answered = true;
      parent.read = true;
      n.status = 'new';  // ответ тоже доходит до ассистента
    } else {
      n.kind = val('nnKind');
      if (n.kind === 'task') n.status = 'new';
    }
    S.data.notes.push(n);
    S.replyTo = null;
    return true;
  },
  'note-reply'(el) {
    S.replyTo = el.dataset.id;
    render();
    document.getElementById('main').scrollTop = 0;
    document.getElementById('nnText').focus();
    return false;
  },
  'note-unreply'() {
    S.replyTo = null;
    render();
    return false;
  },
  'note-del'(el) {
    if (!confirm('Удалить запись?')) return false;
    S.data.notes = S.data.notes.filter((x) => x.id !== el.dataset.id);
    return true;
  },
  'task-toggle'(el) {
    const t = byId(S.data.tasks, el.dataset.id);
    setStatus(t, t.status === 'done' ? 'todo' : 'done');
    return true;
  },
  'task-add'() {
    const title = val('ntTitle');
    if (!title) return false;
    S.data.tasks.push({
      id: uid(), title, category: val('ntCat'), priority: val('ntPrio'), status: 'todo',
      due: val('ntDue'), time: val('ntTime'), created: today(),
    });
    return true;
  },
  'task-del'(el) {
    S.data.tasks = S.data.tasks.filter((x) => x.id !== el.dataset.id);
    return true;
  },
  'sched-add'() {
    const title = val('nsTitle');
    if (!title) return false;
    S.data.schedule.push({ id: uid(), day: +val('nsDay'), start: val('nsStart'), end: val('nsEnd'), title, place: val('nsPlace'), category: val('nsCat') });
    return true;
  },
  zoom(el) {
    const d = +el.dataset.d;
    if (!d) { S.hourH = null; S.calScroll = 0; render(); return false; }
    zoomAt(d > 0 ? 1.4 : 1 / 1.4, document.getElementById('calBody').clientHeight / 2);
    return false;
  },
  week(el) {
    const n = +el.dataset.d;
    S.weekStart = n ? addDays(S.weekStart, 7 * n) : monday(new Date());
    render();
    return false;
  },
  'sched-del'(el) {
    S.data.schedule = S.data.schedule.filter((x) => x.id !== el.dataset.id);
    return true;
  },
  'rem-add'() {
    const title = val('nrTitle'), repeat = val('nrRepeat');
    if (!title || !val('nrTime')) return false;
    const r = { id: uid(), title, time: val('nrTime'), repeat };
    if (repeat === 'none') r.date = val('nrDate');
    if (repeat === 'weekly') r.day = +val('nrDay');
    S.data.reminders.push(r);
    return true;
  },
  'rem-toggle'(el) {
    const r = byId(S.data.reminders, el.dataset.id);
    r.off = !r.off;
    return true;
  },
  'rem-del'(el) {
    S.data.reminders = S.data.reminders.filter((x) => x.id !== el.dataset.id);
    return true;
  },
  'test-notify'() {
    api().test_notify();
    toast('Уведомление отправлено - смотри правый нижний угол экрана');
    return false;
  },
};

function setStatus(t, status) {
  t.status = status;
  if (status === 'done') t.done_at = today();
  else delete t.done_at;
}

const CHANGE = {
  'note-filter'(el) {
    S.noteFilter = el.value;
    render();
    return false;
  },
  'task-set'(el) {
    const t = byId(S.data.tasks, el.dataset.id), f = el.dataset.f;
    if (f === 'status') setStatus(t, el.value);
    else if (f === 'title' && !el.value.trim()) return false;
    else t[f] = el.value.trim();
    return true;
  },
  filter(el) {
    S.filter[el.dataset.f] = el.value;
    if (el.dataset.f !== 'q') render();
    return false;
  },
};

document.addEventListener('click', (e) => {
  const nav = e.target.closest('.nav button');
  if (nav) { S.page = nav.dataset.page; S.calScroll = null; render(); document.getElementById('main').scrollTop = 0; return; }
  if (e.target.classList.contains('modal-bg')) { CLICK['detail-close'](); return; }
  if (e.target.closest('.go-notes')) { S.page = 'notes'; render(); document.getElementById('main').scrollTop = 0; return; }
  const el = e.target.closest('[data-act]');
  if (el && el.tagName === 'BUTTON' && CLICK[el.dataset.act] && CLICK[el.dataset.act](el)) commit();
});
// двойной клик по блоку календаря или делу - подробности
document.addEventListener('dblclick', (e) => {
  if (e.target.closest('button, input, select, textarea, .modal')) return;
  const el = e.target.closest('[data-kind][data-id]');
  if (el && DETAIL_LIST[el.dataset.kind]) openDetail(el.dataset.kind, el.dataset.id);
});
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-act]');
  if (el && CHANGE[el.dataset.act] && CHANGE[el.dataset.act](el)) commit();
});
document.addEventListener('input', (e) => {
  const el = e.target;
  if (el.dataset.act === 'filter' && el.dataset.f === 'q') {
    S.filter.q = el.value;
    const pos = el.selectionStart;
    render();
    const again = document.querySelector('[data-act="filter"][data-f="q"]');
    again.focus();
    again.setSelectionRange(pos, pos);
  }
  if (el.id === 'nrRepeat') {
    document.getElementById('nrDate').style.display = el.value === 'none' ? '' : 'none';
    document.getElementById('nrDay').style.display = el.value === 'weekly' ? '' : 'none';
  }
});
// окно поменяло размер - календарь заново подгоняется по высоте и ширине
window.addEventListener('resize', () => {
  clearTimeout(window.__rs);
  window.__rs = setTimeout(() => { if (S.data && S.page === 'schedule') render(); }, 150);
});

// Enter в поле ввода = кнопка "Добавить" рядом
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && S.detail) { CLICK[S.detailEdit ? 'detail-cancel' : 'detail-close'](); return; }
  if (e.key === 'Enter' && e.ctrlKey && e.target.id === 'detailText') { CLICK['detail-save']() && commit(); return; }
  if (e.key === 'Enter' && e.ctrlKey && e.target.id === 'nnText') { document.querySelector('[data-act="note-add"]').click(); return; }
  if (e.key !== 'Enter' || !e.target.matches('.form input')) return;
  const btn = e.target.closest('.form').querySelector('.btn[data-act]');
  if (btn) btn.click();
});

// ---------- старт ----------
window.addEventListener('pywebviewready', async () => {
  const now = new Date();
  S.weekStart = monday(now);
  if (!(await load())) {
    document.getElementById('main').innerHTML = '<div class="loading">data.json не читается - проверь, что файл не повреждён.</div>';
    return;
  }
  render();
  setInterval(poll, 2000);
  // раз в минуту обновляем экран: смена дня, просрочка по времени
  setInterval(() => {
    const a = document.activeElement;
    if (!(a && a.matches('input, select, textarea'))) render();
  }, 60000);
});
