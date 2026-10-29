"""Maps browser adapter. Reads visible public place pages, without login or bypasses."""

from urllib.parse import quote
import math

from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright

from leadfinder.collectors.parsing import parse_place, place_identity, place_coordinates
from leadfinder.services import CollectionStopped


class CollectorError(Exception):
    """An actionable collection error safe to display in the UI."""


# Kept in one adapter because Maps markup can change independently of the app.
EXTRACT_PLACE = """() => {
    const text = s => document.querySelector(s)?.textContent?.trim() || null;
    const label = s => document.querySelector(s)?.getAttribute('aria-label') || text(s);
    const reviews = document.querySelector('button[jsaction*="moreReviews"]');
    const ratingLabel = document.querySelector('[role="img"][aria-label*="estrelas"], [role="img"][aria-label*="stars"]')?.getAttribute('aria-label');
    const hours = document.querySelector('[data-item-id="oh"]');
    const hoursLabel = hours?.getAttribute('aria-label');
    const clean = value => value.replace(/[\uE000-\uF8FF]/g, '').replace(/\\s+/g, ' ').trim();
    const phoneNode = document.querySelector('[data-item-id^="phone:tel:"]');
    const phone = [phoneNode?.getAttribute('aria-label'), phoneNode?.innerText && clean(phoneNode.innerText),
        document.querySelector('a[href^="tel:"]')?.getAttribute('href')?.slice(4)]
        .find(value => typeof value === 'string' && value.replace(/\\D/g, '').length >= 8) || null;
    const week = Array.from(document.querySelectorAll('table tr, [role="row"]'))
        .filter(row => /segunda|terça|quarta|quinta|sexta|sábado|domingo|monday|tuesday|wednesday|thursday|friday|saturday|sunday/i.test(row.innerText))
        .map(row => Array.from(row.querySelectorAll('td, [role="cell"]')).map(cell => clean(cell.innerText)).filter(Boolean).join(' · '))
        .filter(Boolean);
    return {
        name: text('h1.DUwDvf') || text('h1'),
        category: text('button[jsaction*="category"]'),
        phone: phone,
        address: label('[data-item-id="address"]'),
        website: document.querySelector('a[data-item-id="authority"]')?.href || null,
        rating: ratingLabel || text('.F7nice span[aria-hidden="true"]'),
        review_count: reviews?.getAttribute('aria-label') || reviews?.textContent || label('.F7nice span[aria-label*="avalia"]') || label('.F7nice span[aria-label*="review"]'),
        hours: week.length ? [...new Set(week)].join('\\n') : hoursLabel || hours?.innerText || label('[data-item-id="oh"] button'),
        plus_code: label('[data-item-id="oloc"]'),
        description: text('.PYvSYb') || text('.WeS02d'),
        price: text('span[aria-label*="Preço"], span[aria-label*="Price"]'),
        attributes: Array.from(document.querySelectorAll('.E0DTEd .iP2t7d')).map(el => el.innerText.trim()).filter(Boolean),
        business_status: text('.ZDu9vd .fCEPlc')
    };
}"""


