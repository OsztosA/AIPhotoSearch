from datetime import datetime

try:
    import reverse_geocoder
except ImportError:
    reverse_geocoder = None
try:
    import pycountry
except ImportError:
    pycountry = None

TIME_OF_DAY = ["early morning", "morning", "afternoon", "evening", "night", "late night"]


def time_of_day(hour: int) -> str:
    if hour < 5:
        return "late night"
    if hour < 8:
        return "early morning"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def _coord(value, ref):
    try:
        d, m, s = (float(x) for x in value)
        deg = d + m / 60 + s / 3600
    except (TypeError, ValueError):
        return None
    return -deg if str(ref).upper() in ("S", "W") else deg


def gps_coords(exif: dict):
    gps = exif.get("GPSInfo") or {}
    lat = _coord(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    lon = _coord(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    return (lat, lon) if lat is not None and lon is not None else None


def locate(exif: dict):
    """Return (city, country) using offline reverse geocoding; empty strings if unavailable."""
    coords = gps_coords(exif)
    if not coords or reverse_geocoder is None:
        return "", ""
    try:
        hit = reverse_geocoder.search([coords], mode=1, verbose=False)[0]
    except Exception:
        return "", ""
    cc = hit.get("cc", "")
    country = cc
    if pycountry and cc:
        c = pycountry.countries.get(alpha_2=cc)
        country = c.name if c else cc
    return hit.get("name", ""), country


def build(path: str, name: str, info: dict) -> tuple[str, dict]:
    """Procedural (no LLM) description plus the exact metadata to store in the vector DB."""
    exif = info["exif"]
    meta = {"file_path": path, "name": name}
    city, country = locate(exif)
    place = ", ".join(p for p in (city, country) if p)
    if city:
        meta["city"] = city
    if country:
        meta["country"] = country

    make = str(exif.get("Make") or "").strip()
    model = str(exif.get("Model") or "").strip()
    camera = model if model.lower().startswith(make.lower()) else f"{make} {model}".strip()
    if camera:
        meta["camera_model"] = camera
    lens = str(exif.get("LensModel") or "").strip()
    if lens:
        meta["lens"] = lens

    text = "A photograph taken"
    if place:
        text += f" in {place}"
    taken = info["taken"]
    if taken:
        dt = datetime.fromisoformat(taken)
        tod = time_of_day(dt.hour)
        meta.update(year=dt.year, month=dt.month, day=dt.day, hour=dt.hour,
                    time_of_day=tod, taken_ts=int(dt.timestamp()))
        text += f" on {dt.strftime('%B %d, %Y')}, in the {tod} ({dt.strftime('%H:%M')})"
    text += "."

    words = list(info["keywords"])
    for extra in (info["title"], info["description"]):
        if extra and extra.lower() not in (w.lower() for w in words):
            words.append(extra)
    if words:
        text += " The image features the following subjects and concepts: " + ", ".join(words) + "."
    return text, meta
