// 노트 초안(F8). 브라우저 localStorage에만 둔다. 서버에는 보내지 않는다.
// 키는 작성이면 draft:new:{subject_id}, 수정이면 draft:note:{note_id}.
// 모든 localStorage 접근은 try/catch로 감싼다. 못 쓰면 초안 없이 작성을 계속한다.
// 초안은 노트 내용을 평문으로 담으므로 저장 성공과 로그아웃에서 지운다.

export const DRAFT_DELAY_MS = 1000; // 입력이 멈추고 이 시간 뒤에 쓴다
export const DISCARD_CONFIRM = '저장하지 않은 내용을 버릴까요?';

const KEY_PREFIX = 'draft:';
const KINDS = ['remember', 'debug', 'review'];

export function draftKey(noteId, subjectId) {
  return noteId ? KEY_PREFIX + 'note:' + noteId : KEY_PREFIX + 'new:' + subjectId;
}

export function removeDraft(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    // 저장소를 못 쓰면 지울 것도 없다
  }
}

// 로그아웃에 성공하면 draft:로 시작하는 키를 모두 지운다.
export function clearAllDrafts() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key !== null && key.startsWith(KEY_PREFIX)) keys.push(key);
    }
    for (const key of keys) localStorage.removeItem(key);
  } catch {
    // 무시
  }
}

// 초안을 읽는다. 없으면 null. JSON 해석에 실패했거나 모양이 아니면 지우고 없는 것으로 본다.
// 돌려주는 kind가 enum 밖이면 null이다(복원할 때 지금 고른 유형을 그대로 둔다).
export function readDraft(key) {
  let raw;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return null;
  }
  if (raw === null) return null;
  let d;
  try {
    d = JSON.parse(raw);
  } catch {
    d = null;
  }
  if (d === null || typeof d !== 'object' || Array.isArray(d) || typeof d.title !== 'string' || typeof d.body !== 'string') {
    removeDraft(key);
    return null;
  }
  return {
    kind: KINDS.includes(d.kind) ? d.kind : null,
    title: d.title,
    tags_text: typeof d.tags_text === 'string' ? d.tags_text : '',
    is_open: d.is_open === true,
    body: d.body,
    base_updated_at: typeof d.base_updated_at === 'string' ? d.base_updated_at : null,
    saved_at: typeof d.saved_at === 'string' ? d.saved_at : null,
  };
}

// 저장 시각(ISO 8601 UTC)을 KST "YYYY-MM-DD HH:MM"으로. 해석할 수 없으면 빈 문자열이다.
function formatSavedAt(iso) {
  const ms = iso === null ? NaN : Date.parse(iso);
  if (!Number.isFinite(ms)) return '';
  return new Date(ms + 9 * 3600 * 1000).toISOString().slice(0, 16).replace('T', ' ');
}

function sameValues(a, b) {
  return (
    a.kind === b.kind && a.title === b.title && a.tags_text === b.tags_text && a.is_open === b.is_open && a.body === b.body
  );
}

