from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


DEFAULT_TENANT_TIMEZONE = "America/Sao_Paulo"


@dataclass(frozen=True)
class CanonicalPeriod:
    start: date
    end: date
    timezone_name: str = DEFAULT_TENANT_TIMEZONE

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def utc_bounds(self) -> tuple[datetime, datetime]:
        tenant_tz = ZoneInfo(self.timezone_name)
        local_start = datetime.combine(self.start, time.min, tzinfo=tenant_tz)
        local_end = datetime.combine(self.end, time.max, tzinfo=tenant_tz)
        return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)

    def dates(self) -> list[str]:
        return [(self.start + timedelta(days=offset)).isoformat() for offset in range(self.days)]


def _parse_date(value: str | None) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def resolve_period(
    *, start: str | None = None, end: str | None = None, days: int = 30,
    month: str | None = None, timezone_name: str = DEFAULT_TENANT_TIMEZONE,
    max_days: int = 366,
) -> CanonicalPeriod:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return CanonicalPeriod(start_date, end_date, timezone_name)

    month_text = str(month or "").strip()
    if month_text:
        try:
            year, month_number = (int(part) for part in month_text[:7].split("-", 1))
            month_start = date(year, month_number, 1)
            month_end = date(year, month_number, calendar.monthrange(year, month_number)[1])
            return CanonicalPeriod(month_start, month_end, timezone_name)
        except (TypeError, ValueError):
            pass

    tenant_today = datetime.now(ZoneInfo(timezone_name)).date()
    safe_days = max(1, min(int(days or 30), max_days))
    period_end = end_date or tenant_today
    period_start = start_date or (period_end - timedelta(days=safe_days - 1))
    if period_start > period_end:
        period_start, period_end = period_end, period_start
    return CanonicalPeriod(period_start, period_end, timezone_name)


def local_date(value: datetime, timezone_name: str = DEFAULT_TENANT_TIMEZONE) -> date:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(ZoneInfo(timezone_name)).date()
