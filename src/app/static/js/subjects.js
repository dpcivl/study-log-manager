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

// 로그아웃(F11). 성공하면 S1로, 실패하면 S2에 머물며 문구를 보인다. 입력 중인 내용은 그대로 둔다.
const logoutBtn = document.getElementById('logout-btn');
const logoutError = document.getElementById('logout-error');
logoutBtn.addEventListener('click', async () => {
  if (logoutBtn.disabled) return;
  logoutBtn.disabled = true;
  logoutError.hidden = true; // 다시 누르면 지난 문구를 지운다
  const res = await api('POST', '/api/logout');
  if (res.ok) {
    location.href = '/login'; // 이동이 끝날 때까지 버튼을 꺼 둔다
    return;
  }
  logoutBtn.disabled = false;
  logoutError.hidden = false;
});

// 이동한 뒤 뒤로 가기로 bfcache에서 복원되면 스크립트가 다시 돌지 않으므로 여기서 버튼을 다시 켠다.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) logoutBtn.disabled = false;
});

load();
