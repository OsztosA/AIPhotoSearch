import re
from datetime import datetime

from PIL import Image, ExifTags
import pillow_heif

pillow_heif.register_heif_opener()

_LI = re.compile(r"<rdf:li[^>]*>([^<]+)</rdf:li>")
_BLOCK = re.compile(r"<(dc:subject|lr:hierarchicalSubject|digiKam:TagsList)\b.*?</\1>", re.S)


def _clean(v):
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v[:64].hex()
    if isinstance(v, (tuple, list)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


_XP = {"XPTitle", "XPComment", "XPAuthor", "XPKeywords", "XPSubject"}


def _named(ifd) -> dict:
    out = {}
    for k, v in ifd.items():
        name = ExifTags.TAGS.get(k, str(k))
        if name in _XP and isinstance(v, bytes):
            v = v.decode("utf-16-le", "replace").rstrip("\x00")
        out[name] = _clean(v)
    return out


def _alt(xmp: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b.*?</{tag}>", xmp, re.S)
    li = _LI.findall(m.group(0)) if m else []
    return li[0].strip() if li else ""


def _keywords(exif: dict, xmp: str) -> list[str]:
    words: list[str] = []
    raw = exif.get("XPKeywords")
    if isinstance(raw, str):
        words += raw.split(";")
    for block in _BLOCK.finditer(xmp):
        for li in _LI.findall(block.group(0)):
            words += re.split(r"[|/]", li)
    seen, out = set(), []
    for w in (w.strip() for w in words):
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out


def extract(path: str) -> dict:
    """Return {'exif': {...}, 'xmp': str, 'keywords': [...], 'taken': 'ISO or None'}."""
    with Image.open(path) as img:
        exif = img.getexif()
        data = _named(exif)
        for name, tag in (("ExifIFD", 0x8769), ("GPS", 0x8825)):
            try:
                ifd = exif.get_ifd(tag)
            except Exception:
                ifd = {}
            if ifd:
                if name == "GPS":
                    data["GPSInfo"] = {ExifTags.GPSTAGS.get(k, str(k)): _clean(v) for k, v in ifd.items()}
                else:
                    data.update(_named(ifd))
        xmp = img.info.get("xmp") or b""
        if isinstance(xmp, bytes):
            xmp = xmp.decode("utf-8", "replace")
        if not xmp:
            try:
                xmp = img.info.get("XML:com.adobe.xmp", "") or ""
            except Exception:
                xmp = ""
    data.pop("MakerNote", None)
    data.pop("UserComment", None)
    taken = None
    for key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        v = data.get(key)
        if isinstance(v, str):
            try:
                taken = datetime.strptime(v.strip("\x00 "), "%Y:%m:%d %H:%M:%S").isoformat()
                break
            except ValueError:
                continue
    title = data.get("XPTitle") or _alt(xmp, "dc:title")
    description = data.get("ImageDescription") or _alt(xmp, "dc:description")
    return {"exif": data, "xmp": xmp, "keywords": _keywords(data, xmp), "taken": taken,
            "title": title or "", "description": description or ""}


