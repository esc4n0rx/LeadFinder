"""Optional local browser smoke test; no requests to Google, no real lead database."""

import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from leadfinder import create_app
from leadfinder.collectors.google_maps import EXTRACT_PLACE
from leadfinder.collectors.parsing import parse_place
from leadfinder.models import Lead
from leadfinder.geography import SearchArea


class FixtureCollector:
    def collect(self, term, location, limit, on_lead, on_error, progress, check_cancel, area=None):
        progress(found=2)
        for index, name in enumerate(("Café Aurora (teste)", '<script>alert("xss")</script>')):
            time.sleep(.3)
            check_cancel()
            on_lead(Lead(
                identity=f"fixture-{index}", name=name, maps_url="https://www.google.com/maps/place/Teste",
                category="Cafeteria", phone="(21) 99999-0000", address="Rua de Exemplo, 10, Rio de Janeiro",
                website="https://example.org", rating=4.8, review_count=128,
                hours="Segunda a sexta: 08:00–18:00", details={"description": "Dados fictícios apenas para teste."},
                latitude=-22.8366, longitude=-43.3252,
            ))


def main():
    output = Path("test-results")
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        class FixtureResolver:
            def resolve(self, postcode):
                return SearchArea(postcode,'Irajá, Rio de Janeiro, RJ',-22.8366,-43.3252)
        app = create_app({"DATABASE": str(Path(directory) / "smoke.sqlite3")}, collector_factory=FixtureCollector, postcode_resolver=FixtureResolver())
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", color_scheme="light")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{server.server_port}")
                page.get_by_role('link', name='Criar minha conta').wait_for()
                page.screenshot(path=str(output/'welcome-light.png'),full_page=True)
                page.get_by_role('link', name='Criar minha conta').click()
                page.get_by_label('Nome completo',exact=True).fill('Browser Tester')
                page.get_by_label('Nome de usuário',exact=True).fill('browser.tester')
                page.get_by_label('Email',exact=True).fill('browser@example.org')
                page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_label('Confirmar senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Criar conta',exact=True).click()
                page.get_by_label('Nome do workspace').fill('Workspace de teste')
                page.screenshot(path=str(output/'workspace-setup.png'),full_page=True)
                page.get_by_role('button',name='Criar workspace').click()
                page.get_by_role("heading", name="Seu próximo contato começa aqui.").wait_for()
                page.evaluate('document.fonts.ready.then(() => true)')
                assert page.evaluate('document.fonts.check("500 14px Geist")'), 'Local Geist font did not load'
                assert page.locator('html').get_attribute('data-theme') == 'light'
                page.screenshot(path=str(output / "desktop-empty.png"), full_page=True)
                page.screenshot(path=str(output / "desktop-light.png"), full_page=True)
                theme = page.get_by_role('switch', name='Modo escuro')
                theme.click()
                assert theme.get_attribute('aria-checked') == 'true'
                assert page.locator('html').get_attribute('data-theme') == 'dark'
                page.screenshot(path=str(output / 'desktop-dark.png'), full_page=True)
                page.reload()
                page.get_by_role('heading', name='Seu próximo contato começa aqui.').wait_for()
                assert page.locator('html').get_attribute('data-theme') == 'dark', 'Theme preference was not persisted'
                page.get_by_role('switch', name='Modo escuro').click()
                assert page.locator('html').get_attribute('data-theme') == 'light'
                page.get_by_role('button', name='Buscar no catálogo', exact=True).click()
                assert page.locator('#directory-query').evaluate('el => el === document.activeElement')
                page.get_by_role('button', name='Nova busca', exact=True).click()
                assert page.locator('#term').evaluate('el => el === document.activeElement')
                page.get_by_label("O que você procura?").fill("Cafeterias")
                page.get_by_label("Em qual região?").fill("Rio de Janeiro")
                page.get_by_label('CEP de referência').fill('21235-112')
                page.get_by_role('button',name='Confirmar CEP').click()
                page.locator('#postcode-preview').wait_for(state='visible')
                assert 'Irajá' in page.locator('#postcode-preview').inner_text()
                page.get_by_role("button", name="Encontrar leads").click()
                page.locator("#directory-body tr:not(.directory-group)").nth(1).wait_for(timeout=15000)
                assert page.locator("#stat-total").inner_text() == "2"
                assert page.locator("#directory-body script").count() == 0
                page.screenshot(path=str(output / "desktop-catalog.png"), full_page=True)
                page.get_by_role('switch', name='Modo escuro').click()
                page.screenshot(path=str(output / 'desktop-catalog-dark.png'), full_page=True)
                page.get_by_role("button", name="Detalhes de Café Aurora (teste)").click()
                page.get_by_role("heading", name="Café Aurora (teste)").wait_for()
                assert page.locator("#dossier-content").inner_text().count("(21) 99999-0000") == 1
                page.screenshot(path=str(output / "desktop-details.png"))
                page.keyboard.press("Escape")
                page.get_by_label("Buscar lead").fill("inexistente")
                page.get_by_role("heading", name="Nenhum lead encontrado").wait_for()
                page.get_by_label("Buscar lead").fill("")
                page.locator("#directory-body tr:not(.directory-group)").nth(1).wait_for()
                page.get_by_role("button", name="Histórico de buscas").click()
                assert page.locator('#page-title').inner_text() == 'Histórico de buscas'
                assert page.locator('.search-panel').is_hidden()
                page.locator(".status-badge.completed").wait_for(timeout=15000)
                page.screenshot(path=str(output / "desktop-history.png"), full_page=True)
                page.get_by_role("button", name="Ver leads").click()
                page.locator("#directory-body tr:not(.directory-group)").nth(1).wait_for()
                assert page.locator('.search-panel').is_hidden()
                page.set_viewport_size({"width": 390, "height": 844})
                page.screenshot(path=str(output / "mobile-catalog.png"), full_page=True)
                page.get_by_role('switch', name='Modo escuro').click()
                page.screenshot(path=str(output / 'mobile-light.png'), full_page=True)
                overflow = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(el => {
                    const rect = el.getBoundingClientRect();
                    return rect.width && rect.right > innerWidth && !el.closest('.table-scroll');
                }).map(el => ({tag: el.tagName, cls: el.className, right: el.getBoundingClientRect().right}))""")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Page overflows on mobile: {overflow}"
                for width in (320, 768, 1024, 1920):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow at {width}px'
                dark_context = browser.new_context(color_scheme='dark')
                system_page = dark_context.new_page()
                system_page.goto(f'http://127.0.0.1:{server.server_port}')
                assert system_page.locator('html').get_attribute('data-theme') == 'dark', 'System theme was ignored'
                dark_context.close()
                blocked_context = browser.new_context(color_scheme='light')
                blocked_context.add_init_script("Object.defineProperty(window, 'localStorage', {get() {throw new Error('Storage unavailable')}})")
                blocked_page = blocked_context.new_page()
                blocked_page.goto(f'http://127.0.0.1:{server.server_port}')
                blocked_page.get_by_role('switch', name='Modo escuro').click()
                assert blocked_page.locator('html').get_attribute('data-theme') == 'dark', 'Theme toggle needs storage access'
                blocked_context.close()
                assert not errors, errors
                fixture = browser.new_page()
                fixture.set_content('''<h1 class="DUwDvf">Café de teste</h1>
                    <button jsaction="pane.category">Cafeteria</button>
                    <button data-item-id="phone:tel:21999990000" aria-label="Telefone: (21) 99999-0000"></button>
                    <button data-item-id="address" aria-label="Endereço: Rua Um, 10"></button>
                    <a data-item-id="authority" href="https://example.org">Site</a>
                    <span role="img" aria-label="4,8 estrelas"></span>
                    <button jsaction="pane.moreReviews" aria-label="128 avaliações"></button>
                    <table class="eK4R0e"><tr><td>segunda-feira</td><td>08:00–18:00</td></tr></table>''')
                lead = parse_place(fixture.evaluate(EXTRACT_PLACE), "https://www.google.com/maps/place/Teste")
                assert lead.phone == "(21) 99999-0000"
                assert (lead.rating, lead.review_count) == (4.8, 128)
                assert "08:00–18:00" in lead.hours
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('.account-menu summary').click()
                page.get_by_role('link',name='Ajustes do perfil').click()
                page.get_by_label('Nome completo',exact=True).fill('Tester Updated')
                page.get_by_label('Senha atual',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Salvar alterações').click()
                page.get_by_role('status').filter(has_text='Perfil atualizado').wait_for()
                page.screenshot(path=str(output/'profile.png'),full_page=True)
                page.get_by_role('button',name='Estabelecimentos',exact=False).click()
                page.locator('.account-menu summary').click()
                page.get_by_role('button',name='Sair da conta').click()
                page.get_by_role('link',name='Já tenho conta').click()
                page.get_by_label('Nome de usuário',exact=True).fill('browser.tester')
                page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Entrar',exact=True).click()
                page.get_by_role('heading',name='Estabelecimentos',exact=True).wait_for()
                page.get_by_role('button',name='Leads',exact=True).click()
                assert page.locator('.workspace-brand').inner_text().startswith('Workspace de teste')
                page.locator('#directory-body tr:not(.directory-group)').nth(1).wait_for()
                assert not errors, errors
                browser.close()
                print("PASS: welcome, registration, workspace setup, CEP/radius/phone filters, profile, logout, login, themes, responsive widths 320–1920px, catalog, DOM extraction; no JS errors.")
        finally:
            server.shutdown()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
