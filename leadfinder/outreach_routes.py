"""Authenticated messaging, WhatsApp configuration, and campaign HTTP boundaries."""

from flask import Blueprint, current_app, g, jsonify, render_template, request, redirect, url_for

from leadfinder.auth import csrf_token, login_required
from leadfinder.outreach import OutreachError, VARIABLES
from leadfinder.integrations.whatsapp_runtime import IntegrationError

outreach = Blueprint('outreach',__name__)


def store():
    return current_app.extensions['outreach_store']


def integration():
    return current_app.extensions['whatsapp_integration']


def body():
    data = request.get_json(silent=True)
    if not isinstance(data,dict):
        raise OutreachError('Envie os dados da operação em JSON.')
    return data


@outreach.errorhandler(OutreachError)
@outreach.errorhandler(IntegrationError)
def outreach_error(error):
    return jsonify(error=str(error)),400


@outreach.get('/profile/integrations')
@login_required(workspace=True)
def integrations_page():
    return render_template('index.html', api_token=csrf_token(), initial_view='integrations')


@outreach.get('/messages')
@login_required(workspace=True)
def messages_page():
    if request.args.get('tab')=='assistant':
        return redirect(url_for('agents.page',conversation=request.args.get('conversation','')),code=303)
    return render_template('index.html',api_token=csrf_token(),initial_view='messages')


@outreach.get('/automation')
@login_required(workspace=True)
def automation_page():
    return render_template('index.html',api_token=csrf_token(),initial_view='automation')


@outreach.route('/api/integrations/whatsapp',methods=['GET','POST'])
@login_required(workspace=True)
def whatsapp_config():
    if request.method == 'POST':
        data = body()
        integration().save(g.workspace['id'],data.get('name'),data.get('phone'))
    return jsonify(integration().status(g.workspace['id']))


@outreach.post('/api/integrations/whatsapp/connect')
@login_required(workspace=True)
def whatsapp_connect():
    integration().connect(g.workspace['id'])
    return jsonify(integration().status(g.workspace['id'])),202


@outreach.post('/api/integrations/whatsapp/disconnect')
@login_required(workspace=True)
def whatsapp_disconnect():
    integration().disconnect(g.workspace['id'])
    return jsonify(integration().status(g.workspace['id']))


@outreach.route('/api/messages',methods=['GET','POST'])
@login_required(workspace=True)
def messages():
    if request.method == 'GET':
        return jsonify(items=store().templates(g.workspace['id']),variables=VARIABLES)
    data = body()
    template_id = store().save_template(g.workspace['id'],data.get('name'),data.get('body'))
    return jsonify(store().template(g.workspace['id'],template_id)),201


@outreach.post('/api/messages/<int:template_id>')
@login_required(workspace=True)
def update_message(template_id):
    if not store().template(g.workspace['id'],template_id):
        return jsonify(error='Mensagem não encontrada.'),404
    data = body()
    store().save_template(g.workspace['id'],data.get('name'),data.get('body'),template_id)
    return jsonify(store().template(g.workspace['id'],template_id))


@outreach.post('/api/messages/<int:template_id>/archive')
@login_required(workspace=True)
def archive_message(template_id):
    if not store().archive_template(g.workspace['id'],template_id):
        return jsonify(error='Mensagem não encontrada.'),404
    return jsonify(ok=True)


@outreach.get('/api/outreach/targets')
@login_required(workspace=True)
def targets():
    try:
        page = int(request.args.get('page',1))
        if not 1 <= page <= 100000:
            raise ValueError()
    except ValueError:
        return jsonify(error='Página inválida.'),400
    result = store().repo.list_leads(query=request.args.get('q','')[:120],search_id=request.args.get('search_id',''),
        workspace_id=g.workspace['id'],page=page,per_page=25,only_phone=True,
        **target_filters())
    return jsonify(result)


def target_filters():
    category=request.args.get('category_id','')
    status=request.args.get('contact_status','')
    stage=request.args.get('stage','')
    from leadfinder.crm import STAGES
    if category and (not category.isascii() or not category.isdigit() or len(category)>10):
        raise OutreachError('Categoria inválida.')
    if status not in ('','new','contacted','conversed') or (stage and stage not in STAGES):
        raise OutreachError('Filtros inválidos.')
    return {'category_id':int(category) if category else None,'contact_status':status or None,'stage':stage or None}


@outreach.route('/api/campaigns',methods=['GET','POST'])
@login_required(workspace=True)
def campaigns():
    if request.method == 'GET':
        return jsonify(items=store().campaigns(g.workspace['id']))
    prepared = store().prepare(g.workspace,g.user['name'],body())
    campaign_id = store().create_campaign(g.workspace['id'],prepared)
    return jsonify(campaign=store().campaign(g.workspace['id'],campaign_id),skipped=prepared['skipped']),201


@outreach.get('/api/campaigns/<campaign_id>')
@login_required(workspace=True)
def campaign_detail(campaign_id):
    campaign = store().campaign(g.workspace['id'],campaign_id)
    return jsonify(campaign) if campaign else (jsonify(error='Disparo não encontrado.'),404)


@outreach.post('/api/campaigns/<campaign_id>/start')
@login_required(workspace=True)
def start_campaign(campaign_id):
    if not store().campaign(g.workspace['id'],campaign_id):
        return jsonify(error='Disparo não encontrado.'),404
    current_app.extensions['campaign_service'].start(g.workspace['id'],campaign_id)
    return jsonify(store().campaign(g.workspace['id'],campaign_id)),202


@outreach.post('/api/campaigns/<campaign_id>/cancel')
@login_required(workspace=True)
def cancel_campaign(campaign_id):
    if not store().campaign(g.workspace['id'],campaign_id):
        return jsonify(error='Disparo não encontrado.'),404
    current_app.extensions['campaign_service'].cancel(g.workspace['id'],campaign_id)
    return jsonify(store().campaign(g.workspace['id'],campaign_id))


@outreach.post('/api/campaigns/<campaign_id>/resume')
@login_required(workspace=True)
def resume_campaign(campaign_id):
    current_app.extensions['campaign_service'].start(g.workspace['id'],campaign_id,resume=True)
    return jsonify(store().campaign(g.workspace['id'],campaign_id)),202


@outreach.post('/api/campaigns/<campaign_id>/pause')
@login_required(workspace=True)
def pause_campaign(campaign_id):
    current_app.extensions['campaign_service'].pause(g.workspace['id'],campaign_id)
    return jsonify(store().campaign(g.workspace['id'],campaign_id))


@outreach.post('/api/campaigns/<campaign_id>/schedule')
@login_required(workspace=True)
def schedule_campaign(campaign_id):
    current_app.extensions['campaign_service'].schedule(g.workspace['id'],campaign_id,body().get('due_at'))
    return jsonify(store().campaign(g.workspace['id'],campaign_id)),202


@outreach.post('/api/campaigns/<campaign_id>/messages/<int:message_id>/verify')
@login_required(workspace=True)
def verify_campaign(campaign_id,message_id):
    current_app.extensions['campaign_service'].reconcile(g.workspace['id'],campaign_id,message_id,body().get('resolution'))
    return jsonify(store().campaign(g.workspace['id'],campaign_id))
