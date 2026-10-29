"""Eight approved workflows in an isolated database, with fake WhatsApp only."""
from datetime import datetime,timedelta
from pathlib import Path
import re
import tempfile
import threading

from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server

from leadfinder import create_app
from leadfinder.models import Lead
from tests.test_outreach import FakeWhatsApp


def main():
    output=Path('test-results');output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        provider=FakeWhatsApp();provider.verify=lambda *args:{'ack':1}
        app=create_app({'TESTING':True,'DATABASE':str(Path(folder)/'growth.sqlite3')},whatsapp_provider=provider)
        accounts=app.extensions['accounts'];repo=app.extensions['repository'];store=app.extensions['outreach_store']
        identity=accounts.create_user('Pessoa de Teste','growth.tester','growth@example.org','browser-password-123')
        workspace=accounts.setup_workspace(identity,'Workspace Crescimento')
        repo.create_search('fixture','Cafés','Rio',40,workspace_id=workspace)
        for index in range(30):
            repo.save_lead('fixture',Lead(f'fixture-{index}',f'Café {index:02}','https://example.org',phone='219'+str(88880000+index),category='Cafeteria',address='Rua de Teste, 10'))
        repo.update_search('fixture',status='completed')
        template=store.save_template(workspace,'Primeiro contato','Olá {{empresa}}! Podemos conversar?')
        second=store.save_template(workspace,'Segundo contato','Uma demonstração de 15 minutos faz sentido?')
        integration=app.extensions['whatsapp_integration'];integration.save(workspace,'Pessoa Teste','5521999991111');integration.connect(workspace)
        prepared=store.prepare({'id':workspace,'name':'Workspace Crescimento'},'Pessoa Teste',{'name':'Recuperar tentativa','simulated':False,'template_ids':[template,second],'target_ids':[1],'interval_seconds':3})
        recovery=store.create_campaign(workspace,prepared)
        with repo.connection() as db:
            db.execute("UPDATE campaigns SET status='paused' WHERE id=?",(recovery,))
            db.execute("UPDATE campaign_messages SET status='uncertain',provider_id='true_fixture@c.us_FIXTURE_out' WHERE campaign_id=? AND message_index=0",(recovery,))
        server=make_server('127.0.0.1',0,app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/login')
                page.get_by_label('Nome de usuário',exact=True).fill('growth.tester');page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Entrar',exact=True).click()
                page.get_by_role('button',name='Leads',exact=True).click()
                expect(page.locator('#directory-count')).to_have_text('30')
                page.locator('[data-select-lead]').first.check()
                page.get_by_role('button',name='Próxima página de leads').click()
                expect(page.locator('#directory-page')).to_have_text('2 / 2')
                page.locator('[data-select-lead]').first.check()
                expect(page.locator('#lead-selection-count')).to_have_text('2 selecionados')
                page.get_by_role('button',name='Ações em lote',exact=True).click()
                page.locator('#bulk-dialog').get_by_label('Etapa comercial',exact=True).select_option('demo')
                page.get_by_role('button',name='Aplicar aos selecionados').click()
                expect(page.locator('#bulk-dialog')).not_to_be_visible()
                with page.expect_download() as csv_result:
                    page.get_by_role('button',name='Exportar CSV',exact=True).click()
                csv=csv_result.value
                assert Path(csv.path()).read_bytes().startswith(b'\xef\xbb\xbf')
                csv.delete()
                page.get_by_role('button',name='Mensagens com IA',exact=True).click()
                expect(page.locator('#ai-chat-prompt')).to_have_value(re.compile('2 leads'))
                page.get_by_role('button',name='Leads',exact=True).click()
                page.get_by_role('button',name='Criar campanha',exact=True).click()
                expect(page.locator('#target-count')).to_have_text('2 selecionados')
                page.locator(f'[data-template="{template}"]').check()
                page.get_by_role('button',name='Preparar e revisar disparo').click()
                expect(page.locator('.review-summary')).to_contain_text('2 destinatário(s)')
                page.get_by_label('Agendar data e hora',exact=True).fill((datetime.now()+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'))
                page.get_by_role('button',name='Confirmar agendamento',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Agendado')
                page.get_by_role('button',name='Cancelar restantes',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Cancelado')
                row=page.locator('.campaign-row').filter(has_text='Recuperar tentativa')
                row.get_by_role('button',name='Ver detalhes',exact=True).click()
                page.get_by_role('button',name='Consultar confirmação',exact=True).click()
                expect(page.locator('.review-summary small')).to_contain_text('1 enviados')
                page.get_by_role('button',name='Retomar 1 pendente(s)',exact=True).click()
                expect(page.locator('.review-summary .status-badge')).to_have_text('Envios aceitos pelo WhatsApp')
                assert len(provider.sent)==1,'Recovery must send only the previously pending message through the fake provider'
                page.get_by_role('button',name='Leads',exact=True).click()
                page.get_by_label('Buscar lead',exact=True).fill('Café 00')
                expect(page.locator('#directory-count')).to_have_text('1')
                page.locator('#directory-body [data-dossier]').click()
                page.get_by_label('Nova anotação',exact=True).fill('Cliente pediu uma demonstração.')
                page.get_by_role('button',name='Salvar anotação',exact=True).click()
                expect(page.locator('.dossier-note')).to_contain_text('Cliente pediu uma demonstração.')
                page.get_by_label('Lembrete',exact=True).fill('Confirmar demonstração')
                page.get_by_label('Quando retornar',exact=True).fill((datetime.now()-timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'))
                page.get_by_role('button',name='Criar lembrete',exact=True).click()
                page.get_by_role('button',name='Fechar ficha do lead',exact=True).click()
                page.get_by_role('button',name='Lembretes',exact=True).click()
                expect(page.locator('.task-row.overdue')).to_contain_text('Confirmar demonstração')
                page.get_by_role('button',name='Concluir',exact=True).click()
                expect(page.locator('#tasks-list')).to_contain_text('Nenhum lembrete')
                page.get_by_role('button',name='Funil comercial',exact=True).click()
                page.locator('[data-drop-stage="contacted"] [data-card-stage="1"]').select_option('customer')
                expect(page.locator('[data-drop-stage="customer"]')).to_contain_text('Café 00')
                expect(page.locator('#pipeline-feedback')).to_contain_text('Arraste')
                page.evaluate("""()=>{window.kanbanEvents=[];for(const type of ['dragstart','drop','dragend'])document.querySelector('#pipeline-board').addEventListener(type,event=>window.kanbanEvents.push({type,target:event.target.tagName,data:event.dataTransfer?.getData('text/plain')}));}""")
                page.locator('[data-drop-stage="customer"] [data-drag-lead="1"] .pipeline-grip').drag_to(page.locator('[data-drop-stage="lost"]'))
                try:
                    expect(page.locator('[data-drop-stage="lost"]')).to_contain_text('Café 00')
                except AssertionError as error:
                    page.screenshot(path=str(output/'growth-kanban-drop-failure.png'))
                    raise AssertionError(str(page.evaluate('window.kanbanEvents'))) from error
                page.get_by_role('button',name='Workspace',exact=True).click()
                page.get_by_label('Produto ou serviço',exact=True).fill('OctaMenu de teste')
                page.get_by_label('Diferenciais e benefícios verificáveis',exact=True).fill('Pedidos e cardápio em um lugar.')
                page.get_by_label('Público-alvo',exact=True).fill('Restaurantes')
                page.get_by_label('Oferta e objetivo do contato',exact=True).fill('Agendar demonstração')
                page.get_by_label('Tom de voz',exact=True).fill('Profissional')
                page.get_by_role('button',name='Salvar contexto do produto',exact=True).click()
                expect(page.locator('#product-feedback')).to_contain_text('Contexto salvo')
                password='fixture-backup-password-123'
                page.get_by_label('Senha para proteger o backup',exact=True).fill(password)
                with page.expect_download() as result:
                    page.get_by_role('button',name='Baixar backup completo',exact=True).click()
                download=result.value;backup=Path(download.path()).read_bytes();download.delete()
                page.get_by_label('Produto ou serviço',exact=True).fill('Alterado depois do backup')
                page.get_by_role('button',name='Salvar contexto do produto',exact=True).click()
                page.get_by_label('Arquivo de backup',exact=True).set_input_files({'name':'workspace.lfbackup','mimeType':'application/octet-stream','buffer':backup})
                page.get_by_label('Senha do arquivo',exact=True).fill(password)
                page.get_by_role('button',name='Analisar backup',exact=True).click()
                expect(page.locator('#restore-preview')).to_contain_text('30 leads')
                page.get_by_label('Digite o nome atual do workspace',exact=True).fill('Workspace Crescimento')
                page.get_by_label('Sua senha atual da conta',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Confirmar restauração do workspace',exact=True).click()
                expect(page.locator('#page-title')).to_have_text('Leads')
                expect(page.locator('#directory-count')).to_have_text('30')
                page.get_by_role('button',name='Workspace',exact=True).click()
                expect(page.get_by_label('Produto ou serviço',exact=True)).to_have_value('OctaMenu de teste')
                for theme in ('light','dark'):
                    if page.locator('html').get_attribute('data-theme')!=theme:page.get_by_role('switch',name='Modo escuro').click()
                    for view,label in [('leads','Leads'),('pipeline','Funil comercial'),('tasks','Lembretes'),('workspace','Workspace')]:
                        page.get_by_role('button',name=label,exact=True).click()
                        if view=='pipeline':expect(page.locator('#pipeline-feedback')).to_contain_text('Arraste')
                        page.screenshot(path=str(output/f'growth-{view}-{theme}.png'))
                        for width in (320,390,768,1024,1440):
                            page.set_viewport_size({'width':width,'height':900})
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{view} overflow at {width}'
                assert not errors,errors
                assert len(provider.sent)==1
                browser.close()
                print('PASS eight growth workflows: bulk across pages, category campaign handoff, dossier, recovery, Kanban, reminders, scheduling, product context, CSV API and encrypted backup/restore. Fake provider only.')
        finally:
            app.extensions['scheduler'].stop.set();server.shutdown();server.server_close()


if __name__=='__main__':
    main()
