"""Postal point regression: Maps headings can precede URL hydration by seconds."""
import unittest
from unittest.mock import MagicMock,patch
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from leadfinder.collectors.geocoding import MapsPostcodeGeocoder,postcode_point
from leadfinder.geography import GeographyError,distance_km

PLACE='https://www.google.com/maps/place/Rocha+Miranda,+Rio+de+Janeiro+-+RJ,+21540-550/@-22.8515951,-43.34298,17z/data=!3m1!4b1!4m6!3m5!1splace!8m2!3d-22.8516757!4d-43.3428934!16s%2Fg%2Fexample?hl=pt-BR'
SEARCH='https://www.google.com/maps/search/21540-550%20Brasil/?hl=pt-BR'

class PostalPointTest(unittest.TestCase):
    def test_uses_selected_postal_point_instead_of_camera_or_stale_preview(self):
        point=postcode_point(PLACE,'21540550')
        self.assertEqual(point,(-22.8516757,-43.3428934))
        self.assertGreater(distance_km(*point,-22.9141308,-43.4459821),10)
        self.assertIsNone(postcode_point(SEARCH,'21540550'))
        self.assertIsNone(postcode_point(PLACE.split('/data=')[0],'21540550'))
    def test_rejects_different_postcode_invalid_and_ambiguous_coordinates(self):
        self.assertIsNone(postcode_point(PLACE,'21235112'))
        self.assertIsNone(postcode_point(PLACE.replace('!3d-22.8516757','!3d-222.8516757'),'21540550'))
        self.assertIsNone(postcode_point(PLACE.replace('?hl','!3d-22!4d-43?hl'),'21540550'))
        self.assertEqual(postcode_point(PLACE.replace('21540-550','21540%2D550'),'21540550'),(-22.8516757,-43.3428934))
    def test_heading_does_not_allow_early_stale_metadata(self):
        manager=MagicMock();browser=manager.__enter__.return_value.chromium.launch.return_value
        page=browser.new_page.return_value;page.url=SEARCH
        # This was the old source, returned even after Maps had loaded the correct area.
        page.locator.return_value.get_attribute.return_value='https://maps.google.com/maps/api/staticmap?center=-22.9141308%2C-43.4459821&zoom=10'
        def hydrate(predicate,**kwargs):
            self.assertFalse(predicate(page.url));page.url=PLACE;self.assertTrue(predicate(page.url))
        page.wait_for_url.side_effect=hydrate
        with patch('leadfinder.collectors.geocoding.sync_playwright',return_value=manager),patch('leadfinder.collectors.geocoding.GoogleMapsCollector._consent'),patch('leadfinder.collectors.geocoding.GoogleMapsCollector._check_blocked'):
            self.assertEqual(MapsPostcodeGeocoder().coordinates('21540-550'),(-22.8516757,-43.3428934))
        page.wait_for_url.assert_called_once();page.locator.assert_not_called();browser.close.assert_called_once()
        self.assertEqual(page.get_by_role.call_count,2)
    def test_never_falls_back_to_metadata_if_postal_place_does_not_load(self):
        manager=MagicMock();browser=manager.__enter__.return_value.chromium.launch.return_value
        page=browser.new_page.return_value;page.url=SEARCH
        page.wait_for_url.side_effect=PlaywrightTimeout('not loaded')
        with patch('leadfinder.collectors.geocoding.sync_playwright',return_value=manager),patch('leadfinder.collectors.geocoding.GoogleMapsCollector._consent'),patch('leadfinder.collectors.geocoding.GoogleMapsCollector._check_blocked'):
            with self.assertRaises(GeographyError):MapsPostcodeGeocoder().coordinates('21540550')
        page.locator.assert_not_called();browser.close.assert_called_once()

    def test_tel_link_fallback_does_not_keep_brazilian_trunk_prefix(self):
        from leadfinder.collectors.parsing import parse_place
        lead=parse_place({'name':'Teste','phone':'021994825634'},PLACE)
        self.assertEqual(lead.phone,'21994825634')
        self.assertEqual(parse_place({'name':'Teste','phone':'+5521994825634'},PLACE).phone,'+5521994825634')

if __name__=='__main__':unittest.main()
