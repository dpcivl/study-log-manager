"""오늘 날짜(KST). 한국 표준시는 일광절약시간이 없어 고정 오프셋으로 충분하다."""

from datetime import UTC, date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))


def today_kst() -> date:
    return datetime.now(UTC).astimezone(KST).date()
