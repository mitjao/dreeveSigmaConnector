"""
Parse SIGMA Log Format (.slf) — the XML SIGMA Cloud stores each activity as
(inside a ZIP). Reverse-engineered from SIGMA DATA CENTER's
ActivityFactory.createLogFromSLF / ActivityEntryMapper.

An .slf looks like:

    <Activity revision="400">
      <appVersion>3.0.41</appVersion>
      <platform>android</platform>
      <Computer unit="rox111" unitGUID="…"/>
      <GeneralInformation>
        <user gender="male"><![CDATA[Mitja]]></user>
        <sport>cycling</sport>
        <GUID>39E96B24-…</GUID>
        <startDate>Thu Aug 13 13:00:52 GMT+0200 2026</startDate>
        <modificationDate>1786994617308</modificationDate>
        <statistic distance="…" averageSpeed="…" …/>
      </GeneralInformation>
      <Entries>
        <Entry timeStart="Thu Aug 13 13:00:53 GMT+0200 2026"
               latitude="49.96…" longitude="8.27…" altitude="48800"
               distanceAbsolute="0.34" speed="0.34" cadence="0"
               heartrate="…" power="…" temperature="22.0"
               trainingTimeAbsolute="200" useForTrack="1" useForChart="1"/>
        …
      </Entries>
      <Markers><Marker type="fitStandardLap" …/></Markers>
    </Activity>

Units (from the decompiled mapper):
  altitude            millimetres   -> divide by 1000 for metres
  distance/absolute   metres
  speed               metres/second
  latitude/longitude  decimal degrees
  cadence             rpm
  heartrate           bpm
  power               watts
  temperature         °C
  trainingTime(Absolute) centiseconds (1/100 s)

(altitude and time scales confirmed against DATA CENTER's FIT export mapper:
 setAltitude(millimeterToMeter.convert(entry.altitude)); trainingTime / 100.)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# "Thu Aug 13 13:00:53 GMT+0200 2026"  (AS3 Date.toString())
_SLF_DATE = re.compile(
    r"^\w{3}\s+(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+"
    r"GMT([+-]\d{4})\s+(\d{4})$"
)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_slf_date(s: str) -> Optional[datetime]:
    """Parse an AS3 Date string into an aware UTC datetime, or None."""
    if not s:
        return None
    m = _SLF_DATE.match(s.strip())
    if not m:
        return None
    mon, day, hh, mm, ss, off, year = m.groups()
    sign = 1 if off[0] == "+" else -1
    tz = timezone(sign * _timedelta_minutes(int(off[1:3]) * 60 + int(off[3:5])))
    dt = datetime(int(year), _MONTHS[mon], int(day), int(hh), int(mm), int(ss), tzinfo=tz)
    return dt.astimezone(timezone.utc)


def _timedelta_minutes(minutes: int):
    from datetime import timedelta
    return timedelta(minutes=minutes)


def _f(v: Optional[str]) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


@dataclass
class TrackPoint:
    time: Optional[datetime]
    lat: Optional[float] = None
    lon: Optional[float] = None
    altitude_m: Optional[float] = None
    distance_m: Optional[float] = None
    speed_ms: Optional[float] = None
    cadence: Optional[int] = None
    heartrate: Optional[int] = None
    power_w: Optional[int] = None
    temperature_c: Optional[float] = None
    elapsed_cs: Optional[float] = None   # trainingTimeAbsolute (cumulative moving time, centiseconds)


@dataclass
class Lap:
    """A lap marker (SIGMA `<Marker type="fitStandardLap"|"l"|"al">`)."""
    type: str = ""
    number: Optional[int] = None
    time_s: Optional[float] = None            # moving time of the lap (from `time`, cs->s)
    time_absolute_cs: Optional[float] = None  # cumulative moving time at lap end
    distance_m: Optional[float] = None        # lap distance (from `distance`)
    distance_absolute_m: Optional[float] = None  # cumulative distance at lap end
    avg_speed_ms: Optional[float] = None
    max_speed_ms: Optional[float] = None
    avg_cadence: Optional[int] = None
    max_cadence: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    avg_power_w: Optional[int] = None
    max_power_w: Optional[int] = None
    calories: Optional[float] = None


@dataclass
class Activity:
    guid: str = ""
    sport: str = ""
    start: Optional[datetime] = None
    modification_date: Optional[int] = None
    device: str = ""
    name: str = ""
    total_distance_m: Optional[float] = None
    total_time_s: Optional[float] = None
    calories: Optional[float] = None
    points: list[TrackPoint] = field(default_factory=list)
    laps: list[Lap] = field(default_factory=list)

    @property
    def has_gps(self) -> bool:
        return any(p.lat is not None and p.lon is not None for p in self.points)

    def lap_markers(self) -> list[Lap]:
        """Lap-defining markers only, most specific type first, ordered along the ride."""
        for t in ("fitStandardLap", "l", "al"):
            laps = [m for m in self.laps if m.type == t]
            if laps:
                laps.sort(key=_lap_sort_key)
                return laps
        return []


def parse_slf(data: bytes | str) -> Activity:
    """Parse SLF bytes/str into an Activity with track points."""
    if isinstance(data, bytes):
        # Strip anything before the first '<' (some files carry a BOM/prefix).
        i = data.find(b"<")
        text = data[i:].decode("utf-8", "replace") if i >= 0 else data.decode("utf-8", "replace")
    else:
        text = data
        j = text.find("<")
        if j > 0:
            text = text[j:]

    root = ET.fromstring(text)
    act = Activity()

    gi = root.find("GeneralInformation")
    if gi is not None:
        act.sport = (gi.findtext("sport") or "").strip()
        act.guid = (gi.findtext("GUID") or "").strip()
        act.name = (gi.findtext("name") or "").strip()
        act.start = parse_slf_date(gi.findtext("startDate") or "")
        md = gi.findtext("modificationDate")
        act.modification_date = int(md) if md and md.isdigit() else None
        # Summary metrics are direct children of GeneralInformation.
        # `<statistic>` is just a boolean flag, not a container.
        act.total_distance_m = _f(gi.findtext("distance"))
        # trainingTime is moving time in centiseconds (pairs with averageSpeed).
        act.total_time_s = _cs_to_s(_f(gi.findtext("trainingTime")))
        act.calories = _f(gi.findtext("calories"))

    comp = root.find("Computer")
    if comp is not None:
        act.device = comp.get("unit", "")

    entries = root.find("Entries")
    if entries is not None:
        for e in entries.findall("Entry"):
            act.points.append(_entry_to_point(e))

    markers = root.find("Markers")
    if markers is not None:
        for m in markers.findall("Marker"):
            act.laps.append(_marker_to_lap(m))

    # Fallback start time from the first point.
    if act.start is None and act.points and act.points[0].time:
        act.start = act.points[0].time
    return act


def _lap_sort_key(m: "Lap"):
    if m.number is not None:
        return (0, m.number)
    if m.distance_absolute_m is not None:
        return (1, m.distance_absolute_m)
    return (2, m.time_absolute_cs or 0)


def _int(v):
    f = _f(v)
    return None if f is None else int(round(f))


def _marker_to_lap(m: ET.Element) -> "Lap":
    return Lap(
        type=m.get("type", ""),
        number=_int(m.get("number")),
        time_s=_cs_to_s(_f(m.get("time"))),
        time_absolute_cs=_f(m.get("timeAbsolute")),
        distance_m=_f(m.get("distance")),
        distance_absolute_m=_f(m.get("distanceAbsolute")),
        avg_speed_ms=_f(m.get("averageSpeed")),
        max_speed_ms=_f(m.get("maximumSpeed")),
        avg_cadence=_int(m.get("averageCadence")),
        max_cadence=_int(m.get("maximumCadence")),
        avg_hr=_int(m.get("averageHeartrate")),
        max_hr=_int(m.get("maximumHeartrate")),
        avg_power_w=_int(m.get("averagePower")),
        max_power_w=_int(m.get("maximumPower")),
        calories=_f(m.get("calories")),
    )


def _cs_to_s(v: Optional[float]) -> Optional[float]:
    return None if v is None else v / 100.0


def _entry_to_point(e: ET.Element) -> TrackPoint:
    alt = _f(e.get("altitude"))
    cad = _f(e.get("cadence"))
    hr = _f(e.get("heartrate"))
    pw = _f(e.get("power"))
    return TrackPoint(
        time=parse_slf_date(e.get("timeStart") or ""),
        lat=_f(e.get("latitude")),
        lon=_f(e.get("longitude")),
        altitude_m=None if alt is None else alt / 1000.0,
        distance_m=_f(e.get("distanceAbsolute")),
        speed_ms=_f(e.get("speed")),
        cadence=None if cad is None else int(round(cad)),
        heartrate=None if hr is None else int(round(hr)),
        power_w=None if pw is None else int(round(pw)),
        temperature_c=_f(e.get("temperature")),
        elapsed_cs=_f(e.get("trainingTimeAbsolute")),
    )
