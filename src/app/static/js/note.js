// S5 노트 보기. GET/DELETE /api/notes/{id} (F3)
import { api, dateKst, el, errorMessage } from './common.js';
import { renderMarkdown } from './markdown.js';

const KIND_LABEL = { remember: '기억할 것', debug: '디버깅', review: '후기' };

const root = document.getElementById('s5');
const noteId = root.dataset.noteId;
const url = '/api/notes/' + noteId;
const title = document.getElementById('s5-title');
const meta = document.getElementById('note-view-meta');
const dates = document.getElementById('note-view-dates');
const body = document.getElementById('note-view-body');
const actions = document.getElementById('note-view-actions');
const errorBox = document.getElementById('note-view-error');
const backLink = document.getElementById('note-back');
const deleteBtn = document.getElementById('note-delete-btn');
let note = null;

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function render(n) {
  title.textContent = n.title;
  document.title = n.title + ' - Study Log';
  backLink.href = '/subjects/' + n.subject_id;
  meta.replaceChildren(el('span', 'badge-kind', KIND_LABEL[n.kind]));
  for (const tag of n.tags) meta.appendChild(el('span', 'tag', tag));
  if (n.is_open) meta.appendChild(el('span', 'badge-open', '미해결'));
  dates.replaceChildren(
    el('span', '', '작성 ' + dateKst(n.created_at)),
    el('span', '', '수정 ' + dateKst(n.updated_at)),
  );
  renderMarkdown(body, n.body);
  actions.hidden = false;
}

async function load() {
  const res = await api('GET', url);
  if (res.status === 404) {
    title.textContent = '노트를 찾을 수 없습니다';
    return;
  }
  if (!res.ok) {
    title.textContent = '노트를 불러오지 못했습니다';
    showError(errorMessage(res, '노트를 불러오지 못했습니다'));
    return;
  }
  note = res.data;
  render(note);
}

deleteBtn.addEventListener('click', async () => {
  if (!confirm('이 노트를 삭제할까요?')) return;
  errorBox.hidden = true;
  deleteBtn.disabled = true;
  const res = await api('DELETE', url);
  deleteBtn.disabled = false;
  if (!res.ok && res.status !== 404) {
    showError(errorMessage(res, '삭제하지 못했습니다'));
    return;
  }
  // 404는 이미 없는 노트이므로 삭제된 것과 같다.
  location.href = '/subjects/' + note.subject_id;
});

load();
