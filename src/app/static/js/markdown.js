// 마크다운 렌더. S4 미리보기와 S5 본문이 같은 함수를 쓴다. (F3)
// 순서: marked로 HTML 변환 → DOMPurify로 정화 → DOM 삽입 → highlight.js로 코드 강조.
// marked, DOMPurify, hljs는 vendor/의 classic script가 만든 전역이다(페이지 템플릿이 먼저 불러온다).
import { el } from './common.js';

// 본문에서 쓸 일이 없고 화면을 바꾸거나 입력을 가로챌 수 있는 요소는 정화 단계에서 뺀다.
const PURIFY_CONFIG = {
  FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'],
  FORBID_ATTR: ['style'],
  RETURN_DOM_FRAGMENT: true,
};

// 작업 목록(- [x], - [ ])의 체크 상태는 입력 요소 대신 글자 기호(☑ / ☐)로 보인다.
// input은 정화 단계에서 계속 금지한다.
if (typeof marked !== 'undefined') {
  marked.use({
    renderer: {
      checkbox(checked) {
        return checked
          ? '<span class="task-mark" role="img" aria-label="완료">☑</span>'
          : '<span class="task-mark" role="img" aria-label="미완료">☐</span>';
      },
      listitem(text, task) {
        return task ? `<li class="task-item">${text}</li>\n` : `<li>${text}</li>\n`;
      },
    },
  });
}

// source 마크다운을 target 안에 렌더한다. target의 기존 내용은 지운다.
export function renderMarkdown(target, source) {
  if (!source.trim()) {
    target.replaceChildren(el('p', '', '(내용 없음)'));
    return;
  }
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    // 라이브러리를 불러오지 못했다. 정화 없이 HTML을 만들 수 없으므로 원문을 글자 그대로 보인다.
    const pre = el('pre', '', source);
    target.replaceChildren(pre);
    return;
  }
  const html = marked.parse(source, { async: false, gfm: true, breaks: true });
  target.replaceChildren(DOMPurify.sanitize(html, PURIFY_CONFIG));
  if (typeof hljs === 'undefined') return;
  for (const code of target.querySelectorAll('pre code')) {
    // ```python 처럼 언어를 적은 블록만 강조한다(언어가 없으면 그대로 둔다).
    const match = /(?:^|\s)language-([\w+#-]+)/.exec(code.className);
    if (match && hljs.getLanguage(match[1])) hljs.highlightElement(code);
  }
}
