"""Explicit domain-tool allowlist. No arbitrary HTTP, filesystem, SQL or secrets."""
import math

from leadfinder.ai.catalog import AIError
from leadfinder.crm import CRM,STAGES
from leadfinder.lead_directory import LeadDirectory,DirectoryError
from leadfinder.lead_editor import LeadEditor
from leadfinder.funnels import FunnelStore
from leadfinder.geography import normalize_postcode

S={'type':'string'};I={'type':'integer'};B={'type':'boolean'}
IDS={'type':'array','items':I}


def obj(properties):
    return {'type':'object','properties':properties}


FILTERS={'search_id':S,'q':S,'category_id':I,'contact_status':S,'stage':S,'only_phone':B,'page':I}
EDIT={'name':S,'category':S,'phone':S,'address':S,'website':S,'hours':S,'plus_code':S,'description':S,
      'latitude':{'type':'number'},'longitude':{'type':'number'},'rating':{'type':'number'},'review_count':I}
CHANGES={'category_ids':IDS,'category_mode':S,'stage':S,'contact_status':S}
CONTEXT={key:S for key in ('product','differentials','audience','offer','tone')}
# name: description, policy, properties, genuinely required fields
TOOLS={
    'workspace_overview':('Consultar resumo, categorias, etapas e contexto do workspace.','read',{},()),
    'leads_list':('Encontrar leads por texto, categoria, contato ou etapa; 25 por página.','read',FILTERS,()),
    'leads_get':('Consultar a ficha, anotações e histórico de um lead pelo ID.','read',{'id':I},('id',)),
    'categories_list':('Listar categorias e seus IDs.','read',{},()),
    'categories_create':('Criar categoria de organização (nome de 2–60 caracteres).','write',{'name':S},('name',)),
    'messages_list':('Listar modelos de mensagem e seus IDs.','read',{},()),
    'messages_create':('Salvar mensagem solicitada pelo usuário (nome 2–80, texto 1–4000). Variáveis: {{empresa}}, {{nome}}, {{telefone}}, {{meu_nome}}, {{workspace}}, {{categoria}}, {{site}}, {{endereco}}.','write',{'name':S,'body':S},('name','body')),
    'messages_update':('Atualizar um modelo existente e solicitado, preservando snapshots de disparos.','write',{'id':I,'name':S,'body':S},('id','name','body')),
    'leads_organize':('Organizar até 1000 leads: categorias, contato e etapa. category_mode: add/replace/remove. Etapas: new/contacted/replied/demo/customer/lost.','write',{'ids':IDS,'changes':obj(CHANGES)},('ids','changes')),
    'leads_edit':('Corrigir campos do lead solicitado. Campos vazios limpam textos; origem e datas de coleta são preservadas.','write',{'id':I,'fields':obj(EDIT)},('id','fields')),
    'leads_delete':('Preparar exclusão dos leads indicados. Exige revisão e confirmação humana na interface.','confirm',{'ids':IDS},('ids',)),
    'funnels_list':('Listar funis segmentados existentes.','read',{},()),
    'funnels_create':('Criar um funil segmentado com as etapas padrão. Os filtros opcionais definem seu público; consulte categorias antes de usar IDs.','write',{'name':S,'q':S,'category_id':I,'contact_status':S,'only_phone':B},('name',)),
    'searches_list':('Consultar histórico e andamento das buscas do workspace.','read',{},()),
    'searches_cancel':('Interromper uma busca em andamento solicitada pelo usuário.','write',{'id':S},('id',)),
    'searches_start':('Iniciar extração no Google Maps pelo termo e região ou CEP/raio solicitados; limite de 1–100. Categoria opcional agrupa resultados.','write',{'term':S,'location':S,'max_results':I,'category_id':I,'require_phone':B,'postcode':S,'radius_km':{'type':'number'}},('term',)),
    'notes_create':('Salvar uma anotação solicitada na ficha de um lead.','write',{'lead_id':I,'body':S},('lead_id','body')),
    'reminders_create':('Criar lembrete para um lead. due_at deve ser ISO 8601 com fuso horário explícito.','write',{'lead_id':I,'title':S,'due_at':S},('lead_id','title','due_at')),
    'reminders_list':('Listar lembretes; filter: pending/overdue/completed/all.','read',{'filter':S},()),
    'reminders_complete':('Concluir ou reabrir um lembrete solicitado pelo usuário.','write',{'id':I,'completed':B},('id','completed')),
    'campaigns_list':('Consultar disparos existentes, IDs e resultados.','read',{},()),
    'campaigns_get':('Consultar textos, destinatários e IDs das tentativas de um disparo.','read',{'id':S},('id',)),
    'campaigns_prepare':('Preparar rascunho real a partir de IDs de mensagens e leads (até 100). Não envia.','write',{'name':S,'template_ids':IDS,'target_ids':IDS,'interval_seconds':I},('name','template_ids','target_ids')),
    'campaigns_start':('Propor início de um rascunho real. A execução requer confirmação humana após revisar todos os textos e destinatários.','confirm',{'id':S},('id',)),
    'campaigns_resume':('Propor retomada apenas dos pendentes de um disparo. Requer confirmação humana; tentativas incertas precisam ser verificadas primeiro.','confirm',{'id':S},('id',)),
    'campaigns_schedule':('Propor agenda de rascunho real. Requer confirmação humana; due_at ISO 8601 com fuso.','confirm',{'id':S,'due_at':S},('id','due_at')),
    'campaigns_pause':('Pausar um disparo em andamento solicitado pelo usuário.','write',{'id':S},('id',)),
    'campaigns_cancel':('Cancelar os restantes de um disparo solicitado pelo usuário.','write',{'id':S},('id',)),
    'campaigns_verify':('Consultar novamente uma tentativa sem confirmação, sem reenviá-la.','write',{'id':S,'message_id':I},('id','message_id')),
    'product_context_get':('Consultar o contexto salvo do produto.','read',{},()),
    'product_context_set':('Atualizar apenas os campos solicitados do contexto de produto para as próximas interações.','write',CONTEXT,()),
}