// S4의 초안 보관. 화면 쪽은 값을 읽고 쓰는 방법만 알려 준다.
// opts: { noteId, subjectId, snapshot(): {kind,title,tags_text,is_open,body}, apply(values): 입력 칸에 값으로 넣는다,
//         elements: { banner, bannerText, restore, discard, unavailable, form }, leaveLinks: [a, ...] }
// 돌려주는 값: { start(baseUpdatedAt), flush(), flushForSave(), stop(), markSaved(), hasChanges() }
export function createDraftSession(opts) {
  const { noteId, snapshot, apply, elements, leaveLinks } = opts;
  const key = () => draftKey(noteId, opts.subjectId());
  let loadedValues = null; // 마지막으로 불러오거나 저장한 값. null이면 아직 시작 전이다
  let baseUpdatedAt = null;
  let active = false; // 시작했고 아직 이탈 중이 아니다
  let touched = false; // 시작한 뒤 사용자가 입력을 건드렸다
  let pending = null; // 안내 줄이 보여 주는 초안
  let timer = null;
  let warned = false;

  const hasChanges = () => loadedValues !== null && !sameValues(snapshot(), loadedValues);

  function warnUnavailable() {
    if (warned) return;
    warned = true;
    elements.unavailable.hidden = false;
  }

  function write() {
    // 입력을 건드리지 않았으면 쓰지 않는다. 안내 줄이 떠 있는 동안에는 고르지 않은 초안을 덮어쓰지 않으니
    // 입력 타이머, pagehide 같은 경로에서는 쓰지 않는다. "복원"이나 "버리기"를 누른 뒤부터 쓴다.
    // 저장 버튼은 지금 입력을 고른 것이므로 flushForSave()가 안내 줄을 먼저 닫는다.
    if (!active || !touched || pending !== null) return;
    const d = {
      ...snapshot(),
      base_updated_at: baseUpdatedAt,
      saved_at: new Date().toISOString().replace(/\.\d+Z$/, 'Z'),
    };
    try {
      localStorage.setItem(key(), JSON.stringify(d));
    } catch {
      warnUnavailable(); // 저장소를 못 쓰거나 용량이 부족하다. 초안 없이 계속 쓴다
    }
  }

  function flush() {
    clearTimeout(timer);
    timer = null;
    write();
  }

  function hideBanner() {
    pending = null;
    elements.banner.hidden = true;
  }

  // "저장"을 눌렀다. 저장은 지금 입력을 고른 것으로 본다.
  // 입력을 건드렸으면 안내 줄을 닫고(고르지 않은 초안의 대기를 끝내고) 지금 입력을 초안에 바로 쓴다.
  // 건드리지 않았으면 초안을 그대로 둔다. 저장이 실패해도 입력과 초안은 남는다.
  function flushForSave() {
    if (active && touched && pending !== null) hideBanner();
    flush();
  }

  // 더 이상 초안을 쓰지 않고 이탈 경고도 띄우지 않는다. 저장 성공, 세션 만료, 확인한 이탈에서 쓴다.
  function stop() {
    clearTimeout(timer);
    timer = null;
    active = false;
  }

  // 불러온(또는 새로 연) 입력을 기준값으로 삼고, 남은 초안이 있으면 안내 줄을 보인다.
  function start(base) {
    clearTimeout(timer);
    loadedValues = snapshot();
    baseUpdatedAt = base;
    active = true;
    touched = false;
    hideBanner();
    elements.unavailable.hidden = true;
    warned = false;
    const d = readDraft(key());
    if (d === null) return;
    const compare = { ...d, kind: d.kind === null ? loadedValues.kind : d.kind };
    const show =
      noteId === null || noteId === ''
        ? d.title !== '' || d.body !== '' || d.tags_text !== '' || d.is_open // 작성: 내용이 있을 때
        : !sameValues(compare, loadedValues); // 수정: 불러온 노트와 다를 때
    if (!show) {
      removeDraft(key()); // 같으면 조용히 지운다
      return;
    }
    pending = d;
    const when = formatSavedAt(d.saved_at);
    elements.bannerText.textContent = '저장하지 않은 초안이 있습니다' + (when ? ' (' + when + ')' : '');
    elements.banner.hidden = false;
  }

  // 저장에 성공했다. 초안을 지우고 쓰기를 멈춘다.
  function markSaved() {
    stop();
    removeDraft(key());
  }

  elements.restore.addEventListener('click', () => {
    const d = pending;
    if (d === null) return;
    apply({ ...d, kind: d.kind === null ? snapshot().kind : d.kind });
    baseUpdatedAt = d.base_updated_at;
    hideBanner();
  });

  elements.discard.addEventListener('click', () => {
    clearTimeout(timer);
    timer = null;
    removeDraft(key()); // 입력은 그대로 둔다
    hideBanner();
  });

  const touch = () => {
    if (!active) return;
    touched = true;
    clearTimeout(timer);
    timer = setTimeout(write, DRAFT_DELAY_MS);
  };
  elements.form.addEventListener('input', touch);
  elements.form.addEventListener('change', touch);

  // 취소와 상단 "← 주제". 변경이 있으면 확인 창을 띄우고, 취소하면 머문다.
  for (const link of leaveLinks) {
    link.addEventListener('click', (event) => {
      if (!active) return;
      if (hasChanges()) {
        if (!window.confirm(DISCARD_CONFIRM)) {
          event.preventDefault();
          return;
        }
      } else if (pending !== null) {
        stop(); // 아직 고르지 않은 초안은 남겨 둔다
        return;
      }
      stop();
      removeDraft(key());
    });
  }

  // 새로고침이나 탭 닫기에서 변경이 있으면 브라우저 이탈 경고를 띄운다.
  window.addEventListener('beforeunload', (event) => {
    if (!active || !hasChanges()) return;
    flush();
    event.preventDefault();
    event.returnValue = '';
  });
  // 이탈 경고가 없는 브라우저(iOS Safari 등)에서도 초안은 남는다.
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush();
  });

  return { start, flush, flushForSave, stop, markSaved, hasChanges };
}
