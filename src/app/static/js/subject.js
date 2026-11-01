// S3 주제 상세의 헤더·요약·편집. GET/PATCH /api/subjects/{id} (F1)
import { api, clearErrors, dday, el, errorMessage, formatHours, showErrors } from './common.js';
import { initExport } from './export.js';
import { initNotes } from './notes.js';
import { initSessions } from './sessions.js';

const root = document.getElementById('s3');
const subjectId = root.dataset.subjectId;
const url = '/api/subjects/' + subjectId;
const title = document.getElementById('s3-title');
const summary = document.getElementById('subject-summary');
const background = document.getElementById('subject-background');
const summaryError = document.getElementById('summary-error');
const loadError = document.getElementById('subject-load-error');
const editBtn = document.getElementById('subject-edit-btn');
const form = document.getElementById('subject-edit-form');
const submitBtn = form.querySelector('button[type="submit"]');
let subject = null;
let summarySeq = 0;

function renderSummary(sub) {
  summaryError.hidden = true; // 서버 값으로 다시 그렸으니 갱신 실패 문구는 사라진다
  title.textContent = sub.name;
  document.title = sub.name + ' - Study Log';
  summary.replaceChildren();
  const parts = [sub.started_on + ' ~ ' + (sub.target_date || '목표일 없음')];
  if (sub.target_date) parts.push(dday(sub.target_date));
  for (const text of parts) summary.appendChild(el('span', '', text));
  for (const [label, value] of [
    ['누적 ', formatHours(sub.total_minutes)],
    ['최근 7일 ', formatHours(sub.last7_minutes)],
    ['공부한 날 ', sub.days_studied + '일'],
  ]) {
    const s = el('span', '', label);
    s.appendChild(el('strong', '', value));
    summary.appendChild(s);
  }
  background.textContent = sub.background;
  background.hidden = !sub.background;
}

async function load() {
  const res = await api('GET', url);
  if (!res.ok) {
    loadError.textContent = errorMessage(res, '주제를 불러오지 못했습니다');
    loadError.hidden = false;
    return;
  }
  subject = res.data;
  editBtn.hidden = false;
  renderSummary(subject);
  initSessions(subjectId, refreshSummary); // F2 공부 시간 섹션
  initExport(subjectId); // F6 내보내기 버튼
  initNotes(subjectId); // F3 새 노트 링크, F4 노트 필터·목록
}

// 공부 기록이 바뀐 뒤 요약 줄(누적, 최근 7일, 공부한 날)을 서버 값으로 다시 맞춘다.
async function refreshSummary() {
  const seq = ++summarySeq;
  const res = await api('GET', url);
  if (seq !== summarySeq) return; // 더 나중에 시작한 갱신이 결과를 정한다
  if (!res.ok) {
    summaryError.hidden = false; // 기록은 바뀌었지만 요약은 옛 값 그대로다. 다음에 성공하면 사라진다
    return;
  }
  subject = res.data;
  renderSummary(subject);
}

editBtn.addEventListener('click', () => {
  clearErrors(form);
  document.getElementById('edit-name').value = subject.name;
  document.getElementById('edit-started').value = subject.started_on;
  document.getElementById('edit-target').value = subject.target_date || '';
  document.getElementById('edit-background').value = subject.background;
  form.hidden = false;
  document.getElementById('edit-name').focus();
});

document.getElementById('subject-edit-cancel').addEventListener('click', () => {
  form.hidden = true;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  submitBtn.disabled = true;
  // 검증은 서버가 한다. 값은 입력한 그대로 보낸다(빈 목표일은 null = 목표일 지우기).
  const res = await api('PATCH', url, {
    name: document.getElementById('edit-name').value,
    started_on: document.getElementById('edit-started').value,
    target_date: document.getElementById('edit-target').value || null,
    background: document.getElementById('edit-background').value,
  });
  submitBtn.disabled = false;
  if (!res.ok) {
    showErrors(form, res, '저장하지 못했습니다');
    return;
  }
  subject = res.data;
  renderSummary(subject);
  form.hidden = true;
});

load();
