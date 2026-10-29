"""Pure transformations for Google Maps public place fields."""

import hashlib
import re
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

from leadfinder.models import Lead
from leadfinder.geography import valid_coordinates


def safe_url(value):
    if not value:
        return None
    parsed = urlsplit(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def canonical_url(value):
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def place_identity(url):
    decoded = unquote(url)
    # Feature ID identifies the place independently of search viewport or name.
    match = re.search(r"!1s([^!/?]+)", decoded)
    if match:
        return match.group(1)
    query = parse_qs(urlsplit(url).query)
    for key in ("query_place_id", "cid"):
        if query.get(key):
            return f"{key}:{query[key][0]}"
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


def number(value, integer=False):
    if not value:
        return None
    match = re.search(r"[\d][\d.,\s]*", value)
    if not match:
        return None
    raw = match.group().strip()
    try:
        if integer:
            return int(re.sub(r"\D", "", raw))
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def clean_label(value, *prefixes):
    if not value:
        return None
    for prefix in prefixes:
        value = re.sub(rf"^{re.escape(prefix)}\s*:\s*", "", value, flags=re.I)
    return value.strip() or None


def place_coordinates(url):
    """Read the selected place point, never the map's @camera position."""
    path=unquote(urlsplit(url).path)
    if not path.startswith('/maps/place/'):
        return None
    points={(float(lat),float(lon)) for lat,lon in re.findall(r'!3d(-?[0-9]+(?:\.[0-9]+)?)!4d(-?[0-9]+(?:\.[0-9]+)?)',path)}
    if len(points)!=1:
        return None
    latitude,longitude=points.pop()
    return (latitude,longitude) if valid_coordinates(latitude,longitude) else None


def parse_place(raw, url):
    name = (raw.get("name") or "").strip()
    if not name:
        raise ValueError("A página não contém um nome de estabelecimento.")
    coordinates = place_coordinates(url)
    phone=clean_label(raw.get("phone"),"Telefone","Phone")
    if phone and re.fullmatch(r"0[0-9]{10,11}",phone):
        phone=phone[1:]  # Maps tel: links may include the Brazilian trunk prefix.
    website = raw.get("website")
    if website and "google.com/url?" in website:
        website = parse_qs(urlsplit(website).query).get("q", [website])[0]
    return Lead(
        identity=place_identity(url), name=name, maps_url=url,
        category=raw.get("category") or None,
        phone=phone,
        address=clean_label(raw.get("address"), "Endereço", "Address"),
        website=safe_url(website), rating=number(raw.get("rating")),
        review_count=number(raw.get("review_count"), integer=True),
        hours=raw.get("hours") or None,
        plus_code=clean_label(raw.get("plus_code"), "Plus code", "Código Plus"),
        latitude=coordinates[0] if coordinates else None,
        longitude=coordinates[1] if coordinates else None,
        details={key: raw[key] for key in ("description", "price", "attributes", "business_status") if raw.get(key)},
    )
