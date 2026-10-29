"""Opt-in integration check. Reads up to three public places; never touches the catalog."""

import json
from pathlib import Path

from leadfinder.collectors.google_maps import GoogleMapsCollector


def main():
    leads, errors = [], []

    def save(lead):
        leads.append(lead.to_dict())
        print(json.dumps({"name": lead.name, "phone": lead.phone, "address": lead.address}, ensure_ascii=False), flush=True)

    GoogleMapsCollector().collect(
        "cafeterias", "Irajá, Rio de Janeiro", 3, save,
        lambda error: errors.append(error),
        lambda **values: print(json.dumps(values, ensure_ascii=False), flush=True),
        lambda: None,
    )
    output = Path("test-results")
    output.mkdir(exist_ok=True)
    (output / "live-maps.json").write_text(json.dumps({"leads": leads, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not leads:
        raise RuntimeError("No places collected during live check")
    print(f"LIVE CHECK: {len(leads)} place(s), {sum(bool(lead['phone']) for lead in leads)} with phone; {len(errors)} error(s)")


if __name__ == "__main__":
    main()
