#!/usr/bin/env bash
# 랄프 루프: hi-dev-mockup을 새 세션으로 반복 실행한다.
# 프로젝트 루트에서 실행한다: bash .claude/skills/hi-dev-mockup/scripts/ralph.sh [최대 반복 횟수]

PROGRESS="docs/mockup-progress.md"

if [ ! -f "docs/design.md" ]; then
  echo "docs/design.md가 없습니다. hi-dev-plan으로 만든 설계 문서를 먼저 넣으세요."
  exit 1
fi

# design.md의 화면(S)·기능(F) ID 개수를 센다
ID_COUNT=$(grep -oE '\b[SF][0-9]+\b' docs/design.md | sort -u | wc -l | tr -d ' ')

# 최대 횟수: 숫자를 붙여 실행하면 그 값, 아니면 ID 개수 × 2
MAX_RUNS="${1:-$((ID_COUNT * 2))}"
echo "화면·기능 ${ID_COUNT}개, 최대 ${MAX_RUNS}회까지 반복합니다."

for i in $(seq 1 "$MAX_RUNS"); do
  echo "===== 랄프 루프 $i / $MAX_RUNS 회차 ====="

  # 매 회차 새 세션으로 시작한다. 기억은 docs/mockup-progress.md에만 남는다
  claude -p "/hi-dev-mockup" \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Write" "Edit" "Bash(bash .claude/skills/hi-dev-mockup/scripts/check_ids.sh)"

  # 회차마다 커밋해 둔다. 문제가 생기면 이 회차로 돌아올 수 있다
  git add mockup docs/mockup-progress.md
  git commit -q -m "mockup: 랄프 루프 ${i}회차" || true

  # 완료 표시: 마지막 줄이 정확히 STATUS: DONE일 때만 인정한다
  if [ -f "$PROGRESS" ] && tail -n 1 "$PROGRESS" | grep -qx "STATUS: DONE"; then
    # Claude의 완료 선언을 스크립트가 다시 확인한다
    if grep -qF -- "- [ ]" "$PROGRESS"; then
      echo "체크 안 된 항목이 남아 있어 완료 표시를 지우고 계속합니다."
      sed '$d' "$PROGRESS" > "$PROGRESS.tmp" && mv "$PROGRESS.tmp" "$PROGRESS"
      continue
    fi
    if ! bash .claude/skills/hi-dev-mockup/scripts/check_ids.sh | grep -q "^PASS"; then
      echo "ID 검사를 통과하지 못해 완료 표시를 지우고 계속합니다."
      sed '$d' "$PROGRESS" > "$PROGRESS.tmp" && mv "$PROGRESS.tmp" "$PROGRESS"
      continue
    fi
    echo "===== 목업 완성: ${i}회차에 끝났습니다 ====="
    exit 0
  fi
done

echo "===== 최대 ${MAX_RUNS}회를 다 돌았지만 완료되지 않았습니다. $PROGRESS를 확인하세요 ====="
exit 1