// 여러 화면이 같이 쓰는 도우미. 사용자 텍스트는 textContent로만 DOM에 넣는다.

// 요청 하나를 기다리는 최대 시간(F11). 이 안에 응답이 없으면 요청을 끊는다.
export const REQUEST_TIMEOUT_MS = 15000;

const CONNECT_FAIL_MESSAGE = '서버에 연결할 수 없습니다';
const TIMEOUT_GET_MESSAGE = '서버 응답이 없습니다. 잠시 후 다시 시도하세요';
const TIMEOUT_WRITE_MESSAGE = '응답을 받지 못했습니다. 저장되었는지 확인한 뒤 다시 시도하세요';
export const BAD_RESPONSE_MESSAGE = '서버 응답을 해석할 수 없습니다';

// 시간 제한이 있는 fetch. 본문 읽기(readBody)까지 같은 제한 안에서 끝나야 한다.
// 실패(연결 실패, 시간 초과)면 { failure: 화면에 보일 문구 }를 돌려준다.
// 응답을 받았으면 { response, body, bodyOk }를 돌려준다. 본문을 못 읽었으면 bodyOk가 false다.
export async function timedFetch(url, options, readBody) {
  const method = (options.method || 'GET').toUpperCase();
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  const timeoutFailure = () => ({ failure: method === 'GET' ? TIMEOUT_GET_MESSAGE : TIMEOUT_WRITE_MESSAGE });
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    let body = null;
    let bodyOk = true;
    try {
      body = await readBody(response);
    } catch {
      bodyOk = false;
    }
    if (timedOut) return timeoutFailure();
    return { response, body, bodyOk };
  } catch {
    return timedOut ? timeoutFailure() : { failure: CONNECT_FAIL_MESSAGE };
  } finally {
    clearTimeout(timer);
  }
}

// 2xx 응답의 본문이 JSON 객체인가. 204는 본문이 없으므로 따지지 않는다.
export function isUsableSuccess(response, body, bodyOk) {
  if (response.status === 204) return true;
  return bodyOk && body !== null && typeof body === 'object';
}

// JSON API 호출. 401이면 /login으로 보내고 응답을 돌려주지 않는다(페이지가 이동한다).
// 실패하면 { ok: false, status, data, message? }를 돌려준다. 연결 실패와 시간 초과는 status 0,
// 2xx인데 JSON이 아닌 응답은 그 상태 코드로 오며, 둘 다 message에 화면에 보일 문구가 있다.
// ok가 true이면 204가 아닌 한 data는 JSON 객체다.
export async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const result = await timedFetch(url, options, (res) => (res.status === 204 ? null : res.json()));
  if (result.failure) return { ok: false, status: 0, data: null, message: result.failure };
  const { response } = result;
  if (response.status === 401) {
    location.href = '/login';
    return new Promise(() => {});
  }
  if (response.ok && !isUsableSuccess(response, result.body, result.bodyOk)) {
    return { ok: false, status: response.status, data: null, message: BAD_RESPONSE_MESSAGE };
  }
  return { ok: response.ok, status: response.status, data: result.bodyOk ? result.body : null };
}

// 실패 응답에서 화면에 보일 문구를 고른다.
export function errorMessage(res, fallback) {
  if (res.message) return res.message;
  if (res.status === 0) return CONNECT_FAIL_MESSAGE;
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

// ISO 8601 UTC 시각 → KST 날짜 "YYYY-MM-DD"
export function dateKst(iso) {
  return new Date(Date.parse(iso) + 9 * 3600 * 1000).toISOString().slice(0, 10);
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
  if (first && typeof first.focus === 'function') first.focus(); // 라디오 묶음은 focus가 없다
}
