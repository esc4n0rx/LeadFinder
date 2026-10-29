"""AI UI verification using a local transport fixture and disposable data only."""

import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from leadfinder import create_app
from leadfinder.ai.providers import AIProviders
from tests.test_ai import FakeAITransport
from tests.test_outreach import FakeWhatsApp


def main():
    output=Path('test-results');output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        transport=FakeAITransport()
        app=create_app({'DATABASE':str(Path(directory)/'ai.sqlite3')},whatsapp_provider=FakeWhatsApp(),ai_provider=AIProviders(transport))
        accounts=app.extensions['accounts']
        user=accounts.create_user('Teste IA','ai.browser','ai-browser@example.org','browser-password-123')
        workspace=accounts.setup_workspace(user,'Estúdio de campanhas')
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch()
                page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce',color_scheme='light')
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base+'/login')
                page.get_by_label('Nome de usuário',exact=True).fill('ai.browser')
                page.get_by_label('Senha',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='Entrar',exact=True).click()
                page.get_by_role('button',name='Agentes',exact=True).click()
                expect(page.locator('#ai-send')).to_be_disabled()
                expect(page.locator('#ai-chat-connection')).to_contain_text('Conecte uma API')
                page.get_by_role('link',name='Configurar IA',exact=False).click()
                expect(page.locator('.sidebar')).to_be_visible()
                expect(page.locator('#page-title')).to_have_text('Inteligência artificial')
                for provider in ('openai','openrouter','claude'):
                    card=page.locator(f'[data-ai-provider="{provider}"]')
                    card.get_by_role('button',name='Conectar provedor',exact=False).click()
                    dialog=page.locator('#ai-config-dialog')
                    dialog.get_by_label('Chave de API',exact=True).fill('fake-api-key-for-browser-123456')
                    dialog.get_by_role('button',name='Salvar',exact=False).click()
                    expect(card.locator('.status-badge')).to_have_text('Chave salva')
                    expect(dialog.get_by_label('Chave de API',exact=True)).to_have_value('')
                    dialog.get_by_role('button',name='Testar conexão').click()
                    expect(dialog.locator('.ai-provider-feedback')).to_contain_text('Chave validada')
                    dialog.get_by_role('button',name='Atualizar modelos').click()
                    expect(dialog.locator('.ai-provider-feedback')).to_contain_text('modelos disponíveis')
                    if provider=='openai':
                        model=dialog.locator('[name=model]')
                        model.fill('gpt-6.1')
                        expect(dialog.locator('[role=option]')).to_have_count(2)
                        model.press('ArrowDown');model.press('Enter')
                        expect(dialog.get_by_role('button',name='Testar conexão')).to_be_disabled()
                        dialog.get_by_role('button',name='Salvar',exact=False).click()
                        expect(dialog.locator('.ai-provider-feedback')).to_contain_text('Configuração salva')
                        model=dialog.locator('[name=model]');model.focus();model.press('Escape')
                        expect(dialog).to_be_visible()
                    page.get_by_role('button',name='Fechar configuração',exact=True).click()
                    expect(dialog).not_to_be_visible()
                expect(page.locator('#toast-region .toast')).to_have_count(0,timeout=12000)
                page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
                page.screenshot(path=str(output/'ai-integrations-light.png'),full_page=True)
                for width in (320,390,768,1024,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'AI settings overflow at {width}'
                page.set_viewport_size({'width':390,'height':640})
                page.locator('[data-ai-configure="openai"]').click()
                mobile_dialog=page.locator('#ai-config-dialog')
                expect(mobile_dialog.get_by_role('button',name='Salvar',exact=False)).to_be_in_viewport(ratio=1)
                mobile_dialog.get_by_label('Chave de API',exact=True).fill('fake-new-key-for-cancel-0000')
                mobile_dialog.get_by_role('button',name='Cancelar',exact=True).click()
                expect(mobile_dialog).not_to_be_visible()
                assert app.extensions['ai_service'].config(workspace,'openai')['key_hint']=='3456'
                assert page.locator('#ai-config-dialog [name=api_key]').count()==0
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_role('switch',name='Modo escuro').click()
                page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
                page.screenshot(path=str(output/'ai-integrations-dark.png'),full_page=True)
                page.get_by_role('button',name='Agentes',exact=True).click()
                expect(page.locator('#ai-send')).to_be_disabled()
                transport.reply={'reply':'Qual público você quer alcançar e qual ação espera despertar?\n\n'+'\n'.join(str(i)+'. Informação importante para definir a campanha.' for i in range(1,25)),'messages':[]}
                page.get_by_role('button',name='Apresentar meu produto',exact=False).click()
                assert len([call for call in transport.calls if call[0]=='POST'])==0
                page.get_by_label('Sobre seu produto ou campanha',exact=True).fill('Quero divulgar um serviço de agendamento online.')
                page.get_by_label('Sobre seu produto ou campanha',exact=True).press('Shift+Enter')
                assert page.get_by_label('Sobre seu produto ou campanha',exact=True).input_value().endswith('\n')
                page.get_by_label('Sobre seu produto ou campanha',exact=True).press('Enter')
                expect(page.locator('.ai-assistant-message').last).to_contain_text('Qual público')
                transport.reply={'reply':'Aqui está uma abordagem com benefício concreto e CTA simples. <img src=x onerror=alert(1)>',
                    'messages':[{'name':'Agendamento para clínicas','body':'Olá {{empresa}}! Ajudamos clínicas a receber agendamentos online. Podemos conversar por 15 minutos esta semana?'}]}
                entered,release=threading.Event(),threading.Event()
                transport.hook=lambda:(entered.set(),release.wait(10))
                page.get_by_label('Sobre seu produto ou campanha',exact=True).fill('Clínicas pequenas. Quero convidar para uma conversa de 15 minutos. Tom direto e gentil.')
                page.get_by_role('button',name='Conversar com a IA',exact=False).click()
                expect(page.locator('.bui-loading')).to_be_visible()
                expect(page.locator('#ai-chat-form')).to_be_in_viewport(ratio=1)
                page.locator('#ai-chat-history').evaluate('(node)=>node.scrollTop=0')
                page.get_by_label('Sobre seu produto ou campanha',exact=True).fill('Rascunho do próximo pedido')
                release.set();transport.hook=None
                expect(page.locator('.ai-suggestion')).to_have_count(1)
                expect(page.get_by_label('Sobre seu produto ou campanha',exact=True)).to_have_value('Rascunho do próximo pedido')
                assert page.locator('#ai-chat-history').evaluate('(node)=>node.scrollTop')<10
                page.get_by_role('button',name='Últimas mensagens',exact=False).click()
                assert page.locator('#ai-chat-history img').count()==0
                assert app.extensions['outreach_store'].templates(workspace)==[]
                post_calls=[call for call in transport.calls if call[0]=='POST']
                assert len(post_calls)==2
                assert any(item.get('role')=='assistant' for item in post_calls[-1][3]['input']),'Conversation context was lost'
                page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
                page.screenshot(path=str(output/'ai-assistant-dark.png'),full_page=True)
                page.get_by_role('switch',name='Modo escuro').click()
                page.screenshot(path=str(output/'ai-assistant-light.png'),full_page=True)
                for width in (320,390,768,1024,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    expect(page.locator('#ai-chat-form')).to_be_in_viewport(ratio=1)
                    expect(page.locator('#ai-chat-prompt')).to_be_in_viewport(ratio=1)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'AI chat overflow at {width}'
                    assert page.evaluate('document.documentElement.scrollHeight<=innerHeight+1'),f'Page scroll leaked at {width}'
                for width,height in ((320,568),(390,640),(390,400),(844,390)):
                    page.set_viewport_size({'width':width,'height':height})
                    expect(page.locator('#ai-chat-form')).to_be_in_viewport(ratio=1)
                    expect(page.locator('#ai-chat-prompt')).to_be_in_viewport(ratio=1)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(output/'ai-assistant-mobile.png'),full_page=True)
                page.get_by_role('button',name='Alternar lista de conversas').click()
                expect(page.locator('#ai-history-panel')).to_be_visible()
                page.get_by_label('Buscar conversa',exact=True).fill('não existe')
                expect(page.locator('#ai-thread-list')).to_contain_text('Nenhuma conversa encontrada')
                page.get_by_label('Buscar conversa',exact=True).fill('')
                page.keyboard.press('Escape')
                expect(page.locator('#ai-history-panel')).not_to_be_visible()
                page.set_viewport_size({'width':1440,'height':1000})
                page.get_by_label('Provedor de IA',exact=True).select_option('claude')
                page.get_by_role('button',name='Mensagens',exact=True).click()
                page.get_by_role('button',name='Agentes',exact=True).click()
                expect(page.get_by_label('Provedor de IA',exact=True)).to_have_value('claude')
                page.reload()
                expect(page.locator('#ai-assistant')).to_be_visible()
                expect(page.locator('.ai-suggestion')).to_have_count(1)
                assert '/agents' in page.url and 'conversation=' in page.url
                page.get_by_role('button',name='Usar no editor',exact=True).click()
                expect(page.get_by_label('Nome da mensagem',exact=True)).to_have_value('Agendamento para clínicas')
                assert 'Podemos conversar' in page.get_by_label('Texto da mensagem').input_value()
                page.get_by_role('button',name='Salvar mensagem',exact=True).click()
                expect(page.locator('.template-card')).to_have_count(1)
                page.reload()
                page.get_by_role('button',name='Agentes',exact=True).click()
                expect(page.locator('.ai-suggestion')).to_have_count(1)
                transport.error='Créditos insuficientes no provedor. Confira o saldo da API.'
                page.get_by_label('Sobre seu produto ou campanha',exact=True).fill('Agora crie um follow-up curto.')
                page.get_by_role('button',name='Conversar com a IA',exact=False).click()
                expect(page.locator('.ai-turn').last).to_contain_text('Créditos insuficientes')
                assert not errors,errors
                assert not app.extensions['whatsapp_integration'].provider.sent
                browser.close()
                print('PASS AI UI: three integrations, models, key test, conversation context, review/save, persistence, errors, XSS escaping, light/dark, 320-1440px; no real API generation or WhatsApp sends.')
        finally:
            server.shutdown();thread.join(timeout=5)


if __name__=='__main__':
    main()
