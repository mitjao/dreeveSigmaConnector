"""
Write an Activity (parsed from SLF) as a Garmin TCX file — a format Dreeve
imports natively (streams, laps, HR, power, cadence, GPS).

Laps come from the SLF `<Marker type="fitStandardLap">` entries (falling back to
manual "l" / auto "al" markers). Trackpoints are split into those laps by
cumulative distance (or cumulative moving time for indoor rides without GPS). If
an activity has no lap markers, one lap covering the whole ride is emitted.
Lap boundary semantics match DATA CENTER's own FIT-export mapper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from xml.sax.saxutils import escape

from .slf import Activity, Lap, TrackPoint

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
AX_NS = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"

# SIGMA sport -> TCX Sport (TCX only allows Running/Biking/Other).
_SPORT = {
    "cycling": "Biking",
    "biking": "Biking",
    "mountainbiking": "Biking",
    "ebike": "Biking",
    "running": "Running",
    "jogging": "Running",
    "trailrunning": "Running",
}


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return ("%.6f" % x).rstrip("0").rstrip(".") or "0"
    return str(x)


def activity_to_tcx(act: Activity) -> str:
    sport = _SPORT.get(act.sport.lower(), "Other")
    start_iso = _iso(act.start) or _iso(_first_time(act))

    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append(
        f'<TrainingCenterDatabase xmlns="{TCX_NS}" '
        f'xmlns:ns3="{AX_NS}" '
        f'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    )
    out.append("<Activities>")
    out.append(f'<Activity Sport="{sport}">')
    out.append(f"<Id>{start_iso}</Id>")

    for lap, pts in _laps(act):
        out.append(_lap_xml(act, lap, pts))

    if act.device:
        out.append(f"<Notes>{escape(f'SIGMA {act.device} · GUID {act.guid}')}</Notes>")
    out.append("</Activity>")
    out.append("</Activities>")
    out.append("</TrainingCenterDatabase>")
    return "\n".join(out)


def _laps(act: Activity) -> list[tuple[Lap | None, list[TrackPoint]]]:
    """Return [(lap_marker_or_None, points)] — one entry per emitted lap."""
    markers = act.lap_markers()
    if not markers:
        return [(None, act.points)]

    # Pick the split dimension the markers actually carry.
    if all(m.distance_absolute_m is not None for m in markers) and _has_distance(act):
        dim = "distance"
    elif all(m.time_absolute_cs is not None for m in markers):
        dim = "time"
    else:
        return [(None, act.points)]

    buckets: list[list[TrackPoint]] = [[] for _ in markers]
    idx = 0
    for p in act.points:
        val = p.distance_m if dim == "distance" else p.elapsed_cs
        if val is not None:
            # Advance to the first lap whose cumulative boundary still holds this point.
            while idx < len(markers) - 1 and val > _boundary(markers[idx], dim) + 1e-6:
                idx += 1
        buckets[idx].append(p)
    return list(zip(markers, buckets))


def _boundary(m: Lap, dim: str) -> float:
    return (m.distance_absolute_m if dim == "distance" else m.time_absolute_cs) or 0.0


def _lap_xml(act: Activity, lap: Lap | None, pts: list[TrackPoint]) -> str:
    start = pts[0].time if pts and pts[0].time else act.start
    start_iso = _iso(start)

    total_time = None
    dist = None
    calories = None
    max_speed = None
    avg_hr = max_hr = avg_cad = avg_pw = max_pw = avg_speed = None
    trigger = "Manual"

    if lap is not None:
        total_time = lap.time_s
        dist = lap.distance_m
        calories = lap.calories
        max_speed = lap.max_speed_ms
        avg_hr, max_hr = lap.avg_hr, lap.max_hr
        avg_cad, avg_pw, max_pw = lap.avg_cadence, lap.avg_power_w, lap.max_power_w
        avg_speed = lap.avg_speed_ms
        trigger = "Distance" if lap.distance_absolute_m is not None else "Manual"
    else:
        total_time = act.total_time_s
        dist = act.total_distance_m
        calories = act.calories

    if total_time is None and pts:
        total_time = _elapsed_seconds(pts)
    if dist is None and pts:
        dist = _delta_distance(pts)

    b: list[str] = [f'<Lap StartTime="{start_iso}">']
    if total_time is not None:
        b.append(f"<TotalTimeSeconds>{_num(total_time)}</TotalTimeSeconds>")
    if dist is not None:
        b.append(f"<DistanceMeters>{_num(dist)}</DistanceMeters>")
    if max_speed is not None:
        b.append(f"<MaximumSpeed>{_num(max_speed)}</MaximumSpeed>")
    if calories is not None:
        b.append(f"<Calories>{int(round(calories))}</Calories>")
    if avg_hr is not None:
        b.append(f"<AverageHeartRateBpm><Value>{avg_hr}</Value></AverageHeartRateBpm>")
    if max_hr is not None:
        b.append(f"<MaximumHeartRateBpm><Value>{max_hr}</Value></MaximumHeartRateBpm>")
    b.append("<Intensity>Active</Intensity>")
    if avg_cad is not None:
        b.append(f"<Cadence>{min(avg_cad, 254)}</Cadence>")
    b.append(f"<TriggerMethod>{trigger}</TriggerMethod>")

    b.append("<Track>")
    for p in pts:
        b.append(_trackpoint_xml(p))
    b.append("</Track>")

    lx: list[str] = []
    if avg_speed is not None:
        lx.append(f"<ns3:AvgSpeed>{_num(avg_speed)}</ns3:AvgSpeed>")
    if avg_cad is not None:
        lx.append(f"<ns3:AvgBikeCadence>{min(avg_cad, 254)}</ns3:AvgBikeCadence>")
    if avg_pw is not None:
        lx.append(f"<ns3:AvgWatts>{avg_pw}</ns3:AvgWatts>")
    if max_pw is not None:
        lx.append(f"<ns3:MaxWatts>{max_pw}</ns3:MaxWatts>")
    if lx:
        b.append("<Extensions><ns3:LX>" + "".join(lx) + "</ns3:LX></Extensions>")

    b.append("</Lap>")
    return "\n".join(b)


def _trackpoint_xml(p: TrackPoint) -> str:
    b: list[str] = ["<Trackpoint>"]
    b.append(f"<Time>{_iso(p.time)}</Time>")
    if p.lat is not None and p.lon is not None:
        b.append(
            "<Position>"
            f"<LatitudeDegrees>{_num(p.lat)}</LatitudeDegrees>"
            f"<LongitudeDegrees>{_num(p.lon)}</LongitudeDegrees>"
            "</Position>"
        )
    if p.altitude_m is not None:
        b.append(f"<AltitudeMeters>{_num(p.altitude_m)}</AltitudeMeters>")
    if p.distance_m is not None:
        b.append(f"<DistanceMeters>{_num(p.distance_m)}</DistanceMeters>")
    if p.heartrate is not None:
        b.append(f"<HeartRateBpm><Value>{p.heartrate}</Value></HeartRateBpm>")
    if p.cadence is not None:
        b.append(f"<Cadence>{min(p.cadence, 254)}</Cadence>")
    ext: list[str] = []
    if p.speed_ms is not None:
        ext.append(f"<ns3:Speed>{_num(p.speed_ms)}</ns3:Speed>")
    if p.power_w is not None:
        ext.append(f"<ns3:Watts>{p.power_w}</ns3:Watts>")
    if ext:
        b.append("<Extensions><ns3:TPX>" + "".join(ext) + "</ns3:TPX></Extensions>")
    b.append("</Trackpoint>")
    return "".join(b)


def _has_distance(act: Activity) -> bool:
    return any(p.distance_m for p in act.points)


def _first_time(act: Activity):
    for p in act.points:
        if p.time:
            return p.time
    return None


def _elapsed_seconds(pts: list[TrackPoint]):
    ts = [p.time for p in pts if p.time]
    if len(ts) < 2:
        return 0
    return (ts[-1] - ts[0]).total_seconds()


def _delta_distance(pts: list[TrackPoint]):
    ds = [p.distance_m for p in pts if p.distance_m is not None]
    if len(ds) < 2:
        return ds[0] if ds else None
    return ds[-1] - ds[0]
