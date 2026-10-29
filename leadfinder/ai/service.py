"""Local conversation persistence and explicit, idempotent AI generation."""

import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from leadfinder.ai.catalog import AIError, PROVIDERS, provider_spec
from leadfinder.ai.credentials import CredentialVault
from leadfinder.ai.providers import AIProviders
from leadfinder.outreach import validate_template, OutreachError
from leadfinder.repository import now


def parse_reply(text):
    cleaned=text.strip()
    if cleaned.startswith('```'):
        cleaned=re.sub(r'^```(?:json)?\s*|\s*```$','',cleaned)
    try:
        result=json.loads(cleaned)
    except ValueError:
        return text[:12000],[], 'A IA respondeu sem modelos estruturados. Peça para gerar as mensagens ou copie o texto para revisar.'
    if not isinstance(result,dict) or not isinstance(result.get('reply'),str) or not isinstance(result.get('messages'),list):
        raise AIError('A IA retornou uma resposta incompleta. Reformule o pedido; nenhum modelo foi salvo.')
    if len(result['reply'])>12000 or len(result['messages'])>5:
        raise AIError('A resposta ultrapassou o limite de 5 modelos. Peça uma sequência menor.')
    suggestions=[]
    for item in result['messages']:
        try:
            if not isinstance(item,dict):
                raise OutreachError('Formato de mensagem inválido.')
            name,body=validate_template(item.get('name'),item.get('body'))
        except OutreachError:
            raise AIError('A IA gerou um modelo com tamanho ou variáveis inválidos. Peça uma versão usando as variáveis disponíveis no editor.') from None
        suggestions.append({'name':name,'body':body})
    if not result['reply'].strip() and not suggestions:
        raise AIError('A IA retornou uma resposta vazia. Tente reformular o pedido.')
    return result['reply'],suggestions,None


