"""
Geocoder — converts place name to lat/lon and timezone offset.
Uses geopy (Nominatim, no API key needed) + timezonefinder.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut
    GEOPY_OK = True
except ImportError:
    GEOPY_OK = False

try:
    from timezonefinder import TimezoneFinder
    from datetime import timezone, datetime
    import zoneinfo
    TZ_OK = True
except ImportError:
    TZ_OK = False


_geolocator = Nominatim(user_agent="vedic_astro_brain_v1") if GEOPY_OK else None
_tf = TimezoneFinder() if TZ_OK else None


def geocode(place: str) -> Optional[dict]:
    """
    Returns dict with lat, lon, timezone_offset_hours, timezone_name.
    Returns None if geocoding fails.
    """
    if not GEOPY_OK or not _geolocator:
        return None
    try:
        time.sleep(1.1)  # Nominatim rate limit: 1 req/sec
        location = _geolocator.geocode(place, timeout=15)
        if not location:
            return None
        lat = location.latitude
        lon = location.longitude

        tz_name = None
        tz_offset = 0.0
        if _tf and TZ_OK:
            tz_name = _tf.timezone_at(lat=lat, lng=lon)
            if tz_name:
                try:
                    tz = zoneinfo.ZoneInfo(tz_name)
                    now = datetime.now(tz)
                    tz_offset = now.utcoffset().total_seconds() / 3600
                except Exception:
                    tz_offset = 0.0

        return {
            "lat": lat,
            "lon": lon,
            "display_name": location.address[:80],
            "timezone_name": tz_name or "UTC",
            "timezone_offset_hours": tz_offset,
        }
    except GeocoderTimedOut:
        return None
    except Exception:
        return None


def parse_birth_datetime(
    date_str: str,     # "YYYY-MM-DD" or "DD/MM/YYYY" or "Month DD YYYY"
    time_str: str,     # "HH:MM" or "HH:MM:SS" (local time)
    tz_offset: float,  # hours offset from UTC
) -> "datetime":
    """Parse birth date/time and convert to UTC datetime."""
    from datetime import datetime, timedelta, timezone

    date_str = date_str.strip()
    time_str = time_str.strip()

    # Try multiple date formats
    date_formats = [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
        "%B %d %Y", "%b %d %Y", "%d %B %Y",
        "%m/%d/%Y",
    ]
    birth_date = None
    for fmt in date_formats:
        try:
            birth_date = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue
    if birth_date is None:
        raise ValueError(f"Cannot parse date: {date_str}. Use YYYY-MM-DD format.")

    # Parse time
    time_formats = ["%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"]
    birth_time = None
    for fmt in time_formats:
        try:
            birth_time = datetime.strptime(time_str, fmt).time()
            break
        except ValueError:
            continue
    if birth_time is None:
        raise ValueError(f"Cannot parse time: {time_str}. Use HH:MM format (24-hour).")

    # Combine and convert to UTC
    local_dt = datetime.combine(birth_date, birth_time)
    offset   = timedelta(hours=tz_offset)
    utc_dt   = local_dt - offset
    return utc_dt.replace(tzinfo=timezone.utc)
