"""HTTP boundary: validation, local request protection, and JSON responses."""

import math
from dataclasses import asdict

from flask import Blueprint, current_app, g, jsonify, redirect, render_template, request

from leadfinder.auth import csrf_token, login_required
from leadfinder.geography import GeographyError, normalize_postcode

from leadfinder.services import SearchBusy

web = Blueprint("web", __name__)


def repository():
    return current_app.extensions["repository"]


@web.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response


@web.get("/")
def index():
    if not g.user:
        return redirect('/welcome')
    if not g.workspace:
        return redirect('/setup')
    return render_template("index.html", api_token=csrf_token())


@web.get("/api/overview")
@login_required(workspace=True)
def overview():
    return jsonify(stats=repository().stats(g.workspace['id']), searches=repository().searches(g.workspace['id']))


@web.get('/history')
@login_required(workspace=True)
def history_page():
    return render_template('index.html',api_token=csrf_token(),initial_view='history')


@web.get('/api/postcodes/<postcode>')
@login_required(workspace=True)
def postcode_details(postcode):
    try:
        area = current_app.extensions['postcode_resolver'].resolve(normalize_postcode(postcode))
        return jsonify(asdict(area))
    except GeographyError as error:
        return jsonify(error=str(error)), 422


@web.post("/api/searches")
@login_required(workspace=True)
def create_search():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Dados de busca inválidos."), 400
    term, location, limit = data.get("term", ""), data.get("location", ""), data.get("max_results", 30)
    if not isinstance(term, str) or not 2 <= len(term.strip()) <= 120:
        return jsonify(error="Informe um termo entre 2 e 120 caracteres."), 400
    if not isinstance(location, str) or len(location.strip()) > 160:
        return jsonify(error="A região deve ter até 160 caracteres."), 400
    if type(limit) is not int or not 1 <= limit <= 100:
        return jsonify(error="Escolha entre 1 e 100 resultados."), 400
    require_phone = data.get('require_phone', True)
    category_id = data.get('category_id')
    if category_id is not None and (type(category_id) is not int or category_id<1):
        return jsonify(error='Selecione uma categoria válida.'),400
    if type(require_phone) is not bool:
        return jsonify(error='O filtro de telefone deve ser verdadeiro ou falso.'), 400
    postcode = data.get('postcode', '')
    if not isinstance(postcode, str):
        return jsonify(error='Informe um CEP válido.'), 400
    area = None
    radius = data.get('radius_km', 5)
    if type(radius) not in (float, int) or not math.isfinite(radius) or not .5 <= radius <= 50:
        return jsonify(error='O raio deve estar entre 0,5 e 50 km.'), 400
    if postcode.strip():
        try:
            area = current_app.extensions['postcode_resolver'].resolve(normalize_postcode(postcode)).with_radius(radius)
        except GeographyError as error:
            return jsonify(error=str(error)), 422
        location = area.address
    try:
        search = current_app.extensions["search_service"].start(term.strip(), location.strip(), limit,
            workspace_id=g.workspace['id'], area=area, require_phone=require_phone, category_id=category_id)
    except SearchBusy as error:
        return jsonify(error=str(error)), 409
    except ValueError as error:
        return jsonify(error=str(error)),400
    return jsonify(search), 202


@web.post("/api/searches/<search_id>/cancel")
@login_required(workspace=True)
def cancel_search(search_id):
    search = repository().get_search(search_id, g.workspace['id'])
    if not search:
        return jsonify(error="Busca não encontrada."), 404
    if search["status"] in {"queued", "running"}:
        repository().update_search(search_id, cancel_requested=1)
    return jsonify(ok=True)


@web.get("/api/leads")
@login_required(workspace=True)
def leads():
    try:
        page = int(request.args.get("page", "1"))
        if page < 1 or page > 1_000_000:
            raise ValueError()
    except ValueError:
        return jsonify(error="Página inválida."), 400
    category = request.args.get('category_id','')
    if category and (not category.isascii() or not category.isdigit() or len(category)>10):
        return jsonify(error='Categoria inválida.'),400
    status=request.args.get('contact_status','')
    stage=request.args.get('stage','')
    from leadfinder.crm import STAGES
    if stage and stage not in STAGES:
        return jsonify(error='Etapa inválida.'),400
    if status not in ('','new','contacted','conversed'):
        return jsonify(error='Status inválido.'),400
    return jsonify(repository().list_leads(request.args.get("q", "")[:200], request.args.get("search_id", ""), page,
        workspace_id=g.workspace['id'], only_phone=request.args.get('only_phone', 'false') == 'true',
        category_id=int(category) if category else None,contact_status=status or None,grouped=request.args.get('grouped')=='true',stage=stage or None))


@web.get("/api/leads/<int:lead_id>")
@login_required(workspace=True)
def lead_details(lead_id):
    lead = repository().get_lead(lead_id, g.workspace['id'])
    return jsonify(lead) if lead else (jsonify(error="Estabelecimento não encontrado."), 404)


@web.app_errorhandler(413)
def too_large(error):
    return jsonify(error="Requisição muito grande."), 413