def schema_for(properties,required=()):
    result={}
    for key,original in properties.items():
        schema=dict(original)
        if schema['type']=='object':
            schema=schema_for(schema['properties'])
        if key not in required:
            schema={**schema,'type':[schema['type'],'null']}
        result[key]=schema
    return {'type':'object','properties':result,'required':list(properties),'additionalProperties':False}


def clean(arguments,properties,required=()):
    if not isinstance(arguments,dict) or not set(arguments)<=set(properties) or any(arguments.get(key) is None for key in required):
        raise AIError('Os argumentos da ferramenta estão incompletos ou contêm campos não permitidos.')
    result={}
    for key,value in arguments.items():
        if value is None:
            continue
        schema=properties[key];kind=schema['type']
        valid={'string':isinstance(value,str),'integer':type(value) is int,'boolean':type(value) is bool,
               'number':type(value) in (int,float) and math.isfinite(value) if type(value) in (int,float) else False,
               'array':isinstance(value,list),'object':isinstance(value,dict)}[kind]
        if not valid or (kind=='string' and len(value)>8000):
            raise AIError('Argumento inválido na ferramenta: '+key)
        if kind=='array' and (len(value)>1000 or any(type(item) is not int or item<1 for item in value)):
            raise AIError('A seleção de IDs da ferramenta é inválida.')
        result[key]=clean(value,schema['properties']) if kind=='object' else value
    return result


