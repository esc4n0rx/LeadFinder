"""Authenticated endpoints for workspace categories and lead organization."""
from flask import Blueprint, current_app, g, jsonify, render_template, request

from leadfinder.auth import csrf_token, login_required
from leadfinder.lead_directory import DirectoryError, LeadDirectory

directory=Blueprint('directory',__name__)


def store():
    return LeadDirectory(current_app.extensions['repository'])


@directory.get('/leads')
@login_required(workspace=True)
def leads_page():
    return render_template('index.html',api_token=csrf_token(),initial_view='leads')


@directory.get('/api/categories')
@login_required(workspace=True)
def categories():
    return jsonify(items=store().categories(g.workspace['id']))


@directory.post('/api/categories')
@login_required(workspace=True)
def create_category():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error='Dados inválidos.'),400
    category_id=store().save_category(g.workspace['id'],data.get('name'))
    return jsonify(id=category_id),201


@directory.post('/api/categories/<int:category_id>')
@login_required(workspace=True)
def rename_category(category_id):
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error='Dados inválidos.'),400
    store().save_category(g.workspace['id'],data.get('name'),category_id)
    return jsonify(ok=True)


@directory.post('/api/categories/<int:category_id>/delete')
@login_required(workspace=True)
def delete_category(category_id):
    store().delete_category(g.workspace['id'],category_id)
    return jsonify(ok=True)


@directory.post('/api/leads/<int:lead_id>/organization')
@login_required(workspace=True)
def organize_lead(lead_id):
    store().update_lead(g.workspace['id'],lead_id,request.get_json(silent=True))
    return jsonify(ok=True)


@directory.errorhandler(DirectoryError)
def invalid(error):
    return jsonify(error=str(error)),400


@directory.errorhandler(LookupError)
def missing(error):
    return jsonify(error=str(error)),404