class GoogleMapsCollector:
    def __init__(self, headless=True, channel=None):
        self.headless = headless
        self.channel = channel

    def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel, area=None):
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=self.headless, channel=self.channel)
            except PlaywrightError as error:
                raise CollectorError("Navegador indisponível. Execute: python -m playwright install chromium. Consulte o README para usar Chrome/Edge.") from error
            try:
                context = browser.new_context(locale="pt-BR", viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page.set_default_timeout(8000)
                query = f"{term} {location}".strip()
                viewport = ''
                if area:
                    zoom = max(8, min(16, round(math.log2(40075 * math.cos(math.radians(area.latitude)) / (area.radius_km * 2)))))
                    viewport = f'@{area.latitude},{area.longitude},{zoom}z/'
                page.goto(f"https://www.google.com/maps/search/{quote(query, safe='')}/{viewport}?hl=pt-BR", wait_until="domcontentloaded", timeout=45000)
                self._consent(page)
                self._check_blocked(page)
                check_cancel()
                links = self._discover(page, limit, progress, check_cancel)
                progress(found=len(links), message=f"{len(links)} local(is) encontrado(s). Lendo os detalhes…")
                for url in links:
                    check_cancel()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        self._check_blocked(page)
                        page.locator("h1.DUwDvf").wait_for(timeout=15000)
                        self._wait_place_location(page,check_cancel)
                        # Phone and address load after the heading.
                        try:
                            page.locator('[data-item-id="address"], [data-item-id^="phone:tel:"], [data-item-id="oloc"]').first.wait_for(timeout=5000)
                        except PlaywrightTimeout:
                            pass
                        # Expand the weekly schedule when the public page offers it.
                        hours_button = page.locator('[data-item-id="oh"]').first
                        if hours_button.count():
                            try:
                                hours_button.click(timeout=2000)
                                page.locator('table.eK4R0e').wait_for(timeout=2000)
                            except PlaywrightError:
                                pass
                        check_cancel()
                        raw = page.evaluate(EXTRACT_PLACE)
                        if not raw.get('phone'):
                            # An address is not proof that the contact row has finished loading.
                            try:
                                page.locator('[data-item-id^="phone:tel:"], a[href^="tel:"]').first.wait_for(timeout=3000)
                                raw=page.evaluate(EXTRACT_PLACE)
                            except PlaywrightTimeout:
                                pass
                            check_cancel()
                        on_lead(parse_place(raw, page.url))
                    except (CollectorError, CollectionStopped):
                        raise
                    except (PlaywrightError, ValueError):
                        on_error("Não foi possível ler um estabelecimento. Continuando a coleta…")
                    page.wait_for_timeout(1000)
            except PlaywrightTimeout as error:
                raise CollectorError("O Google Maps demorou para responder. Verifique a conexão e tente novamente.") from error
            except PlaywrightError as error:
                raise CollectorError("O navegador perdeu a conexão com o Google Maps. Os leads já salvos foram preservados.") from error
            finally:
                browser.close()

    @staticmethod
    def _wait_place_location(page,check_cancel):
        # A single search result can show its heading/phone while its URL is still
        # /maps/search/. Wait for the selected place before deriving identity/point.
        for _ in range(3):
            check_cancel()
            try:
                page.wait_for_url(lambda url:place_coordinates(str(url)) is not None,timeout=4000)
                return
            except PlaywrightTimeout:
                pass
        # Genuine missing coordinates remain explicit and the radius filter stays strict.
        check_cancel()

    @staticmethod
    def _consent(page):
        if "consent.google." not in page.url and not page.locator('form[action*="consent"]').count():
            return
        button = page.get_by_role("button", name="Rejeitar tudo", exact=True)
        if not button.count():
            button = page.get_by_role("button", name="Reject all", exact=True)
        if button.count():
            button.first.click()
            page.wait_for_load_state("domcontentloaded")
        else:
            raise CollectorError("O Google exibiu uma tela de consentimento não reconhecida. Tente com LEADFINDER_HEADLESS=false.")

    @staticmethod
    def _check_blocked(page):
        if "/sorry/" in page.url or page.locator('iframe[src*="recaptcha"], form#captcha-form').count():
            raise CollectorError("O Google solicitou uma verificação (CAPTCHA). A coleta foi interrompida; tente novamente mais tarde.")

    def _discover(self, page, limit, progress, check_cancel):
        try:
            page.locator('[role="feed"], h1.DUwDvf').first.wait_for(timeout=20000)
        except PlaywrightTimeout:
            self._check_blocked(page)
            body = page.locator("body").inner_text()
            if any(text in body.lower() for text in ("nenhum resultado", "no results", "não encontrou")):
                return []
            raise CollectorError("Não foi possível reconhecer os resultados do Maps. A página pode ter mudado ou solicitado uma verificação.")
        feed = page.locator('[role="feed"]').first
        if not feed.count():
            return [page.url]
        links, seen = [], set()
        stalls = 0
        # Both a stall bound and an iteration bound prevent endless scrolling.
        for _ in range(100):
            check_cancel()
            self._check_blocked(page)
            previous = len(links)
            for url in feed.locator('a[href*="/maps/place/"]').evaluate_all("els => els.map(el => el.href)"):
                identity = place_identity(url)
                if identity not in seen:
                    seen.add(identity)
                    links.append(url)
                    if len(links) >= limit:
                        return links
            progress(found=len(links), message=f"Encontrando estabelecimentos… {len(links)} até agora.")
            stalls = stalls + 1 if len(links) == previous else 0
            if stalls >= 4:
                break
            feed.evaluate("el => { el.scrollTop = el.scrollHeight; }")
            page.wait_for_timeout(1500)
        return links
