// S3 상단 바의 내보내기. GET /api/subjects/{id}/export (F6)
import { BAD_RESPONSE_MESSAGE, errorMessage, timedFetch } from './common.js';

const FALLBACK_NAME = 'subject.md';

// Content-Disposition의 filename*=UTF-8''<퍼센트 인코딩>을 푼다. 못 풀면 기본 이름이다.
function filenameFrom(response) {
  const match = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(response.headers.get('Content-Disposition') || '');
  if (!match) return FALLBACK_NAME;
  try {
    return decodeURIComponent(match[1].trim()) || FALLBACK_NAME;
  } catch {
    return FALLBACK_NAME;
  }
}

export function initExport(subjectId) {
  const button = document.getElementById('export-btn');
  const error = document.getElementById('export-error');
  const url = '/api/subjects/' + subjectId + '/export';

  function showError(message) {
    error.textContent = message;
    error.hidden = !message;
  }

  button.hidden = false;
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true; // 응답을 기다리는 동안 연타를 막는다
    showError('');
    try {
      // 성공이면 본문을 파일로, 실패면 오류 JSON을 읽는다. 둘 다 15초 제한 안에서 끝나야 한다.
      const result = await timedFetch(url, {}, (res) => (res.ok ? res.blob() : res.json()));
      if (result.failure) {
        showError(result.failure);
        return;
      }
      const { response } = result;
      if (response.status === 401) {
        location.href = '/login';
        return;
      }
      if (!response.ok) {
        const data = result.bodyOk ? result.body : null;
        showError(errorMessage({ status: response.status, data }, '내보내지 못했습니다'));
        return;
      }
      if (!result.bodyOk) {
        showError('내보내지 못했습니다');
        return;
      }
      // 2xx여도 204이거나 text/markdown이 아니면(프록시 오류 페이지 등) 파일을 만들지 않는다.
      const contentType = response.headers.get('Content-Type') || '';
      if (response.status === 204 || !/^\s*text\/markdown\s*(;|$)/i.test(contentType)) {
        showError(BAD_RESPONSE_MESSAGE);
        return;
      }
      const blob = result.body;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = filenameFrom(response);
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } finally {
      button.disabled = false;
    }
  });
}
