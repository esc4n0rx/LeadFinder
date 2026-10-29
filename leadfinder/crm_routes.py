"""Workspace-scoped CRM, lead selection, and export endpoints."""
import csv
import io

from flask import Blueprint,current_app,g,jsonify,render_template,request,Response

from leadfinder.auth import csrf_token,login_required
from leadfinder.crm import CRM,STAGES,validate_ids
from leadfinder.lead_directory import DirectoryError

crm=Blueprint('crm',__name__)


def service():
    return CRM(current_app.extensions['repository'])


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        raise DirectoryError('Envie os dados em JSON.')
    return data


@crm.errorhandler(DirectoryError)
def invalid(error):
    return jsonify(error=str(error)),400


@crm.errorhandler(LookupError)
def missing(error):
    return jsonify(error=str(error)),404


@crm.get('/tasks')
@crm.get('/pipeline')
@crm.get('/workspace')
@login_required(workspace=True)
def page():
    return render_template('index.html',api_token=csrf_token(),initial_view={'/tasks':'tasks','/pipeline':'pipeline','/workspace':'workspace'}[request.path])


@crm.get('/api/crm/stages')
@login_required(workspace=True)
def stages():
    return jsonify(stages=STAGES)


def funnel_filters():
    from leadfinder.funnels import FunnelStore
    identity=request.args.get('funnel_id','')
    if not identity:return {}
    if not identity.isdigit():raise DirectoryError('Funil inválido.')
    funnel=FunnelStore(service().repo).get(g.workspace['id'],int(identity))
    if not funnel:raise LookupError('Funil não encontrado neste workspace.')
    filters=dict(funnel['filters']);filters['scope_query']=filters.pop('q','')
    return filters


@crm.get('/api/funnels')
@login_required(workspace=True)
def funnels():
    from leadfinder.funnels import FunnelStore
    return jsonify(items=FunnelStore(service().repo).list(g.workspace['id']))


@crm.post('/api/funnels')
@login_required(workspace=True)
def create_funnel():
    from leadfinder.funnels import FunnelStore
    data=body()
    return jsonify(FunnelStore(service().repo).create(g.workspace['id'],data.get('name'),data.get('filters',{}))),201


@crm.get('/api/crm/board')
@login_required(workspace=True)
def board():
    filters=funnel_filters();query=request.args.get('q','')[:200]
    return jsonify(columns=[{'stage':key,'label':label,**service().repo.list_leads(query=query,workspace_id=g.workspace['id'],stage=key,**filters)} for key,label in STAGES.items()])


@crm.get('/api/crm/board/<stage>')
@login_required(workspace=True)
def board_page(stage):
    if stage not in STAGES:raise DirectoryError('Etapa inválida.')
    try:page=int(request.args.get('page',1))
    except ValueError:raise DirectoryError('Página inválida.') from None
    if not 1<=page<=100000:raise DirectoryError('Página inválida.')
    return jsonify(service().repo.list_leads(query=request.args.get('q','')[:200],page=page,workspace_id=g.workspace['id'],stage=stage,**funnel_filters()))


@crm.get('/api/leads/<int:lead_id>/dossier')
@login_required(workspace=True)
def dossier(lead_id):
    return jsonify(service().dossier(g.workspace['id'],lead_id))


@crm.post('/api/leads/<int:lead_id>/notes')
@login_required(workspace=True)
def note(lead_id):
    return jsonify(id=service().note(g.workspace['id'],lead_id,body().get('body'))),201


@crm.post('/api/leads/<int:lead_id>/reminders')
@login_required(workspace=True)
def reminder(lead_id):
    data=body()
    return jsonify(id=service().reminder(g.workspace['id'],lead_id,data.get('title'),data.get('due_at'))),201


@crm.route('/api/product-context',methods=['GET','POST'])
@login_required(workspace=True)
def context():
    return jsonify(service().context(g.workspace['id'],body() if request.method=='POST' else None))


@crm.get('/api/reminders')
@login_required(workspace=True)
def reminders():
    return jsonify(items=service().reminders(g.workspace['id'],request.args.get('filter','pending')))


@crm.post('/api/reminders/<int:reminder_id>')
@login_required(workspace=True)
def complete_reminder(reminder_id):
    service().complete_reminder(g.workspace['id'],reminder_id,body().get('completed'))
    return jsonify(ok=True)


@crm.post('/api/leads/bulk')
@login_required(workspace=True)
def bulk():
    data=body()
    return jsonify(service().bulk(g.workspace['id'],data.get('ids'),data.get('changes')))


