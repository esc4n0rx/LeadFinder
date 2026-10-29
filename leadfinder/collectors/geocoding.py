"""Resolve a postal area's public Maps center, without reusing city centroids."""

import re
from urllib.parse import quote, unquote, urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from leadfinder.collectors.google_maps import CollectorError, GoogleMapsCollector
from leadfinder.collectors.parsing import place_coordinates
from leadfinder.geography import GeographyError, normalize_postcode


def postcode_point(url,postcode):
    """Only accept the selected postal place, never the camera or social preview."""
    parsed=urlsplit(url)
    path=unquote(parsed.path)
    formatted=postcode[:5]+'-'+postcode[5:]
    if not path.startswith('/maps/place/') or not re.search(r'(?<![0-9])'+re.escape(formatted)+r'(?![0-9])',path):
        return None
    return place_coordinates(url)


class MapsPostcodeGeocoder:
    def __init__(self, headless=True, channel=None):
        self.headless, self.channel = headless, channel

    def coordinates(self, postcode):
        postcode=normalize_postcode(postcode)
        formatted = postcode[:5] + '-' + postcode[5:]
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless, channel=self.channel, timeout=20000)
                try:
                    page = browser.new_page(locale='pt-BR')
                    page.set_default_timeout(12000)
                    page.goto('https://www.google.com/maps/search/' + quote(formatted+' Brasil', safe='') + '/?hl=pt-BR', wait_until='domcontentloaded', timeout=30000)
                    GoogleMapsCollector._consent(page)
                    GoogleMapsCollector._check_blocked(page)
                    page.get_by_role('heading', name=re.compile(r'^'+re.escape(formatted)+r'$')).wait_for()
                    # The heading arrives before Maps finishes selecting the postal place.
                    # og:image may permanently retain the initial regional viewport.
                    page.wait_for_url(lambda url:postcode_point(str(url),postcode) is not None,timeout=15000)
                    page.get_by_role('heading', name=re.compile(r'^'+re.escape(formatted)+r'$')).wait_for()
                    point=postcode_point(page.url,postcode)
                    if point is None:
                        raise ValueError()
                    return point
                finally:
                    browser.close()
        except CollectorError as error:
            raise GeographyError('Não foi possível confirmar o CEP no Maps: ' + str(error)) from error
        except (PlaywrightError, ValueError, TypeError) as error:
            raise GeographyError('Não foi possível localizar a área deste CEP no Maps. Confira o CEP ou tente novamente. Nenhuma busca sem raio foi iniciada.') from error
