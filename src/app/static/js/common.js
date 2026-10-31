// 여러 화면이 같이 쓰는 도우미. 사용자 텍스트는 textContent로만 DOM에 넣는다.

// JSON API 호출. 401이면 /login으로 보내고 응답을 돌려주지 않는다(페이지가 이동한다).
// 네트워크 오류면 { ok: false, status: 0, data: null }을 돌려준다.
export async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    return { ok: false, status: 0, data: null };
  }
  if (response.status === 401) {
    location.href = '/login';
    return new Promise(() => {});
  }
  let data = null;
  if (response.status !== 204) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  }
  return { ok: response.ok, status: response.status, data };
}

// 실패 응답에서 화면에 보일 문구를 고른다.
export function errorMessage(res, fallback) {
  if (res.status === 0) return '서버에 연결할 수 없습니다';
  return (res.data && res.data.error && res.data.error.message) || fallback;
}

export function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// 오늘 날짜(KST) "YYYY-MM-DD". KST는 UTC+9 고정이다.
export function todayKst() {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

// 분 → "1.5h" (소수 첫째 자리까지, 0.0이면 "0h")
export function formatHours(minutes) {
  return String(Math.round(minutes / 6) / 10) + 'h';
}

// 목표일까지 D-day. 오늘은 KST 기준이다.
export function dday(target) {
  const diff = Math.round((Date.parse(target + 'T00:00:00Z') - Date.parse(todayKst() + 'T00:00:00Z')) / 86400000);
  return diff > 0 ? 'D-' + diff : diff === 0 ? 'D-Day' : 'D+' + -diff;
}

// 폼 안의 [data-error-for] 문구를 지운다.
export function clearErrors(form) {
  for (const p of form.querySelectorAll('[data-error-for]')) {
    p.textContent = '';
    p.hidden = true;
  }
}

// 422 응답의 fields를 필드별 문구 자리에 보인다. 자리가 없는 필드와 그 밖의 오류는 form 자리에 보인다.
export function showErrors(form, res, fallback) {
  clearErrors(form);
  const fields = (res.status === 422 && res.data && res.data.error && res.data.error.fields) || {};
  let first = null;
  const general = [];
  for (const [name, message] of Object.entries(fields)) {
    const p = form.querySelector('[data-error-for="' + name + '"]');
    if (p) {
      p.textContent = message;
      p.hidden = false;
      if (!first) first = form.elements[name];
    } else {
      general.push(message);
    }
  }
  if (Object.keys(fields).length === 0) general.push(errorMessage(res, fallback));
  if (general.length) {
    const p = form.querySelector('[data-error-for="form"]');
    p.textContent = general.join(' ');
    p.hidden = false;
  }
  if (first) first.focus();
}
