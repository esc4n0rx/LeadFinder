"""Offline Chromium fixtures for delayed place hydration and explicit phone links."""
import json
from playwright.sync_api import sync_playwright
from leadfinder.collectors.google_maps import GoogleMapsCollector,EXTRACT_PLACE
from leadfinder.collectors.parsing import parse_place
from leadfinder.services import CollectionStopped
from tests.test_geocoding import PLACE,SEARCH

def main():
    with sync_playwright() as p:
        browser=p.chromium.launch()
        try:
            page=browser.new_page()
            html='<h1 class="DUwDvf">Mibi Burguer</h1><button data-item-id="address">Rua Marupiara</button><meta property="og:image" content="https://maps.google.com/staticmap?center=-22.9141308,-43.4459821"><script>setTimeout(()=>{history.replaceState(null,"",'+json.dumps(PLACE)+');document.body.insertAdjacentHTML("beforeend",\'<button data-item-id="phone:tel:021994825634" aria-label="Telefone: (21) 99482-5634">Telefone</button>\');},500);</script>'
            page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
            page.goto(SEARCH,wait_until='domcontentloaded')
            assert page.evaluate(EXTRACT_PLACE)['phone'] is None
            GoogleMapsCollector._wait_place_location(page,lambda:None)
            lead=parse_place(page.evaluate(EXTRACT_PLACE),page.url)
            assert lead.phone=='(21) 99482-5634' and lead.latitude==-22.8516757
            page.set_content('<h1 class="DUwDvf">Mibi Burguer</h1><a href="tel:021994825634" aria-label="Ligar para número de telefone">Ligar</a>')
            assert parse_place(page.evaluate(EXTRACT_PLACE),PLACE).phone=='21994825634'
            page.set_content('<h1 class="DUwDvf">Mibi Burguer</h1><button data-item-id="phone:tel:021994825634" aria-label="Ligar">&#xe000; (21) 99482-5634</button>')
            assert parse_place(page.evaluate(EXTRACT_PLACE),PLACE).phone=='(21) 99482-5634'
            page.set_content('<h1 class="DUwDvf">Sem contato</h1><div>Rua Um, 219994825634 · 125 avaliações</div>')
            assert parse_place(page.evaluate(EXTRACT_PLACE),PLACE).phone is None
            def cancel():raise CollectionStopped()
            try:GoogleMapsCollector._wait_place_location(page,cancel)
            except CollectionStopped:pass
            else:raise AssertionError('Cancellation was ignored')
            print('PASS offline Maps DOM: heading before URL/phone, point hydration, explicit tel fallback, no guessing from unrelated digits, cancellation.')
        finally:browser.close()

if __name__=='__main__':main()