class AIService:
    def __init__(self, repository, providers=None):
        self.repo=repository
        self.providers=providers or AIProviders()
        self.vault=CredentialVault(Path(repository.database).parent/'.ai-credentials.key')
        with self.repo.connection() as db:
            db.execute("UPDATE ai_turns SET status='failed',error='O servidor reiniciou durante a geração. Não houve nova tentativa automática.' WHERE status='pending'")

    def config(self, workspace_id, provider):
        provider_spec(provider)
        with self.repo.connection() as db:
            row=db.execute('SELECT * FROM ai_integrations WHERE workspace_id=? AND provider=?',(workspace_id,provider)).fetchone()
            return dict(row) if row else None

    def configurations(self, workspace_id):
        result=[]
        for identity,spec in PROVIDERS.items():
            config=self.config(workspace_id,identity)
            result.append({'provider':identity,'name':spec['name'],'configured':bool(config),
                'model':config['model'] if config else spec['default'],
                'key_hint':config['key_hint'] if config else None,
                'provider_workspace':config['provider_workspace'] if config else '',
                'models':[{'id':item,'name':item} for item in spec['models']],
                'keys_url':spec['keys_url'],'docs_url':spec['docs_url'],'checked_at':'2026-10-28'})
        return result

    def save(self, workspace_id, provider, data):
        spec=provider_spec(provider)
        current=self.config(workspace_id,provider)
        key=data.get('api_key','')
        if not isinstance(key,str):
            raise AIError('Informe uma chave de API válida.')
        key=key.strip()
        model=data.get('model',spec['default'])
        if not isinstance(model,str) or '://' in model or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,149}',model):
            raise AIError('Informe o ID do modelo exatamente como aparece no provedor.')
        workspace=data.get('provider_workspace','')
        if not isinstance(workspace,str) or (workspace and (provider!='claude' or not re.fullmatch(r'wrkspc_[A-Za-z0-9]{1,100}',workspace))):
            raise AIError('Confira o ID do workspace Anthropic ou deixe o campo vazio.')
        if key:
            if not re.fullmatch(r'[!-~]{16,512}',key):
                raise AIError('A chave deve ter de 16 a 512 caracteres, sem espaços.')
            with self.repo.connection() as db:
                if db.execute('SELECT 1 FROM ai_integrations LIMIT 1').fetchone():
                    self.vault.cipher()  # Do not replace a missing local encryption key silently.
            encrypted,hint=self.vault.encrypt(key),key[-4:]
        elif current:
            encrypted,hint=current['encrypted_key'],current['key_hint']
        else:
            raise AIError('Informe a chave de API para conectar este provedor.')
        with self.repo.connection() as db:
            db.execute('''INSERT INTO ai_integrations VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(workspace_id,provider) DO UPDATE SET encrypted_key=excluded.encrypted_key,
                key_hint=excluded.key_hint,model=excluded.model,provider_workspace=excluded.provider_workspace,updated_at=excluded.updated_at''',
                (workspace_id,provider,encrypted,hint,model,workspace,now()))
        return next(item for item in self.configurations(workspace_id) if item['provider']==provider)

    def remove(self, workspace_id, provider):
        provider_spec(provider)
        with self.repo.connection() as db:
            db.execute('DELETE FROM ai_integrations WHERE workspace_id=? AND provider=?',(workspace_id,provider))

    def require_config(self, workspace_id, provider):
        config=self.config(workspace_id,provider)
        if not config:
            raise AIError('Conecte este provedor em Perfil → Integrações → Inteligência artificial.')
        return config,self.vault.decrypt(config['encrypted_key'])

    def models(self, workspace_id, provider):
        config,key=self.require_config(workspace_id,provider)
        return self.providers.models(provider,key,config['provider_workspace'])

    def test(self, workspace_id, provider):
        config,_=self.require_config(workspace_id,provider)
        models=self.models(workspace_id,provider)
        if not any(item['id']==config['model'] for item in models):
            raise AIError('A chave respondeu, mas o modelo selecionado não aparece no catálogo acessível. Atualize os modelos ou confira o ID.')
        return {'ok':True,'message':'Chave validada e modelo encontrado no catálogo. A geração depende do saldo e dos limites da API.'}

    def threads(self, workspace_id):
        with self.repo.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,title,created_at,updated_at FROM ai_threads WHERE workspace_id=? ORDER BY updated_at DESC LIMIT 50',(workspace_id,))]

    def new_thread(self, workspace_id):
        identity=uuid4().hex
        with self.repo.connection() as db:
            db.execute('INSERT INTO ai_threads VALUES(?,?,?,?,?)',(identity,workspace_id,'Nova campanha',now(),now()))
        return self.thread(workspace_id,identity)

    def thread(self, workspace_id, thread_id):
        with self.repo.connection() as db:
            row=db.execute('SELECT * FROM ai_threads WHERE workspace_id=? AND id=?',(workspace_id,thread_id)).fetchone()
            if not row:
                raise AIError('Conversa não encontrada neste workspace.')
            result=dict(row)
            turns=db.execute('SELECT * FROM (SELECT * FROM ai_turns WHERE thread_id=? ORDER BY id DESC LIMIT 50) ORDER BY id',(thread_id,)).fetchall()
        result['turns']=[self.public_turn(dict(row)) for row in turns]
        return result

    def public_turn(self, row):
        for field in ('suggestions','usage'):
            row[field]=json.loads(row[field])
        from leadfinder.ai.agent import public_action
        with self.repo.connection() as db:
            row['actions']=[public_action(action) for action in db.execute('SELECT * FROM ai_tool_calls WHERE workspace_id=? AND turn_id=? ORDER BY created_at,id',(row['workspace_id'],row['id']))]
        return row

    def chat(self, workspace_id, thread_id, data):
        text=data.get('message','')
        request_key=data.get('request_key','')
        provider=data.get('provider','')
        if not isinstance(text,str) or not 1<=len(text.strip())<=6000:
            raise AIError('Escreva de 1 a 6.000 caracteres sobre sua campanha.')
        if not isinstance(request_key,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',request_key):
            raise AIError('Identificador da solicitação inválido. Recarregue a página.')
        thread=self.thread(workspace_id,thread_id)
        with self.repo.connection() as db:
            previous=db.execute('SELECT * FROM ai_turns WHERE workspace_id=? AND request_key=?',(workspace_id,request_key)).fetchone()
            if previous:
                if previous['thread_id']!=thread_id or previous['user_text']!=text.strip() or previous['provider']!=provider:
                    raise AIError('Este identificador já pertence a outro pedido. Recarregue a conversa.')
                return self.public_turn(dict(previous))
        config,key=self.require_config(workspace_id,provider)
        from leadfinder.crm import CRM
        product_context=CRM(self.repo).context(workspace_id)
        history=[]
        for turn in [item for item in thread['turns'] if item['status']=='completed'][-12:]:
            history.extend([{'role':'user','content':turn['user_text']},
                {'role':'assistant','content':json.dumps({'reply':turn['reply'],'messages':turn['suggestions']},ensure_ascii=False)}])
        while sum(len(item['content']) for item in history)>40000:
            history=history[2:]
        if any(product_context.values()):
            history.insert(0,{'role':'user','content':'Contexto cadastrado do produto para esta campanha. Use apenas as informações fornecidas; não invente benefícios, ofertas ou resultados. Ajuste ao segmento mencionado na conversa.\n'+json.dumps(product_context,ensure_ascii=False)})
        history.append({'role':'user','content':text.strip()})
        try:
            with self.repo.connection() as db:
                identity=db.execute('INSERT INTO ai_turns(thread_id,workspace_id,request_key,provider,model,user_text,created_at,context_snapshot) VALUES(?,?,?,?,?,?,?,?) RETURNING id',
                    (thread_id,workspace_id,request_key,provider,config['model'],text.strip(),now(),json.dumps(product_context,ensure_ascii=False))).fetchone()[0]
                db.execute('UPDATE ai_threads SET title=?,updated_at=? WHERE id=?',
                    (text.strip()[:65] if not thread['turns'] else thread['title'],now(),thread_id))
        except sqlite3.IntegrityError:
            raise AIError('Já há uma geração em andamento neste workspace. Aguarde o resultado.') from None
        try:
            response,usage=self.providers.complete(provider,key,config['model'],history,config['provider_workspace'])
            reply,suggestions,warning=parse_reply(response)
            with self.repo.connection() as db:
                db.execute("UPDATE ai_turns SET status='completed',reply=?,suggestions=?,usage=?,error=? WHERE id=?",
                    (reply,json.dumps(suggestions,ensure_ascii=False),json.dumps(usage),warning,identity))
        except Exception as error:
            message=str(error) if isinstance(error,AIError) else 'Falha inesperada ao gerar a resposta. Nenhum modelo foi salvo e não houve repetição automática.'
            with self.repo.connection() as db:
                db.execute("UPDATE ai_turns SET status='failed',error=? WHERE id=?",(message,identity))
        with self.repo.connection() as db:
            result=self.public_turn(dict(db.execute('SELECT * FROM ai_turns WHERE id=?',(identity,)).fetchone()))
        return result
