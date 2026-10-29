"""Messaging UI smoke check, with a fake provider and a disposable database only."""

from pathlib import Path
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from leadfinder import create_app
from leadfinder.models import Lead
from tests.test_outreach import FakeWhatsApp


def main():
    output=Path('test-results');output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        provider=FakeWhatsApp()
        app=create_app({'DATABASE':str(Path(directory)/'outreach.sqlite3')},whatsapp_provider=provider)
        accounts=app.extensions['accounts'];repo=app.extensions['repository']
        user_id=accounts.create_user('João de Teste','outreach.tester','outreach@example.org','browser-password-123')
        workspace=accounts.setup_workspace(user_id,'Workspace de teste')
        repo.create_search('test','Cafés','Rio',10,workspace_id=workspace)
        repo.save_lead('test',Lead('fixture','Café Exemplo (teste)','https://example.org',phone='21988882222'))
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce',color_scheme='light')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/login')
                page.get_by_label('Nome de usuário',exact=True).fill('outreach.tester')
                page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Entrar',exact=True).click()
                page.get_by_role('button',name='Mensagens',exact=True).click()
                page.get_by_label('Nome da mensagem',exact=True).fill('Apresentação')
                page.get_by_label('Texto da mensagem').fill('Olá {{empresa}}! Sou {{meu_nome}} do {{workspace}}. Contato: {{telefone}}. Tudo bem?')
                assert 'Café Horizonte' in page.locator('#message-preview-text').inner_text()
                page.get_by_role('button',name='Salvar mensagem',exact=True).click()
                page.locator('.template-card').wait_for()
                page.screenshot(path=str(output/'messages-light.png'),full_page=True)
                page.get_by_role('switch',name='Modo escuro').click()
                page.screenshot(path=str(output/'messages-dark.png'),full_page=True)
                page.get_by_role('button',name='Automação',exact=True).click()
                page.get_by_label('Modo de execução').select_option('simulated')
                page.get_by_label('Nome do disparo',exact=True).fill('Simulação do cliente fictício')
                page.get_by_label('Telefone do cliente fictício').fill('(21) 98888-2222')
                page.locator('[data-template]').first.check()
                page.get_by_role('button',name='Preparar e revisar disparo').click()
                expect(page.locator('.delivery-item > small')).to_contain_text('+5521988882222')
                expect(page.locator('.delivery-item .chat-bubble')).to_contain_text('Contato: 5521988882222')
                page.get_by_role('button',name='Executar simulação',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Simulação concluída · sem envio')
                assert not provider.sent,'Fictional client reached provider'
                page.screenshot(path=str(output/'automation-simulation.png'),full_page=True)
                page.locator('.account-menu summary').click()
                page.get_by_role('link',name='Ajustes do perfil').click()
                expect(page.locator('.title-bar')).to_be_visible()
                expect(page.locator('.sidebar')).to_be_visible()
                expect(page.locator('#main-content #auth-name')).to_be_visible()
                expect(page.locator('#catalog-view')).to_be_hidden()
                for theme in ('light','dark'):
                    if page.locator('html').get_attribute('data-theme') != theme:
                        page.get_by_role('switch',name='Modo escuro').click()
                    page.screenshot(path=str(output/('profile-shell-'+theme+'.png')),full_page=True)
                page.get_by_role('link',name='Integrações',exact=True).click()
                expect(page.locator('.title-bar')).to_be_visible()
                expect(page.locator('.sidebar')).to_be_visible()
                expect(page.locator('#main-content #wa-config')).to_be_visible()
                page.reload()
                expect(page.locator('#page-title')).to_have_text('Integrações')
                for width in (320,390,768,1024,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Settings overflow at {width}'
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_label('Seu nome de envio').fill('João')
                page.get_by_label('Número do WhatsApp').fill('+55 21 99999-1111')
                page.get_by_role('button',name='Salvar integração').click()
                page.get_by_text('Integração salva.',exact=True).wait_for()
                page.screenshot(path=str(output/'whatsapp-settings.png'),full_page=True)
                page.get_by_role('button',name='Estabelecimentos',exact=False).click()
                page.get_by_role('button',name='Automação',exact=True).click()
                page.get_by_label('Nome do disparo',exact=True).fill('Envio com adaptador de teste')
                page.get_by_label('Modo de execução').select_option('real')
                page.locator('[data-template]').first.check()
                page.locator('[data-target]').first.check()
                page.get_by_role('button',name='Preparar e revisar disparo').click()
                page.get_by_role('button',name='Iniciar disparo real',exact=True).wait_for()
                assert not page.get_by_role('button',name='Iniciar disparo real',exact=True).is_enabled()
                page.get_by_role('link',name='Configurar WhatsApp').click()
                page.get_by_role('button',name='Conectar / restaurar sessão',exact=True).click()
                expect(page.locator('#wa-status')).to_have_text('Conectado')
                page.get_by_role('button',name='Estabelecimentos',exact=False).click()
                page.get_by_role('button',name='Automação',exact=True).click()
                row=page.locator('.campaign-row').filter(has_text='Envio com adaptador de teste')
                row.get_by_role('button',name='Ver detalhes').click()
                page.get_by_role('button',name='Iniciar disparo real',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Envios aceitos pelo WhatsApp')
                assert len(provider.sent)==1,'Expected one fake-provider delivery'
                assert 'Café Exemplo (teste)' in provider.sent[0][2]
                page.screenshot(path=str(output/'automation-test-provider.png'),full_page=True)
                expect(page.locator('#campaign-detail .operation-log')).to_contain_text('aceita pelo servidor')
                page.get_by_label('Modo de execução').select_option('test')
                page.locator('[data-template]').first.check()
                page.get_by_label('Nome do disparo',exact=True).fill('WhatsApp para número de teste')
                page.locator('#fictional-phone').fill('+55 21 97777-3333')
                page.get_by_role('button',name='Preparar e revisar disparo').click()
                expect(page.locator('#campaign-mode-badge')).to_have_text('WhatsApp · número de teste')
                expect(page.locator('.delivery-item > small').first).to_contain_text('+5521977773333')
                page.get_by_role('button',name='Iniciar disparo real',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Envios aceitos pelo WhatsApp')
                assert len(provider.sent)==2
                assert provider.sent[-1][1]=='5521977773333'
                page.screenshot(path=str(output/'automation-real-test-number.png'),full_page=True)

                for view in ('Mensagens','Automação'):
                    page.get_by_role('button',name=view,exact=True).click()
                    for width in (320,390,768,1024,1440):
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'Overflow: {view} at {width}'
                    page.set_viewport_size({'width':390,'height':844})
                    page.screenshot(path=str(output/('outreach-mobile-'+view+'.png')),full_page=True)
                page.reload()
                page.get_by_role('heading',name='Automação',exact=True).wait_for()
                assert not errors,errors
                browser.close()
                print('PASS messaging UI: templates, preview, fictional simulation without provider, active-integration gate, one fake-provider delivery, profile integration, themes, responsive widths, direct page reload; no real WhatsApp messages sent.')
        finally:
            server.shutdown();thread.join(timeout=5)


if __name__=='__main__':
    main()
