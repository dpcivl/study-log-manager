// S3 노트 섹션의 필터 바와 목록. GET /api/subjects/{id}/notes (F4)
import { api, dateKst, el, errorMessage } from './common.js';

const PAGE_SIZE = 20;
const SEARCH_DELAY_MS = 300;
const KIND_LABEL = { remember: '기억할 것', debug: '디버깅', review: '후기' };
const KIND_TABS = [['', '전체'], ['remember', KIND_LABEL.remember], ['debug', KIND_LABEL.debug], ['review', KIND_LABEL.review]];

export function initNotes(subjectId) {
  const section = document.getElementById('notes');
  const kindTabs = document.getElementById('kind-tabs');
  const openOnly = document.getElementById('open-only');
  const tagChips = document.getElementById('tag-chips');
  const searchInput = document.getElementById('note-search');
  const list = document.getElementById('note-list');
  const listError = document.getElementById('note-list-error');
  const empty = document.getElementById('note-empty');
  const moreBtn = document.getElementById('note-more');
  const listUrl = '/api/subjects/' + subjectId + '/notes';

  let kind = ''; // '' = 전체
  let selectedTags = [];
  let knownTags = null; // 마지막 응답의 tags(칩을 다시 만들지 판단하는 데 쓴다)
  let items = []; // 지금까지 불러온 노트(수정 최신순)
  let total = 0;
  let page = 0; // 불러온 쪽 수
  let loadSeq = 0; // 필터를 바꿔 다시 부를 때마다 올린다. 오래된 응답은 버린다
  let loading = false; // 첫 쪽부터 다시 부르는 중
  let searchTimer = null;

  function query(pageNumber) {
    const params = new URLSearchParams();
    if (kind) params.set('kind', kind);
    for (const t of selectedTags) params.append('tag', t);
    const q = searchInput.value.trim();
    if (q) params.set('q', q);
    if (openOnly.checked) params.set('open', 'true');
    params.set('page', String(pageNumber));
    params.set('limit', String(PAGE_SIZE));
    return listUrl + '?' + params.toString();
  }

  function showListError(res, fallback) {
    listError.textContent = errorMessage(res, fallback);
    listError.hidden = false;
  }

  function renderKindTabs() {
    if (!kindTabs.children.length) {
      for (const [value, label] of KIND_TABS) {
        const b = el('button', 'tab', label);
        b.type = 'button';
        b.dataset.kind = value;
        b.addEventListener('click', () => {
          kind = value;
          renderKindTabs();
          reload();
        });
        kindTabs.appendChild(b);
      }
    }
    for (const b of kindTabs.children) b.setAttribute('aria-pressed', String(b.dataset.kind === kind));
  }

  // 태그 칩. 태그 목록이 그대로면 버튼을 다시 만들지 않아 키보드 초점을 지킨다.
  function renderTagChips(tags) {
    const same = knownTags && knownTags.length === tags.length && knownTags.every((t, i) => t === tags[i]);
    if (!same) {
      tagChips.replaceChildren();
      for (const t of tags) {
        const b = el('button', 'chip', t);
        b.type = 'button';
        b.addEventListener('click', () => {
          const i = selectedTags.indexOf(t);
          if (i >= 0) selectedTags.splice(i, 1);
          else selectedTags.push(t);
          renderTagChips(tags);
          reload();
        });
        tagChips.appendChild(b);
      }
      knownTags = tags;
    }
    for (const b of tagChips.children) {
      b.setAttribute('aria-pressed', String(selectedTags.includes(b.textContent)));
    }
  }

  function renderItem(n) {
    const li = el('li');
    const a = el('a', 'note-item');
    a.href = '/notes/' + n.id;
    a.appendChild(el('h3', '', n.title));
    const meta = el('div', 'note-meta');
    meta.appendChild(el('span', 'badge-kind', KIND_LABEL[n.kind] || n.kind));
    for (const t of n.tags) meta.appendChild(el('span', 'tag', t));
    if (n.is_open) meta.appendChild(el('span', 'badge-open', '미해결'));
    meta.appendChild(el('span', '', dateKst(n.updated_at)));
    a.appendChild(meta);
    li.appendChild(a);
    return li;
  }

  function renderList() {
    list.replaceChildren(...items.map(renderItem));
    empty.hidden = items.length > 0;
    moreBtn.hidden = items.length >= total;
  }

  // 필터가 바뀌면 첫 쪽부터 다시 부른다. 가장 나중에 보낸 요청의 응답만 그린다.
  async function reload() {
    clearTimeout(searchTimer);
    const seq = ++loadSeq;
    loading = true;
    moreBtn.disabled = true;
    // 선택한 태그가 사라졌으면(노트가 바뀌어 주제에서 없어짐) 선택에서 빼고 다시 부른다.
    for (;;) {
      const res = await api('GET', query(1));
      if (seq !== loadSeq) return;
      if (!res.ok) {
        loading = false;
        // 목록은 이전 필터 결과라 비우고, 더 보기와 빈 결과 문구도 숨겨 오류 문구만 남긴다.
        items = [];
        total = 0;
        page = 0;
        list.replaceChildren();
        moreBtn.hidden = true;
        empty.hidden = true;
        moreBtn.disabled = false;
        showListError(res, '노트를 불러오지 못했습니다');
        return;
      }
      const tags = res.data.tags;
      const kept = selectedTags.filter((t) => tags.includes(t));
      if (kept.length !== selectedTags.length) {
        selectedTags = kept;
        continue;
      }
      listError.hidden = true;
      items = res.data.items;
      total = res.data.total;
      page = 1;
      renderTagChips(tags);
      renderList();
      loading = false;
      moreBtn.disabled = false;
      return;
    }
  }

  moreBtn.addEventListener('click', async () => {
    if (loading) return;
    const seq = loadSeq;
    moreBtn.disabled = true;
    const res = await api('GET', query(page + 1));
    if (seq !== loadSeq) return; // 그 사이 필터가 바뀌어 첫 쪽부터 다시 불러오는 중이다
    moreBtn.disabled = false;
    if (!res.ok) {
      showListError(res, '노트를 더 불러오지 못했습니다');
      return;
    }
    listError.hidden = true;
    const known = new Set(items.map((n) => n.id));
    const fresh = res.data.items.filter((n) => !known.has(n.id));
    page += 1;
    items = items.concat(fresh);
    total = res.data.total;
    for (const n of fresh) list.appendChild(renderItem(n));
    moreBtn.hidden = items.length >= total;
  });

  openOnly.addEventListener('change', reload);
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(reload, SEARCH_DELAY_MS);
  });

  renderKindTabs();
  section.hidden = false;
  reload();
}
