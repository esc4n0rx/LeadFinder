"""Category and lead workflows in a disposable workspace; no external services."""
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from leadfinder import create_app
from leadfinder.models import Lead
from tests.test_outreach import FakeWhatsApp


class FixtureCollector:
    def collect(self,term,location,limit,on_lead,*args):
        on_lead(Lead('new-fixture','Novo Café da Busca','https://example.org',category='Cafeteria',phone='21988882222'))


def main():
    output=Path('test-results');output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        provider=FakeWhatsApp()
        app=create_app({'DATABASE':str(Path(directory)/'directory.sqlite3')},collector_factory=FixtureCollector,whatsapp_provider=provider)
        accounts=app.extensions['accounts'];repo=app.extensions['repository']
        user=accounts.create_user('Teste de Leads','directory.tester','directory@example.org','browser-password-123')
        workspace=accounts.setup_workspace(user,'Workspace de Leads')
        repo.create_search('fixture','Cafés','Rio',40,workspace_id=workspace)
        for index in range(30):
            repo.save_lead('fixture',Lead('fixture-'+str(index),f'Café {index:02}','https://example.org',category='Cafeteria',phone='21988882222',address='Rua de Teste, 10',rating=4.7,review_count=12))
        repo.update_search('fixture',status='completed')
        server=make_server('127.0.0.1',0,app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/login')
                page.get_by_label('Nome de usuário',exact=True).fill('directory.tester')
                page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Entrar',exact=True).click()
                page.locator('[data-manage-categories]').first.click()
                page.get_by_label('Nome da categoria',exact=True).fill('Restaurantes')
                page.get_by_role('button',name='Criar categoria',exact=True).click()
                page.get_by_label('Renomear categoria Restaurantes',exact=True).wait_for()
                page.get_by_label('Renomear categoria Restaurantes',exact=True).fill('Restaurantes locais')
                page.get_by_role('button',name='Salvar categoria Restaurantes',exact=True).click()
                page.get_by_label('Renomear categoria Restaurantes locais',exact=True).wait_for()
                page.get_by_role('button',name='Fechar categorias',exact=True).click()
                expect(page.locator('#discovery-category option:checked')).to_have_text('Restaurantes locais')
                page.get_by_label('O que você procura?',exact=True).fill('Cafés de teste')
                page.get_by_role('button',name='Encontrar leads',exact=True).click()
                expect(page.locator('#stat-total')).to_have_text('31')
                page.get_by_role('button',name='Leads',exact=True).click()
                page.get_by_role('button',name='Limpar filtros',exact=True).click()
                expect(page.locator('#directory-count')).to_have_text('31')
                page.get_by_role('button',name='Próxima página de leads',exact=True).click()
                expect(page.locator('#directory-page')).to_have_text('2 / 2')
                page.get_by_label('Buscar lead',exact=True).fill('Café 00')
                expect(page.locator('#directory-count')).to_have_text('1')
                page.get_by_role('button',name='Organizar',exact=True).click()
                page.locator('#organize-categories').get_by_label('Restaurantes locais',exact=True).check()
                page.get_by_label('Status do contato deste lead',exact=True).select_option('conversed')
                page.get_by_role('button',name='Salvar organização',exact=True).click()
                expect(page.locator('#organize-dialog')).not_to_be_visible()
                expect(page.locator('#directory-body .directory-tag')).to_have_text('Restaurantes locais')
                page.get_by_label('Categoria',exact=True).select_option(label='Restaurantes locais')
                page.get_by_label('Status do contato',exact=True).select_option('conversed')
                expect(page.locator('#directory-count')).to_have_text('1')
                page.get_by_label('Status de Café 00',exact=True).select_option('contacted')
                expect(page.locator('#directory-empty')).to_be_visible()
                page.get_by_role('button',name='Limpar filtros',exact=True).click()
                expect(page.locator('#directory-count')).to_have_text('31')
                page.reload()
                expect(page.locator('#page-title')).to_have_text('Leads')
                expect(page.locator('#directory-count')).to_have_text('31')
                for theme in ('light','dark'):
                    if page.locator('html').get_attribute('data-theme')!=theme:
                        page.get_by_role('switch',name='Modo escuro').click()
                    page.screenshot(path=str(output/('leads-'+theme+'.png')),full_page=True)
                    for width in (320,390,768,1024,1440):
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Leads overflow at {width}'
                        page.locator('#directory-view [data-manage-categories]').click()
                        expect(page.locator('#categories-dialog')).to_be_visible()
                        assert page.locator('#categories-dialog').evaluate('node=>node.scrollWidth<=node.clientWidth'),f'Dialog overflow at {width}'
                        page.get_by_role('button',name='Fechar categorias',exact=True).click()
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(output/'leads-mobile.png'),full_page=True)
                page.locator('#directory-view [data-manage-categories]').click()
                page.get_by_role('button',name='Excluir categoria Restaurantes locais',exact=True).click()
                page.get_by_role('button',name='Excluir categoria Restaurantes locais',exact=True).click()
                expect(page.locator('#categories-list')).to_contain_text('Nenhuma categoria')
                page.get_by_role('button',name='Fechar categorias',exact=True).click()
                expect(page.locator('#directory-count')).to_have_text('31')
                assert repo.stats(workspace)['total']==31
                assert not provider.sent
                assert not errors,errors
                browser.close()
                print('PASS: categories CRUD, search grouping, lead organization, contact filters, pagination, reload, light/dark, 320–1440px; no real sends.')
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__':
    main()
