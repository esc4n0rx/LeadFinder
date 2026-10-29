"""Domain records shared by collectors and persistence."""

from dataclasses import asdict, dataclass, field


@dataclass
class Lead:
    identity: str
    name: str
    maps_url: str
    category: str | None = None
    phone: str | None = None
    address: str | None = None
    website: str | None = None
    rating: float | None = None
    review_count: int | None = None
    hours: str | None = None
    plus_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)
