"""HTML authentication/onboarding flows, CSRF tokens and request identity."""

import hmac
import re
import secrets
from functools import wraps

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from leadfinder.accounts import AccountError

auth = Blueprint('auth', __name__)
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))


def accounts():
    return current_app.extensions['accounts']


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


@auth.before_app_request
def load_identity():
    if request.host.split(':')[0].lower() not in {'localhost', '127.0.0.1'}:
        return jsonify(error='Host não permitido.'), 403
    g.user = accounts().session_user(request.cookies.get('leadfinder_auth'))
    g.workspace = accounts().workspace(g.user['id']) if g.user else None
    if request.method == 'POST':
        token = request.headers.get('X-LeadFinder-Token', '') if request.is_json else request.form.get('csrf_token', '')
        expected = session.get('csrf', '')
        if not expected or not hmac.compare_digest(str(token).encode(), expected.encode()):
            if request.path.startswith('/api/'):
                return jsonify(error='Sessão expirada. Recarregue a página.'), 403
            return render_template('auth.html', mode='expired', error='Sua sessão expirou. Recarregue a página para continuar.'), 403


@auth.app_context_processor
def identity_context():
    return {'csrf_token': csrf_token, 'current_user': g.get('user'), 'workspace': g.get('workspace')}


def login_required(workspace=False):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not g.user:
                if request.path.startswith('/api/'):
                    return jsonify(error='Entre na sua conta para continuar.', redirect='/login'), 401
                return redirect(url_for('auth.login'))
            if workspace and not g.workspace:
                if request.path.startswith('/api/'):
                    return jsonify(error='Crie seu workspace para continuar.', redirect='/setup'), 403
                return redirect(url_for('auth.setup'))
            return function(*args, **kwargs)
        return wrapped
    return decorator


def validate_identity(data):
    name, username, email = (data.get(key, '').strip() for key in ('name', 'username', 'email'))
    if not 2 <= len(name) <= 80:
        raise AccountError('Informe seu nome entre 2 e 80 caracteres.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username):
        raise AccountError('Use de 3 a 32 letras, números, pontos, hífens ou sublinhados no usuário.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise AccountError('Informe um email válido.')
    return name, username, email


def validate_password(password, confirmation):
    if not 8 <= len(password) <= 128:
        raise AccountError('A senha deve ter entre 8 e 128 caracteres.')
    if password != confirmation:
        raise AccountError('As senhas não coincidem.')


def signed_in(user_id, destination):
    accounts().revoke_session(request.cookies.get('leadfinder_auth'))
    session.clear()
    response = redirect(destination, code=303)
    response.set_cookie('leadfinder_auth', accounts().new_session(user_id), max_age=7*86400,
                        httponly=True, secure=current_app.config['SESSION_COOKIE_SECURE'], samesite='Lax', path='/')
    return response


@auth.get('/welcome')
def welcome():
    if g.user:
        return redirect('/' if g.workspace else '/setup')
    return render_template('auth.html', mode='welcome')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if g.user:
        return redirect('/' if g.workspace else '/setup')
    error = None
    if request.method == 'POST':
        try:
            name, username, email = validate_identity(request.form)
            password = request.form.get('password', '')
            validate_password(password, request.form.get('password_confirmation', ''))
            user_id = accounts().create_user(name, username, email, password)
            return signed_in(user_id, '/setup')
        except AccountError as issue:
            error = str(issue)
    return render_template('auth.html', mode='register', error=error), 400 if error else 200


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect('/' if g.workspace else '/setup')
    error, status = None, 200
    if request.method == 'POST':
        username, password = request.form.get('username', '').strip(), request.form.get('password', '')
        key = accounts().token_hash(request.remote_addr + ':' + username[:32].casefold())
        if accounts().login_blocked(key):
            error, status = 'Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.', 429
        else:
            user = accounts().find_username(username) if re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username) else None
            valid = check_password_hash(user['password_hash'] if user else DUMMY_HASH, password[:129])
            accounts().record_login(key, bool(user and valid))
            if user and valid:
                return signed_in(user['id'], '/' if accounts().workspace(user['id']) else '/setup')
            error, status = 'Nome de usuário ou senha inválidos.', 400
    return render_template('auth.html', mode='login', error=error), status


@auth.route('/setup', methods=['GET', 'POST'])
@login_required()
def setup():
    if g.workspace:
        return redirect('/')
    error = None
    if request.method == 'POST':
        name = request.form.get('workspace_name', '').strip()
        if not 2 <= len(name) <= 80:
            error = 'Dê um nome ao workspace entre 2 e 80 caracteres.'
        else:
            accounts().setup_workspace(g.user['id'], name)
            return redirect('/', code=303)
    return render_template('auth.html', mode='setup', error=error, legacy_count=accounts().legacy_count(g.user['id'])), 400 if error else 200


@auth.route('/profile', methods=['GET', 'POST'])
@login_required(workspace=True)
def profile():
    error = None
    if request.method == 'POST':
        try:
            name, username, email = validate_identity(request.form)
            password = request.form.get('new_password', '')
            if not check_password_hash(g.user['password_hash'], request.form.get('current_password', '')[:129]):
                raise AccountError('A senha atual não confere.')
            if password:
                validate_password(password, request.form.get('password_confirmation', ''))
            accounts().update_profile(g.user['id'], name, username, email, password or None)
            return signed_in(g.user['id'], '/profile?saved=1')
        except AccountError as issue:
            error = str(issue)
    return render_template('index.html', api_token=csrf_token(), initial_view='profile', error=error, saved=request.args.get('saved') == '1'), 400 if error else 200


@auth.post('/logout')
def logout():
    accounts().revoke_session(request.cookies.get('leadfinder_auth'))
    session.clear()
    response = redirect('/welcome', code=303)
    response.delete_cookie('leadfinder_auth', path='/')
    return response
