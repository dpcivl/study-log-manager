// S3 상단 바의 내보내기. GET /api/subjects/{id}/export (F6)
import { errorMessage } from './common.js';

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

async function failureMessage(response) {
  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  return errorMessage({ status: response.status, data }, '내보내지 못했습니다');
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
      let response;
      try {
        response = await fetch(url);
      } catch {
        showError(errorMessage({ status: 0, data: null }, ''));
        return;
      }
      if (response.status === 401) {
        location.href = '/login';
        return;
      }
      if (!response.ok) {
        showError(await failureMessage(response));
        return;
      }
      let blob;
      try {
        blob = await response.blob();
      } catch {
        showError('내보내지 못했습니다');
        return;
      }
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
