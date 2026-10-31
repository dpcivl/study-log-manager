// S3 공부 시간 섹션. GET/POST /api/subjects/{id}/sessions, PATCH/DELETE /api/sessions/{id} (F2)
import { api, clearErrors, el, errorMessage, formatHours, showErrors, todayKst } from './common.js';

const PAGE_SIZE = 20;

// "10월 31일". 올해가 아니면 연도를 앞에 붙인다.
function formatDay(date) {
  const text = Number(date.slice(5, 7)) + '월 ' + Number(date.slice(8, 10)) + '일';
  return date.slice(0, 4) === todayKst().slice(0, 4) ? text : date.slice(0, 4) + '년 ' + text;
}

// 입력 칸의 값을 API 요청 값으로 바꾼다. 검증은 서버가 한다(빈 칸은 null → 422).
function minutesValue(input) {
  return input.value === '' ? null : Number(input.value);
}

// onChange: 기록이 바뀐 뒤 부르는 함수(S3 요약 줄을 다시 불러온다).
export function initSessions(subjectId, onChange) {
  const section = document.getElementById('sessions');
  const form = document.getElementById('session-form');
  const submitBtn = form.querySelector('button[type="submit"]');
  const list = document.getElementById('session-list');
  const listError = document.getElementById('session-list-error');
  const moreBtn = document.getElementById('session-more');
  const dateInput = document.getElementById('session-date');
  const minutesInput = document.getElementById('session-minutes');
  const memoInput = document.getElementById('session-memo');
  const listUrl = '/api/subjects/' + subjectId + '/sessions';

  let items = []; // 지금까지 불러온 기록(날짜 최신순)
  let total = 0;
  let pages = 0; // 불러온 쪽 수
  let loadSeq = 0; // 오래된 응답이 새 응답을 덮지 않게 한다

  function showListError(res, fallback) {
    listError.textContent = errorMessage(res, fallback);
    listError.hidden = false;
  }

  function renderRow(li, s) {
    li.replaceChildren();
    li.appendChild(el('span', 'date', formatDay(s.studied_on))).title = s.studied_on;
    li.appendChild(el('span', 'dur', formatHours(s.minutes)));
    li.appendChild(el('span', 'memo', s.memo));
    const edit = el('button', 'btn btn-secondary', '수정');
    edit.type = 'button';
    edit.addEventListener('click', () => renderEditRow(li, s));
    const del = el('button', 'btn btn-secondary', '삭제');
    del.type = 'button';
    del.addEventListener('click', async () => {
      del.disabled = true;
      const res = await api('DELETE', '/api/sessions/' + s.id);
      del.disabled = false;
      if (!res.ok && res.status !== 404) {
        let p = li.querySelector('.form-error');
        if (!p) p = li.appendChild(el('p', 'form-error'));
        p.setAttribute('role', 'alert');
        p.textContent = errorMessage(res, '삭제하지 못했습니다');
        return;
      }
      await reload(); // 404는 이미 없는 기록이므로 목록을 새로 불러와 맞춘다
      onChange();
    });
    const actions = el('div', 'record-actions');
    actions.append(edit, del);
    li.appendChild(actions);
  }

  // "수정": 그 행이 날짜·시간(분)·메모 입력과 "저장" "취소" 버튼으로 바뀐다.
  function renderEditRow(li, s) {
    li.replaceChildren();
    const row = el('form', 'record-edit');
    row.noValidate = true; // 값 검증은 서버가 한다. 15의 배수가 아닌 분도 받는다
    const fields = [
      ['studied_on', 'date', s.studied_on, '날짜', 'field'],
      ['minutes', 'number', String(s.minutes), '시간 (분)', 'field'],
      ['memo', 'text', s.memo, '메모', 'field field-memo'],
    ];
    for (const [name, type, value, label, cls] of fields) {
      const box = el('div', cls);
      const input = el('input', 'input');
      input.type = type;
      input.name = name;
      input.value = value;
      input.setAttribute('aria-label', label);
      if (name === 'minutes') input.step = 15;
      if (name === 'memo') input.maxLength = 500;
      const error = el('p', 'form-error');
      error.setAttribute('role', 'alert');
      error.dataset.errorFor = name;
      error.hidden = true;
      box.append(input, error);
      row.appendChild(box);
    }
    const general = el('p', 'form-error');
    general.setAttribute('role', 'alert');
    general.dataset.errorFor = 'form';
    general.hidden = true;
    const actions = el('div', 'form-actions');
    const save = el('button', 'btn btn-primary', '저장');
    save.type = 'submit';
    const cancel = el('button', 'btn btn-secondary', '취소');
    cancel.type = 'button';
    cancel.addEventListener('click', () => renderRow(li, s));
    actions.append(save, cancel);
    row.append(general, actions);
    row.addEventListener('submit', async (event) => {
      event.preventDefault();
      clearErrors(row);
      save.disabled = true;
      const res = await api('PATCH', '/api/sessions/' + s.id, {
        studied_on: row.elements.studied_on.value,
        minutes: minutesValue(row.elements.minutes),
        memo: row.elements.memo.value,
      });
      save.disabled = false;
      if (!res.ok) {
        showErrors(row, res, '저장하지 못했습니다');
        return;
      }
      await reload();
      onChange();
    });
    li.appendChild(row);
    row.elements.studied_on.focus();
  }

  function appendRows(newItems) {
    for (const s of newItems) {
      const li = el('li', 'record');
      renderRow(li, s);
      list.appendChild(li);
    }
  }

  function renderList() {
    list.replaceChildren();
    appendRows(items);
    moreBtn.hidden = items.length >= total;
  }

  // 지금 보이는 쪽 수만큼 처음부터 다시 불러와 목록을 맞춘다.
  async function reload() {
    const seq = ++loadSeq;
    const count = Math.max(pages, 1);
    let all = [];
    let newTotal = 0;
    for (let page = 1; page <= count; page++) {
      const res = await api('GET', listUrl + '?page=' + page + '&limit=' + PAGE_SIZE);
      if (seq !== loadSeq) return;
      if (!res.ok) {
        showListError(res, '공부 기록을 불러오지 못했습니다');
        return;
      }
      all = all.concat(res.data.items);
      newTotal = res.data.total;
      if (all.length >= newTotal) {
        pages = page;
        break;
      }
      pages = page;
    }
    listError.hidden = true;
    items = all;
    total = newTotal;
    renderList();
  }

  moreBtn.addEventListener('click', async () => {
    moreBtn.disabled = true;
    const seq = loadSeq;
    const res = await api('GET', listUrl + '?page=' + (pages + 1) + '&limit=' + PAGE_SIZE);
    moreBtn.disabled = false;
    if (seq !== loadSeq) return; // 그 사이 목록이 새로 불러와졌다
    if (!res.ok) {
      showListError(res, '공부 기록을 더 불러오지 못했습니다');
      return;
    }
    listError.hidden = true;
    const known = new Set(items.map((s) => s.id));
    const fresh = res.data.items.filter((s) => !known.has(s.id));
    pages += 1;
    items = items.concat(fresh);
    total = res.data.total;
    appendRows(fresh);
    moreBtn.hidden = items.length >= total;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearErrors(form);
    submitBtn.disabled = true;
    const res = await api('POST', listUrl, {
      studied_on: dateInput.value,
      minutes: minutesValue(minutesInput),
      memo: memoInput.value,
    });
    submitBtn.disabled = false;
    if (!res.ok) {
      showErrors(form, res, '추가하지 못했습니다');
      return;
    }
    memoInput.value = '';
    await reload();
    onChange();
  });

  dateInput.value = todayKst();
  section.hidden = false;
  reload();
}
