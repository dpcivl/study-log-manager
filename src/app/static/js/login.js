// S1 로그인. POST /api/login 을 부른다. (F5)
const form = document.getElementById('login-form');
const input = document.getElementById('login-password');
const messages = {
  invalid: document.getElementById('login-error-invalid'),
  locked: document.getElementById('login-error-locked'),
  other: document.getElementById('login-error-other'),
};

function showError(which, text) {
  for (const [key, el] of Object.entries(messages)) el.hidden = key !== which;
  if (which === 'other') messages.other.textContent = text; // 사용자 텍스트는 textContent로만 넣는다
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  let response;
  try {
    response = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: input.value }),
    });
  } catch {
    showError('other', '서버에 연결할 수 없습니다');
    return;
  }
  if (response.status === 204) {
    input.value = '';
    location.href = '/';
  } else if (response.status === 401) {
    showError('invalid');
    input.select();
  } else if (response.status === 429) {
    showError('locked');
    input.select();
  } else {
    showError('other', '로그인하지 못했습니다');
  }
});
