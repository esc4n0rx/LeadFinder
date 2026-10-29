"""Scoped manual edit and reviewed deletion of catalog leads."""
from flask import Blueprint,current_app,g,jsonify,request
from leadfinder.auth import login_required
from leadfinder.lead_editor import LeadEditor,LeadConflict
from leadfinder.lead_directory import DirectoryError

lead_edit=Blueprint('lead_edit',__name__)


def service():return LeadEditor(current_app.extensions['repository'])


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):raise DirectoryError('Envie os dados em JSON.')
    return data


@lead_edit.errorhandler(DirectoryError)
def invalid(error):return jsonify(error=str(error)),409 if isinstance(error,LeadConflict) else 400


@lead_edit.errorhandler(LookupError)
def missing(error):return jsonify(error=str(error)),404


@lead_edit.post('/api/leads/<int:lead_id>/edit')
@login_required(workspace=True)
def edit(lead_id):return jsonify(service().update(g.workspace['id'],lead_id,body()))


@lead_edit.post('/api/leads/delete-preview')
@login_required(workspace=True)
def preview():return jsonify(service().preview(g.workspace['id'],body().get('ids')))


@lead_edit.post('/api/leads/delete')
@login_required(workspace=True)
def delete():
    data=body()
    if data.get('confirmed') is not True:raise DirectoryError('Revise os leads e confirme a exclusão.')
    return jsonify(service().delete(g.workspace['id'],data.get('ids'),data.get('fingerprint')))
