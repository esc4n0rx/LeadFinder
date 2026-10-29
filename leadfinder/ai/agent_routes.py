"""Agent workspace and human confirmation endpoints."""
from flask import Blueprint,current_app,g,jsonify,render_template,request
from leadfinder.auth import csrf_token,login_required
from leadfinder.ai.catalog import AIError
from leadfinder.ai.agent import public_action
from leadfinder.lead_directory import DirectoryError
from leadfinder.lead_editor import LeadConflict

agents=Blueprint('agents',__name__)


def service():return current_app.extensions['agent_service']


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):raise AIError('Envie os dados em JSON.')
    return data


@agents.errorhandler(AIError)
@agents.errorhandler(DirectoryError)
def invalid(error):return jsonify(error=str(error)),409 if isinstance(error,LeadConflict) else 400


@agents.after_request
def private(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@agents.get('/agents')
@login_required(workspace=True)
def page():return render_template('index.html',api_token=csrf_token(),initial_view='agents')


@agents.post('/api/agents/threads/<thread_id>/chat')
@login_required(workspace=True)
def chat(thread_id):return jsonify(service().chat(g.workspace,thread_id,body()))


@agents.get('/api/agents/actions/<identity>/preview')
@login_required(workspace=True)
def preview(identity):
    import json
    action=service().action(g.workspace['id'],identity)
    if action['status']!='pending' or not public_action(action)['requires_confirmation']:
        raise AIError('Esta ação não está aguardando confirmação.')
    return jsonify(action=public_action(action),preview=json.loads(action['preview']))


@agents.post('/api/agents/actions/<identity>/confirm')
@login_required(workspace=True)
def confirm(identity):
    if body().get('confirmed') is not True:raise AIError('Revise e confirme a ação pela interface.')
    return jsonify(service().run(g.workspace,identity,confirmed=True))


@agents.post('/api/agents/actions/<identity>/cancel')
@login_required(workspace=True)
def cancel(identity):return jsonify(service().cancel(g.workspace['id'],identity))
