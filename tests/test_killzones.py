from datetime import datetime
from zoneinfo import ZoneInfo

from data.mt5_connector import get_active_killzone, WAT_TZ


def wat(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=WAT_TZ)


def test_london_killzone_active():
    # 08:00 WAT in winter = 03:00 EST (NY) -> inside london (2-5)
    assert get_active_killzone(wat(2024, 1, 15, 8, 0)) == "london"


def test_ny_am_killzone_active():
    # 13:00 WAT in winter = 08:00 EST -> inside ny_am (7-10)
    assert get_active_killzone(wat(2024, 1, 15, 13, 0)) == "ny_am"


def test_no_killzone_active():
    # 00:00 WAT in winter = 19:00 EST previous day -> outside all killzones
    assert get_active_killzone(wat(2024, 1, 15, 0, 0)) is None
