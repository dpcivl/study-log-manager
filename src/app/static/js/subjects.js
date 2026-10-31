// S2 주제 목록. GET/POST /api/subjects (F1)
import { api, clearErrors, dday, el, errorMessage, formatHours, showErrors, todayKst } from './common.js';

const list = document.getElementById('topic-list');
const empty = document.getElementById('topic-empty');
const loadError = document.getElementById('topic-load-error');
const form = document.getElementById('topic-form');
const newBtn = document.getElementById('new-topic-btn');
const submitBtn = form.querySelector('button[type="submit"]');
let subjects = [];

function render() {
  list.replaceChildren();
  for (const sub of subjects) {
    const li = el('li');
    const a = el('a', 'topic-card');
    a.href = '/subjects/' + sub.id;
    a.appendChild(el('h2', '', sub.name));
    const meta = el('p', 'topic-meta');
    meta.appendChild(el('span', '', '시작일 ' + sub.started_on));
    if (sub.target_date) meta.appendChild(el('span', '', dday(sub.target_date)));
    a.appendChild(meta);
    const stats = el('div', 'topic-stats');
    stats.appendChild(el('span', 'hours', formatHours(sub.total_minutes)));
    stats.appendChild(el('span', '', '노트 ' + sub.note_count));
    if (sub.open_note_count > 0) stats.appendChild(el('span', 'badge-open', '미해결 ' + sub.open_note_count));
    a.appendChild(stats);
    li.appendChild(a);
    list.appendChild(li);
  }
  empty.hidden = subjects.length > 0 || !loadError.hidden;
}

async function load() {
  const res = await api('GET', '/api/subjects');
  if (!res.ok) {
    loadError.textContent = errorMessage(res, '주제 목록을 불러오지 못했습니다');
    loadError.hidden = false;
    render();
    return;
  }
  loadError.hidden = true;
  subjects = res.data.items;
  render();
}

function toggleForm(open) {
  form.hidden = !open;
  clearErrors(form);
  newBtn.setAttribute('aria-expanded', String(open));
  if (open) {
    form.reset();
    document.getElementById('topic-started').value = todayKst();
    document.getElementById('topic-name').focus();
  }
}

newBtn.addEventListener('click', () => toggleForm(form.hidden));
document.getElementById('topic-cancel').addEventListener('click', () => toggleForm(false));

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  submitBtn.disabled = true;
  // 검증은 서버가 한다. 값은 입력한 그대로 보낸다(빈 목표일만 null).
  const res = await api('POST', '/api/subjects', {
    name: document.getElementById('topic-name').value,
    background: document.getElementById('topic-background').value,
    started_on: document.getElementById('topic-started').value,
    target_date: document.getElementById('topic-target').value || null,
  });
  submitBtn.disabled = false;
  if (!res.ok) {
    showErrors(form, res, '주제를 만들지 못했습니다');
    return;
  }
  subjects.unshift(res.data);
  toggleForm(false);
  render();
});

document.getElementById('logout-btn').addEventListener('click', async () => {
  await api('POST', '/api/logout');
  location.href = '/login';
});

load();
