"""Authenticated AI integration and conversation endpoints."""

from flask import Blueprint, current_app, g, jsonify, render_template, request
from leadfinder.auth import csrf_token, login_required
from leadfinder.ai.catalog import AIError

ai = Blueprint('ai',__name__)


def service():
    return current_app.extensions['ai_service']


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        raise AIError('Envie os dados em JSON.')
    return data


@ai.errorhandler(AIError)
def ai_error(error):
    return jsonify(error=str(error)),400


@ai.get('/profile/integrations/ai')
@login_required(workspace=True)
def integrations_page():
    return render_template('index.html',api_token=csrf_token(),initial_view='ai')


@ai.get('/api/integrations/ai')
@login_required(workspace=True)
def integrations():
    return jsonify(providers=service().configurations(g.workspace['id']))


@ai.post('/api/integrations/ai/<provider>')
@login_required(workspace=True)
def save(provider):
    return jsonify(service().save(g.workspace['id'],provider,body()))


@ai.post('/api/integrations/ai/<provider>/remove')
@login_required(workspace=True)
def remove(provider):
    service().remove(g.workspace['id'],provider)
    return jsonify(ok=True)


@ai.post('/api/integrations/ai/<provider>/test')
@login_required(workspace=True)
def test(provider):
    return jsonify(service().test(g.workspace['id'],provider))


@ai.get('/api/integrations/ai/<provider>/models')
@login_required(workspace=True)
def models(provider):
    return jsonify(models=service().models(g.workspace['id'],provider),source='live')


@ai.route('/api/ai/threads',methods=['GET','POST'])
@login_required(workspace=True)
def threads():
    if request.method=='POST':
        return jsonify(service().new_thread(g.workspace['id'])),201
    return jsonify(items=service().threads(g.workspace['id']))


@ai.get('/api/ai/threads/<thread_id>')
@login_required(workspace=True)
def thread(thread_id):
    return jsonify(service().thread(g.workspace['id'],thread_id))


@ai.post('/api/ai/threads/<thread_id>/chat')
@login_required(workspace=True)
def chat(thread_id):
    return jsonify(service().chat(g.workspace['id'],thread_id,body()))
