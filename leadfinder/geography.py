"""CEP resolution and strict radial filtering; no location fallback on failure."""

import json
import math
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GeographyError(ValueError):
    pass


@dataclass(frozen=True)
class SearchArea:
    postcode: str
    address: str
    latitude: float
    longitude: float
    radius_km: float = 5

    def with_radius(self, radius):
        return replace(self, radius_km=radius)


def normalize_postcode(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{5}-?\d{3}', value.strip()):
        raise GeographyError('Informe um CEP válido com 8 dígitos.')
    return re.sub(r'\D', '', value)


def distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(a)))


def valid_coordinates(latitude, longitude):
    return (type(latitude) in (float, int) and type(longitude) in (float, int)
            and math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180)


class PostcodeResolver:
    def __init__(self, headless=True, channel=None, geocoder=None):
        self.headless, self.channel, self.geocoder = headless, channel, geocoder

    @lru_cache(maxsize=128)
    def resolve(self, postcode):
        postcode = normalize_postcode(postcode)
        request = Request(f'https://brasilapi.com.br/api/cep/v2/{postcode}', headers={'User-Agent': 'LeadFinder/0.2', 'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=12) as response:
                data = json.load(response)
        except HTTPError as error:
            if error.code in (400, 404):
                raise GeographyError('CEP não encontrado. Confira os dígitos.') from error
            raise GeographyError('O serviço de CEP está indisponível. Tente novamente.') from error
        except (URLError, TimeoutError, ValueError, OSError) as error:
            raise GeographyError('Não foi possível consultar o CEP. Verifique a conexão e tente novamente.') from error
        try:
            address = ', '.join(str(data[k]) for k in ('street', 'neighborhood', 'city', 'state') if data.get(k))
            if not address or str(data.get('cep', '')).replace('-', '') != postcode:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise GeographyError('O serviço não confirmou o endereço deste CEP. Confira os dígitos.')
        # CEP providers may return the city's center even for a street-specific CEP.
        # Resolve the exact postal area in Maps instead of trusting that fallback.
        geocoder = self.geocoder
        if geocoder is None:
            from leadfinder.collectors.geocoding import MapsPostcodeGeocoder
            geocoder = MapsPostcodeGeocoder(self.headless, self.channel)
        latitude, longitude = geocoder.coordinates(postcode)
        if not valid_coordinates(latitude, longitude):
            raise GeographyError('Não foi possível confirmar as coordenadas do CEP.')
        return SearchArea(postcode, address, latitude, longitude)
