"""초기 데이터 시드: 빅데이터분석기사 실기 (주제 1개, 공부 기록 4건, 노트 6건).

프로젝트 폴더에서 `python scripts/seed_bigdata.py`로 실행한다.
DB 주소는 앱과 같이 `DATABASE_URL`(환경 변수 또는 .env)을 따른다.
같은 이름의 주제가 이미 있으면 아무것도 바꾸지 않고 끝낸다.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select  # noqa: E402

from app.db import Base, make_engine, make_session_factory  # noqa: E402
from app.models import Note, StudySession, Subject  # noqa: E402
from app.settings import get_settings  # noqa: E402

SUBJECT = {
    "name": "빅데이터분석기사 실기",
    "background": (
        "임베디드 HW 개발 1년 / SW 개발 2년 5개월 / 정보처리산업기사 / AI 엔지니어 1개월째"
    ),
    "started_on": date(2026, 10, 26),
    "target_date": None,
}

SESSIONS = [
    (date(2026, 10, 26), 60),
    (date(2026, 10, 27), 120),
    (date(2026, 10, 28), 60),
    (date(2026, 10, 29), 120),
]

NOTES = [
    {
        "kind": "remember",
        "title": "csv 저장 시 인덱스 제외",
        "tags": ["pandas", "csv"],
        "is_open": False,
        "body": (
            "인덱스를 제외하고 저장하려면 index=False\n"
            "\n"
            "```python\n"
            "df.to_csv('cafe.csv', index=False)\n"
            "```"
        ),
    },
    {
        "kind": "remember",
        "title": "Pandas 2.x의 info() 자료형",
        "tags": ["pandas"],
        "is_open": False,
        "body": (
            "Pandas 버전은 2.x 버전으로 진행했음\n"
            "- info()를 사용했을 때 object 타입으로 안 나오고 str 타입으로 나올 때가 있었음"
        ),
    },
    {
        "kind": "remember",
        "title": "DataFrame의 isnull()과 isna()가 다른 이유?",
        "tags": ["pandas"],
        "is_open": True,
        "body": "",
    },
    {
        "kind": "remember",
        "title": "날짜와 시간은 문자열로 읽힌다",
        "tags": ["datetime", "pandas"],
        "is_open": False,
        "body": (
            "파이썬은 데이터를 불러올 때 날짜와 시간을 자동으로 인식하지 못하고 "
            "문자열 데이터로 인식하기 땜누에 자료형이 object로 나옴"
        ),
    },
    {
        "kind": "debug",
        "title": "FileNotFoundError: temp_csv",
        "tags": ["csv"],
        "is_open": False,
        "body": (
            "## 문제상황\n"
            "pandas의 DataFrame의 to_csv로 저장 후 불러오려다가 실패했었음\n"
            "\n"
            "## 원인\n"
            "temp_csv가 아니라 temp.csv를 불러왔어야 했음\n"
            "\n"
            "## 해결\n"
            "오타를 고치고 난 뒤 해결함\n"
            "\n"
            "`FileNotFoundError: [Errno 2] No such file or directory: 'temp_csv'`"
        ),
    },
    {
        "kind": "review",
        "title": "코딩팡 사용",
        "tags": [],
        "is_open": False,
        "body": (
            "- 시나공 챕터3부터는 코딩팡에서 진행했음(https://code.sideonai.com/playground)\n"
            "  - 퇴근후딴짓 깃허브(https://github.com/lovedlim/bae-v3)에서 데이터 얻을 수 있음\n"
            "- 문제를 주석에 적어두면서 어떤 걸 구현할지 차근차근 적으면서 해야함"
        ),
    },
]


def main() -> int:
    url = get_settings().database_url
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    engine = make_engine(url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    try:
        with session_factory() as db:
            exists = db.scalar(select(Subject.id).where(Subject.name == SUBJECT["name"]).limit(1))
            if exists is not None:
                print(f"주제 '{SUBJECT['name']}'이(가) 이미 있습니다. 아무것도 바꾸지 않았습니다.")
                return 0

            # 전체를 한 트랜잭션으로 넣는다. 중간에 실패하면 롤백된다.
            try:
                subject = Subject(**SUBJECT)
                db.add(subject)
                db.flush()
                for studied_on, minutes in SESSIONS:
                    db.add(
                        StudySession(
                            subject_id=subject.id,
                            studied_on=studied_on,
                            minutes=minutes,
                            memo="",
                        )
                    )
                for note in NOTES:
                    db.add(Note(subject_id=subject.id, **note))
                db.commit()
            except Exception:
                db.rollback()
                raise
    finally:
        engine.dispose()

    print(
        f"넣었습니다: 주제 1건, 공부 기록 {len(SESSIONS)}건, 노트 {len(NOTES)}건 "
        f"(합계 {sum(m for _, m in SESSIONS)}분)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