def selection(data,limit=1000):
    repo=service().repo
    if 'ids' in data:
        ids=validate_ids(data['ids'],limit)
        with repo.connection() as db:
            service().require_leads(db,g.workspace['id'],ids)
        return ids
    filters=data.get('filters',{})
    if not isinstance(filters,dict) or not set(filters)<={'q','category_id','contact_status','stage','only_phone','search_id'}:
        raise DirectoryError('Filtros inválidos.')
    category=filters.get('category_id')
    if category in ('',None):
        category=None
    elif type(category) is not int or category<0:
        raise DirectoryError('Categoria inválida.')
    status=filters.get('contact_status')
    stage=filters.get('stage')
    if (status is not None and not isinstance(status,str)) or (stage is not None and not isinstance(stage,str)):
        raise DirectoryError('Filtros inválidos.')
    status=status or None;stage=stage or None
    query=filters.get('q','')
    if status not in (None,'new','contacted','conversed') or (stage is not None and (not isinstance(stage,str) or stage not in STAGES)) or not isinstance(query,str) or len(query)>200:
        raise DirectoryError('Filtros inválidos.')
    only_phone=filters.get('only_phone',False)
    search_id=filters.get('search_id','')
    if not isinstance(search_id,str) or len(search_id)>64:
        raise DirectoryError('Busca inválida.')
    if type(only_phone) is not bool:
        raise DirectoryError('Filtro de telefone inválido.')
    rows=repo.list_leads(query=query,workspace_id=g.workspace['id'],per_page=limit+1,
                        category_id=category,contact_status=status,stage=stage,only_phone=only_phone,search_id=search_id)
    if rows['total']>limit:
        raise DirectoryError(f'A seleção tem {rows["total"]} leads. Refine os filtros para no máximo {limit}.')
    return [row['id'] for row in rows['items']]


@crm.post('/api/leads/selection')
@login_required(workspace=True)
def select():
    ids=selection(body())
    return jsonify(ids=ids,total=len(ids))


@crm.post('/api/leads/brief')
@login_required(workspace=True)
def brief():
    ids=selection(body())
    if not ids:
        raise DirectoryError('Selecione leads para preparar a mensagem.')
    marks=','.join('?' for _ in ids)
    with service().repo.connection() as db:
        segments=[str(row[0])[:120] for row in db.execute(f'SELECT DISTINCT category FROM leads WHERE workspace_id=? AND id IN ({marks}) AND category IS NOT NULL ORDER BY category LIMIT 21',(g.workspace['id'],*ids))]
        groups=[row[0] for row in db.execute(f'''SELECT DISTINCT c.name FROM lead_category_links l
            JOIN lead_categories c ON c.id=l.category_id AND c.workspace_id=l.workspace_id
            WHERE l.workspace_id=? AND l.lead_id IN ({marks}) ORDER BY c.name LIMIT 21''',(g.workspace['id'],*ids))]
    segments=segments[:20]+(['outros segmentos da seleção'] if len(segments)>20 else [])
    groups=[str(group)[:60] for group in groups[:20]]+(['outros grupos da seleção'] if len(groups)>20 else [])
    return jsonify(brief=f'Prepare até 3 mensagens de WhatsApp com um CTA claro para uma seleção de {len(ids)} leads. '
        +'Segmentos informados pelo Maps: '+(', '.join(segments) or 'não informados')+'. '
        +'Grupos de organização da seleção: '+(', '.join(groups) or 'sem categoria')+'. '
        +'Use o contexto cadastrado do produto. Grupos são rótulos de organização; não presuma características individuais nem invente ofertas ou resultados. Faça perguntas se faltar informação.')


@crm.post('/api/leads/export')
@login_required(workspace=True)
def export():
    ids=selection(body(),10000)
    out=io.StringIO(newline='');writer=csv.writer(out,delimiter=';')
    writer.writerow(['Nome','Categorias','Categoria Maps','Telefone','Endereço','Site','Nota','Avaliações','Status','Etapa','Próxima ação','Horários','Plus Code','Latitude','Longitude','Descrição','Características','Preço','Situação no Maps','Maps','Primeira coleta','Última coleta'])
    for identity in ids:
        lead=service().repo.get_lead(identity,g.workspace['id'])
        details=lead['details']
        values=[lead['name'],', '.join(c['name'] for c in lead['categories']),lead['category'],lead['phone'],lead['address'],lead['website'],lead['rating'],lead['review_count'],lead['contact_status'],STAGES[lead['stage']],lead['next_action'],lead['hours'],lead['plus_code'],lead['latitude'],lead['longitude'],details.get('description'),', '.join(details.get('attributes',[])),details.get('price'),details.get('business_status'),lead['maps_url'],lead['first_seen_at'],lead['last_seen_at']]
        # Spreadsheet applications must not execute text collected from the web.
        writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in values])
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="leadfinder-leads.csv"'})
