// S4 노트 편집(작성·수정 공용). POST /api/subjects/{id}/notes, GET/PATCH /api/notes/{id} (F3)
import { api, clearErrors, errorMessage, showErrors } from './common.js';
import { renderMarkdown } from './markdown.js';

const DEBUG_TEMPLATE = '## 문제상황\n\n## 원인\n\n## 해결\n';

const root = document.getElementById('s4');
const noteId = root.dataset.noteId || null; // null이면 작성, 있으면 그 노트를 수정
let subjectId = root.dataset.subjectId || null;
const form = document.getElementById('note-form');
const loadError = document.getElementById('note-load-error');
const heading = document.getElementById('s4-title');
const titleInput = document.getElementById('note-title');
const tagsInput = document.getElementById('note-tags');
const openInput = document.getElementById('note-open');
const bodyInput = document.getElementById('note-body');
const preview = document.getElementById('note-preview');
const previewToggle = document.getElementById('preview-toggle');
const counter = document.getElementById('body-counter');
const submitBtn = form.querySelector('button[type="submit"]');
const kindRadios = form.querySelectorAll('input[name="kind"]');

function updateCounter() {
  counter.textContent = bodyInput.value.length.toLocaleString('en-US') + ' / 50,000자';
}

// 미리보기에서 편집 모드로 되돌린다.
function showEditor() {
  bodyInput.hidden = false;
  preview.hidden = true;
  previewToggle.setAttribute('aria-pressed', 'false');
  previewToggle.textContent = '미리보기';
}

function setCancelTarget(href) {
  document.getElementById('note-cancel').href = href;
  document.getElementById('note-cancel-top').href = href;
}

function selectedKind() {
  return form.querySelector('input[name="kind"]:checked').value;
}

function fill(n) {
  for (const r of kindRadios) r.checked = r.value === n.kind;
  titleInput.value = n.title;
  tagsInput.value = n.tags.join(', ');
  openInput.checked = n.is_open;
  bodyInput.value = n.body;
  updateCounter();
}

// 쉼표로 나누고 앞뒤 공백을 지운다. 쉼표 사이가 빈 항목은 버린다. 소문자 변환·중복 제거는 서버가 한다.
function parseTags(text) {
  return text.split(',').map((t) => t.trim()).filter((t) => t !== '');
}

// 디버깅을 골랐고 본문이 비어 있으면 템플릿을 넣는다. 본문이 있으면 덮어쓰지 않는다.
for (const r of kindRadios) {
  r.addEventListener('change', () => {
    if (r.checked && r.value === 'debug' && bodyInput.value.trim() === '') {
      bodyInput.value = DEBUG_TEMPLATE;
      updateCounter();
    }
  });
}

bodyInput.addEventListener('input', updateCounter);

previewToggle.addEventListener('click', () => {
  if (bodyInput.hidden) {
    showEditor();
    return;
  }
  bodyInput.hidden = true;
  preview.hidden = false;
  previewToggle.setAttribute('aria-pressed', 'true');
  previewToggle.textContent = '편집';
  renderMarkdown(preview, bodyInput.value);
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearErrors(form);
  submitBtn.disabled = true;
  // 검증은 서버가 한다. 제목·본문은 입력한 그대로 보낸다.
  const payload = {
    kind: selectedKind(),
    title: titleInput.value,
    body: bodyInput.value,
    tags: parseTags(tagsInput.value),
    is_open: openInput.checked,
  };
  const res = noteId
    ? await api('PATCH', '/api/notes/' + noteId, payload)
    : await api('POST', '/api/subjects/' + subjectId + '/notes', payload);
  if (!res.ok) {
    // 실패했을 때만 버튼을 다시 켠다. 성공하면 이동이 끝날 때까지 꺼 둬 연타로 두 번 저장되지 않게 한다.
    submitBtn.disabled = false;
    // 미리보기 중이면 오류 문구와 입력 칸이 보이도록 편집 모드로 돌아온다.
    showEditor();
    showErrors(form, res, '저장하지 못했습니다');
    return;
  }
  location.href = '/notes/' + res.data.id;
});

// 저장에 성공하면 버튼을 끈 채로 페이지를 떠난다. 뒤로 가기로 bfcache에서 복원되면 스크립트가 다시 돌지 않으므로 여기서 다시 켠다.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) submitBtn.disabled = false;
});

async function init() {
  updateCounter();
  if (!noteId) return;
  heading.textContent = '노트 수정';
  const res = await api('GET', '/api/notes/' + noteId);
  if (!res.ok) {
    loadError.textContent =
      res.status === 404 ? '노트를 찾을 수 없습니다' : errorMessage(res, '노트를 불러오지 못했습니다');
    loadError.hidden = false;
    return;
  }
  subjectId = String(res.data.subject_id);
  fill(res.data);
  setCancelTarget('/notes/' + noteId); // 취소: 수정이면 S5
  form.hidden = false;
  titleInput.focus();
}

init();
