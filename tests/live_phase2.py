"""Opt-in live geographic smoke check. Uses a temporary database, never the user's base."""

import tempfile
import time
from pathlib import Path

from leadfinder import create_app
from leadfinder.geography import distance_km


def main():
    with tempfile.TemporaryDirectory() as directory:
        app = create_app({'DATABASE':str(Path(directory)/'live.sqlite3')})
        area = app.extensions['postcode_resolver'].resolve('21235112').with_radius(5)
        print(f'CEP confirmed: {area.postcode} / {area.address} / {area.latitude}, {area.longitude} / {area.radius_km} km',flush=True)
        service, repo = app.extensions['search_service'], app.extensions['repository']
        search = service.start('cafeterias',area.address,3,workspace_id=1,area=area,require_phone=True)
        previous = None
        deadline = time.monotonic()+240
        while time.monotonic() < deadline:
            current = repo.get_search(search['id'])
            if current['message'] != previous:
                print(current['message'],flush=True)
                previous = current['message']
            if current['status'] not in ('queued','running'):
                break
            time.sleep(1)
        else:
            repo.update_search(search['id'],cancel_requested=1)
            raise RuntimeError('Live check timed out; cancellation requested')
        leads = repo.list_leads(workspace_id=1)['items']
        if current['status'] not in ('completed','partial') or not leads:
            raise RuntimeError(f'Live collection did not produce verified leads: {current["message"]}')
        for lead in leads:
            distance = distance_km(area.latitude,area.longitude,lead['latitude'],lead['longitude'])
            assert lead['phone'] and distance <= area.radius_km
            print(f'Accepted: {lead["name"]} / phone present / {distance:.2f} km',flush=True)
        print(f'PASS live: {len(leads)} accepted, {current["skipped_phone"]} without phone, {current["skipped_distance"]} outside radius, {current["skipped_coordinates"]} without coordinates',flush=True)


if __name__ == '__main__':
    main()
