"""End-to-end agents and lead editing with native-tool fixtures; no external calls."""
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from leadfinder import create_app
from leadfinder.ai.providers import AIProviders
from leadfinder.models import Lead
from tests.test_agents import NativeTransport
from tests.test_outreach import FakeWhatsApp
from tests.browser_directory import FixtureCollector

def main():
    output=Path('test-results');output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        transport=NativeTransport();wa=FakeWhatsApp()
        app=create_app({'TESTING':True,'DATABASE':str(Path(folder)/'agents.sqlite3')},collector_factory=FixtureCollector,whatsapp_provider=wa,ai_provider=AIProviders(transport))
        accounts=app.extensions['accounts'];repo=app.extensions['repository']
        user=accounts.create_user('Pessoa de Teste','agents.tester','agents@example.org','browser-password-123')
        workspace=accounts.setup_workspace(user,'Workspace Agentes')
        app.extensions['ai_service'].save(workspace,'openai',{'api_key':'fake-test-key-12345678','model':'gpt-6.1-terra'})
        repo.create_search('fixture','Cafés','Rio',10,workspace_id=workspace)
        repo.save_lead('fixture',Lead('fixture','Café do Teste','https://example.org/maps',phone='21988882222',category='Cafeteria'))
        repo.update_search('fixture',status='completed')
        lead=repo.list_leads(workspace_id=workspace)['items'][0]['id']
        server=make_server('127.0.0.1',0,app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/login');page.get_by_label('Nome de usuário',exact=True).fill('agents.tester');page.get_by_label('Senha',exact=True).fill('browser-password-123');page.get_by_role('button',name='Entrar',exact=True).click()
                expect(page.locator('.workspace-top')).to_be_visible();assert page.locator('#catalog-view').count()==0
                page.get_by_role('button',name='Agentes',exact=True).click()
                expect(page.locator('#ai-chat-form')).to_be_in_viewport(ratio=1)
                transport.queue=[[('msg','messages_create',{'name':'Convite para demonstração','body':'Olá {{empresa}}! Podemos conversar por 15 minutos?'}),('funnel','funnels_create',{'name':'Cafés prospectados','q':'Café'})],'Mensagem e funil criados.']
                page.locator('#ai-chat-prompt').fill('Crie uma mensagem de convite e um funil para os cafés.');page.locator('#ai-send').click()
                expect(page.locator('.agent-action')).to_have_count(2);expect(page.locator('.agent-action .count-badge').first).to_have_text('Concluído')
                page.screenshot(path=str(output/'agents-desktop-light.png'),full_page=True)
                page.get_by_role('button',name='Mensagens',exact=True).click();expect(page.locator('#template-list')).to_contain_text('Convite para demonstração');assert page.locator('#message-ai-tab').count()==0
                page.get_by_role('button',name='Funil comercial',exact=True).click();page.locator('#pipeline-saved').select_option(label='Cafés prospectados');expect(page.locator('.pipeline-card')).to_have_count(1)
                page.get_by_role('button',name='Leads',exact=True).click();expect(page.locator('#directory-count')).to_have_text('1')
                page.locator('[data-edit-lead]').first.click();page.get_by_label('Nome',exact=True).fill('Café Atualizado');page.get_by_label('Telefone',exact=True).fill('21999991111');page.get_by_role('button',name='Salvar alterações',exact=True).click();expect(page.locator('#lead-edit-dialog')).not_to_be_visible();expect(page.locator('#directory-body')).to_contain_text('Café Atualizado')
                page.locator('[data-delete-lead]').first.click();expect(page.locator('#lead-delete-list')).to_contain_text('Café Atualizado');page.get_by_role('button',name='Fechar revisão',exact=True).click();assert repo.stats(workspace)['total']==1
                page.get_by_role('button',name='Agentes',exact=True).click();transport.queue=[[('delete','leads_delete',{'ids':[lead]})]]
                page.locator('#ai-chat-prompt').fill('Apague o Café Atualizado.');page.locator('#ai-send').click();expect(page.locator('[data-review-action]')).to_have_count(1)
                assert repo.stats(workspace)['total']==1
                page.get_by_role('button',name='Revisar ação',exact=True).click();expect(page.locator('#agent-confirm-details')).to_contain_text('Café Atualizado');page.get_by_role('button',name='Confirmar ação',exact=True).click();expect(page.locator('#agent-confirm-dialog')).not_to_be_visible();expect(page.locator('.agent-action').last).to_contain_text('Concluído')
                assert repo.stats(workspace)['total']==0
                for width,height in ((320,568),(390,844),(768,900),(1024,900),(1440,1000),(390,400),(844,390)):
                    page.set_viewport_size({'width':width,'height':height});expect(page.locator('#ai-chat-form')).to_be_in_viewport(ratio=1)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'overflow {width}'
                    assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+1'),f'page scroll {width}'
                page.set_viewport_size({'width':390,'height':844});page.get_by_role('switch',name='Modo escuro').click();expect(page.locator('#toast-region .toast')).to_have_count(0,timeout=12000);page.locator('#ai-chat-history').evaluate('node=>node.scrollTop=node.scrollHeight');page.screenshot(path=str(output/'agents-mobile-dark.png'),full_page=True)
                page.set_viewport_size({'width':1440,'height':1000});url=page.url;page.reload();expect(page.locator('.agent-action')).to_have_count(3);assert '/agents' in page.url and 'conversation=' in page.url
                page.goto(base+url.split(base)[1].replace('/agents?','/messages?tab=assistant&'));expect(page.locator('#agents-view')).to_be_visible()
                page.get_by_role('button',name='Nova busca',exact=True).click();page.get_by_label('O que você procura?',exact=True).fill('Cafeterias');page.get_by_role('button',name='Encontrar leads',exact=True).click();expect(page.locator('#directory-view')).to_be_visible(timeout=15000);expect(page.locator('#directory-body')).to_contain_text('Novo Café da Busca')
                page.locator('[data-delete-lead]').first.click();page.get_by_role('button',name='Confirmar exclusão',exact=True).click();expect(page.locator('#directory-count')).to_have_text('0')
                assert not errors,errors;assert not wa.sent
                browser.close();print('PASS agents UI: native actions, saved messages/funnels, review-confirm-delete, manual edits/deletes, history and legacy links, extraction to Leads, light/dark, responsive 320-1440 and short screens. No external calls.')
        finally:server.shutdown();thread.join(timeout=5)

if __name__=='__main__':main()
