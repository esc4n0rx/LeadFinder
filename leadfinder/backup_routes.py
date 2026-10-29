"""Encrypted downloads and explicit preview/confirmation of workspace restores."""
import io
from pathlib import Path

from flask import Blueprint,current_app,g,jsonify,request,send_file
from werkzeug.security import check_password_hash

from leadfinder.auth import login_required
from leadfinder.backups import BackupError,MAX_ARCHIVE
from leadfinder.ai.catalog import AIError

backups=Blueprint('backups',__name__)


def service():
    return current_app.extensions['backups']


@backups.errorhandler(BackupError)
@backups.errorhandler(AIError)
def invalid(error):
    return jsonify(error=str(error)),400


@backups.after_request
def private(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


def body():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        raise BackupError('Envie os dados em JSON.')
    return data


@backups.post('/api/backups/export')
@login_required(workspace=True)
def export():
    raw=service().export(g.workspace['id'],body().get('password'))
    return send_file(io.BytesIO(raw),mimetype='application/octet-stream',as_attachment=True,download_name='leadfinder-workspace.lfbackup')


@backups.post('/api/backups/preview')
@login_required(workspace=True)
def preview():
    upload=request.files.get('file')
    if not upload:
        raise BackupError('Selecione um arquivo .lfbackup.')
    raw=upload.stream.read(MAX_ARCHIVE+1)
    return jsonify(service().preview(g.workspace['id'],g.user['id'],raw,request.form.get('password')))


@backups.post('/api/backups/restore')
@login_required(workspace=True)
def restore():
    data=body()
    account_password=data.get('account_password')
    if not isinstance(account_password,str) or not check_password_hash(g.user['password_hash'],account_password):
        raise BackupError('Confirme a senha atual da sua conta para restaurar o workspace.')
    return jsonify(service().restore(g.workspace['id'],g.user['id'],data.get('token'),data.get('password'),data.get('confirmation')))


@backups.get('/api/backups/recovery')
@login_required(workspace=True)
def recovery():
    folder=Path(service().repo.database).parent/'backups'
    files=sorted(folder.glob(f'workspace-{int(g.workspace["id"])}-*.lfbackup'),key=lambda path:path.stat().st_mtime,reverse=True)
    if not files:
        return jsonify(error='Nenhuma cópia anterior à restauração está disponível.'),404
    return send_file(files[0],mimetype='application/octet-stream',as_attachment=True,download_name='leadfinder-antes-da-restauracao.lfbackup')
