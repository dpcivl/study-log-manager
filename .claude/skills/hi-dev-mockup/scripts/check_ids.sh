#!/usr/bin/env bash
# design.md에 있는 화면(S)·기능(F) ID가 목업 HTML에 주석으로 들어갔는지 확인한다.
# 프로젝트 루트에서 실행한다: bash .claude/skills/hi-dev-mockup/scripts/check_ids.sh

DESIGN="docs/design.md"
MOCKUP="mockup/index.html"

if [ ! -f "$DESIGN" ]; then
  echo "FAIL: $DESIGN 파일이 없습니다."
  exit 1
fi
if [ ! -f "$MOCKUP" ]; then
  echo "FAIL: $MOCKUP 파일이 아직 없습니다."
  exit 1
fi

# design.md에서 S1, F12 같은 ID를 중복 없이 뽑는다
ids=$(grep -oE '\b[SF][0-9]+\b' "$DESIGN" | sort -u)

missing=""
for id in $ids; do
  # <!-- F2 --> 처럼 주석으로 들어가 있는지 본다
  if ! grep -qE "<!--[[:space:]]*$id[[:space:]]*-->" "$MOCKUP"; then
    missing="$missing $id"
  fi
done

if [ -z "$missing" ]; then
  echo "PASS: design.md의 모든 ID가 목업에 있습니다."
else
  echo "MISSING:$missing"
fi