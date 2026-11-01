// S1 로그인. POST /api/login 을 부른다. (F5, F11)
import { BAD_RESPONSE_MESSAGE, timedFetch } from './common.js';

const form = document.getElementById('login-form');
const input = document.getElementById('login-password');
const submitBtn = form.querySelector('button[type="submit"]');
const messages = {
  invalid: document.getElementById('login-error-invalid'),
  locked: document.getElementById('login-error-locked'),
  net: document.getElementById('login-error-net'),
};

// which: 'invalid' | 'locked' | 'net' | null(모두 숨김). 사용자에게 보일 값은 textContent로만 넣는다.
function showError(which, text) {
  for (const [key, el] of Object.entries(messages)) el.hidden = key !== which;
  if (which === 'locked' || which === 'net') messages[which].textContent = text;
}

function lockedText(data) {
  const seconds = data && data.error && data.error.retry_after;
  return Number.isFinite(seconds) && seconds > 0
    ? '잠시 후 다시 시도하세요 (' + Math.ceil(seconds) + '초)'
    : '잠시 후 다시 시도하세요';
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (submitBtn.disabled) return;
  submitBtn.disabled = true; // 응답을 기다리는 동안 연타를 막는다
  showError(null);
  const result = await timedFetch(
    '/api/login',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: input.value }),
    },
    (res) => (res.status === 204 ? null : res.json()),
  );
  if (result.failure) {
    showError('net', result.failure);
    submitBtn.disabled = false;
    return;
  }
  const { response } = result;
  const data = result.bodyOk ? result.body : null;
  if (response.status === 204) {
    input.value = '';
    location.href = '/'; // 이동이 끝날 때까지 버튼을 꺼 둔다
    return;
  }
  if (response.ok) {
    // 2xx인데 204가 아니다. JSON이 아니면 해석할 수 없는 응답이다.
    showError('net', BAD_RESPONSE_MESSAGE);
  } else if (response.status === 401) {
    showError('invalid');
    input.select();
  } else if (response.status === 429) {
    showError('locked', lockedText(data));
    input.select();
  } else {
    showError('net', (data && data.error && data.error.message) || '로그인하지 못했습니다');
  }
  submitBtn.disabled = false;
});

// 로그인에 성공하면 버튼을 끈 채로 떠난다. 뒤로 가기로 bfcache에서 복원되면 스크립트가 다시 돌지 않으므로 여기서 다시 켠다.
window.addEventListener('pageshow', (event) => {
  if (event.persisted) submitBtn.disabled = false;
});
