---
name: hi-dev-mockup
description: Builds an HTML mockup from docs/design.md one step per run, tracking progress in docs/mockup-progress.md. Run by the Ralph loop script or with /hi-dev-mockup for a single step.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(bash .claude/skills/hi-dev-mockup/scripts/check_ids.sh)
model: sonnet
effort: medium
---

# hi-dev-mockup: 목업 단계 매뉴얼 (랄프 루프 1회분)

이 매뉴얼은 **한 번 실행에 한 걸음만** 진행한다. 반복은 바깥의 `scripts/ralph.sh`가 맡는다.
매 실행은 이전 대화를 기억하지 못하므로, 기억은 전부 `docs/mockup-progress.md` 파일에 남긴다.

## 입력과 출력
- 입력: `docs/design.md` (hi-dev-plan이 만든 설계 문서. 수정하지 않는다)
- 출력: `mockup/index.html` (목업), `docs/mockup-progress.md` (진행 기록)

## 매 실행 순서

### 1. 상황 파악
- `docs/design.md`를 읽는다. 없으면 "docs/design.md가 없습니다. hi-dev-plan을 먼저 실행하세요."라고 말하고 멈춘다.
- `docs/mockup-progress.md`를 읽는다. 없으면 첫 실행이므로 아래 양식으로 만든다. design.md의 화면 ID(S1, S2…)와 기능 ID(F1, F2…)를 하나도 빠짐없이 옮긴다.

```
# 목업 진행 기록

## 할 일
- [ ] S1: (화면 이름)
- [ ] F1: (기능 이름) - 완료 기준: (design.md의 완료 기준)

## 실행 기록
```

### 2. 한 걸음 작업
- 체크되지 않은 항목 중 **맨 위 하나만** 고른다. 화면(S)을 기능(F)보다 먼저 한다.
- 그 항목만 `mockup/index.html`에 만들거나 고친다. 다른 항목은 건드리지 않는다.
- 목업 규칙:
  - HTML 파일 하나, 외부 라이브러리 없이 HTML/CSS/JavaScript만 쓴다.
  - 데이터는 그럴듯한 한국어 더미 데이터로 채운다. 서버 연동은 하지 않고 흉내만 낸다.
  - 더미 데이터의 필드 이름과 모양은 design.md "5. 인터페이스 약속"의 응답 JSON 예시를 그대로 따른다.
  - 화면 영역 시작에 `<!-- S1 -->`, 기능 요소 근처에 `<!-- F2 -->`처럼 ID 주석을 단다.

### 3. 검증
- `bash .claude/skills/hi-dev-mockup/scripts/check_ids.sh`를 실행해 ID 주석이 빠진 항목을 확인한다.
- 방금 작업한 항목의 완료 기준을 HTML 코드와 대조한다.
- 둘 다 통과하면 그 항목을 `[x]`로 체크한다. 통과하지 못하면 체크하지 않고 이유를 기록한다. 다음 실행이 이어서 고친다.
### 4. 기록
- `docs/mockup-progress.md`의 "실행 기록"에 이번 회차의 항목, 결과, 다음 실행이 알아야 할 점을 남긴다.
- "할 일"의 모든 항목이 `[x]`이고 check_ids.sh 결과가 PASS이면 파일 맨 끝 줄에 `STATUS: DONE`을 쓴다.
- 그 외에는 `STATUS: DONE`을 절대 쓰지 않는다.
