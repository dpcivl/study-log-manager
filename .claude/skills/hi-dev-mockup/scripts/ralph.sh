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

  # 완료 표시가 있으면 끝낸다
  if [ -f "$PROGRESS" ] && tail -n 3 "$PROGRESS" | grep -q "STATUS: DONE"; then
    echo "===== 목업 완성: ${i}회차에 끝났습니다 ====="
    exit 0
  fi
done

echo "===== 최대 ${MAX_RUNS}회를 다 돌았지만 완료되지 않았습니다. $PROGRESS를 확인하세요 ====="
exit 1