class AgentTools:
    def __init__(self,repo,outreach,campaigns,search_service,postcode_resolver=None):
        self.repo,self.outreach,self.campaigns,self.search=repo,outreach,campaigns,search_service
        self.postcodes=postcode_resolver

    def definitions(self):
        return [{'name':name,'description':spec[0],'parameters':schema_for(spec[2],spec[3])} for name,spec in TOOLS.items()]

    def validate(self,name,arguments):
        if name not in TOOLS:
            raise AIError('A ferramenta solicitada não está disponível no LeadFinder.')
        return clean(arguments,TOOLS[name][2],TOOLS[name][3])

    def execute(self,workspace,name,args):
        ws=workspace['id'];crm=CRM(self.repo);directory=LeadDirectory(self.repo)
        if name=='workspace_overview':
            return {'workspace':workspace['name'],'stats':self.repo.stats(ws),'categories':directory.categories(ws),
                    'stages':STAGES,'product':crm.context(ws)}
        if name=='leads_list':
            q=args.pop('q','');page=args.pop('page',1)
            if not 1<=page<=100000 or args.get('contact_status') not in (None,'','new','contacted','conversed') or args.get('stage') not in (None,'',*STAGES):
                raise DirectoryError('Filtros de leads inválidos.')
            return self.repo.list_leads(query=q[:200],page=page,workspace_id=ws,**args)
        if name=='leads_get':return crm.dossier(ws,args['id'])
        if name=='categories_list':return {'items':directory.categories(ws)}
        if name=='categories_create':return {'id':directory.save_category(ws,args['name']),'name':args['name']}
        if name=='messages_list':return {'items':self.outreach.templates(ws)}
        if name in ('messages_create','messages_update'):
            identity=self.outreach.save_template(ws,args['name'],args['body'],args.get('id'))
            return self.outreach.template(ws,identity)
        if name=='leads_organize':return crm.bulk(ws,args['ids'],args['changes'])
        if name=='leads_edit':
            lead=LeadEditor(self.repo).update(ws,args['id'],args['fields'])
            return {'id':lead['id'],'name':lead['name'],'updated':True}
        if name=='funnels_list':return {'items':FunnelStore(self.repo).list(ws)}
        if name=='funnels_create':
            name_value=args.pop('name');return FunnelStore(self.repo).create(ws,name_value,args)
        if name=='searches_list':return {'items':self.repo.searches(ws)}
        if name=='searches_cancel':
            search=self.repo.get_search(args['id'],ws)
            if not search:raise LookupError('Busca não encontrada neste workspace.')
            if search['status'] in ('queued','running'):self.repo.update_search(args['id'],cancel_requested=1)
            return {'id':args['id'],'message':'Interrupção solicitada.' if search['status'] in ('queued','running') else 'A busca já foi encerrada.'}
        if name=='searches_start':
            term=args['term'].strip();location=args.get('location','').strip();limit=args.get('max_results',30)
            if not 2<=len(term)<=120 or len(location)>160 or not 1<=limit<=100:
                raise DirectoryError('Termo, região ou limite da busca inválidos.')
            radius=args.get('radius_km',5);area=None
            if not .5<=radius<=50:raise DirectoryError('O raio deve estar entre 0,5 e 50 km.')
            if args.get('postcode','').strip():
                if not self.postcodes:raise DirectoryError('O serviço de CEP não está disponível.')
                area=self.postcodes.resolve(normalize_postcode(args['postcode'])).with_radius(radius);location=area.address
            return self.search.start(term,location,limit,workspace_id=ws,area=area,category_id=args.get('category_id'),require_phone=args.get('require_phone',True))
        if name=='notes_create':return {'id':crm.note(ws,args['lead_id'],args['body']),'lead_id':args['lead_id']}
        if name=='reminders_create':return {'id':crm.reminder(ws,args['lead_id'],args['title'],args['due_at']),'lead_id':args['lead_id']}
        if name=='reminders_list':return {'items':crm.reminders(ws,args.get('filter','pending'))}
        if name=='reminders_complete':crm.complete_reminder(ws,args['id'],args['completed']);return {'updated':True}
        if name=='campaigns_list':return {'items':self.outreach.campaigns(ws)}
        if name=='campaigns_get':
            campaign=self.outreach.campaign(ws,args['id'])
            if not campaign:raise LookupError('Disparo não encontrado.')
            return campaign
        if name=='campaigns_prepare':
            prepared=self.outreach.prepare(workspace,'Responsável pelo workspace',{'simulated':False,**args})
            identity=self.outreach.create_campaign(ws,prepared)
            return {'id':identity,'name':prepared['name'],'targets':prepared['target_count'],'messages':prepared['message_count'],'status':'draft','skipped':prepared['skipped']}
        if name=='campaigns_pause':self.campaigns.pause(ws,args['id']);return {'id':args['id'],'pause_requested':True}
        if name=='campaigns_cancel':
            if not self.outreach.campaign(ws,args['id'],False):raise LookupError('Disparo não encontrado.')
            self.campaigns.cancel(ws,args['id']);return {'id':args['id'],'cancel_requested':True}
        if name=='campaigns_verify':
            self.campaigns.reconcile(ws,args['id'],args['message_id'])
            return {'id':args['id'],'verified':True}
        if name=='product_context_get':return crm.context(ws)
        if name=='product_context_set':
            if not args:raise DirectoryError('Informe os campos do produto a atualizar.')
            return crm.context(ws,{**crm.context(ws),**args})
        raise AIError('Esta ação exige confirmação pela interface.')
