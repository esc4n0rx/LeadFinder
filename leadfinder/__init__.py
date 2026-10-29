"""Flask application factory and composition root."""

import os
import secrets
from pathlib import Path

from flask import Flask,g,jsonify,request

from leadfinder.repository import Repository
from leadfinder.services import SearchService


def create_app(config=None, collector_factory=None, postcode_resolver=None, whatsapp_provider=None, ai_provider=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("LEADFINDER_DATABASE", str(Path(app.instance_path) / "leadfinder.sqlite3")),
        HEADLESS=os.environ.get("LEADFINDER_HEADLESS", "true").lower() != "false",
        BROWSER_CHANNEL=os.environ.get("LEADFINDER_BROWSER_CHANNEL") or None,
        MAX_CONTENT_LENGTH=32 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('LEADFINDER_SECURE_COOKIES', 'false').lower() == 'true',
    )
    if config:
        app.config.update(config)
    @app.before_request
    def backup_upload_limit():
        if request.path=='/api/backups/preview':
            request.max_content_length=65*1024*1024
    if not app.config.get('SECRET_KEY'):
        secret_path = Path(app.config['DATABASE']).resolve().parent / '.session-secret'
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with secret_path.open('x', encoding='utf-8') as secret_file:
                secret_file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        app.config['SECRET_KEY'] = secret_path.read_text(encoding='utf-8').strip()
    repository = Repository(app.config["DATABASE"])
    repository.initialize()
    repository.recover_interrupted()
    if collector_factory is None:
        from leadfinder.collectors.google_maps import GoogleMapsCollector

        collector_factory = lambda: GoogleMapsCollector(
            headless=app.config["HEADLESS"], channel=app.config["BROWSER_CHANNEL"]
        )
    app.extensions["repository"] = repository
    from leadfinder.accounts import AccountStore
    from leadfinder.auth import auth
    from leadfinder.geography import PostcodeResolver
    app.extensions['accounts'] = AccountStore(repository)
    app.extensions['postcode_resolver'] = postcode_resolver or PostcodeResolver(app.config['HEADLESS'], app.config['BROWSER_CHANNEL'])
    app.extensions["search_service"] = SearchService(repository, collector_factory)
    from leadfinder.outreach import OutreachStore, IntegrationService
    from leadfinder.campaigns import CampaignService
    from leadfinder.integrations.whatsapp_runtime import WhatsAppRuntime
    from leadfinder.outreach_routes import outreach
    outreach_store = OutreachStore(repository)
    outreach_store.recover()
    provider = whatsapp_provider or WhatsAppRuntime(Path(repository.database).parent/'whatsapp')
    integration_service = IntegrationService(outreach_store,provider)
    app.extensions['outreach_store'] = outreach_store
    app.extensions['whatsapp_integration'] = integration_service
    app.extensions['campaign_service'] = CampaignService(outreach_store,integration_service)
    from leadfinder.routes import web

    app.register_blueprint(auth)
    app.register_blueprint(web)
    app.register_blueprint(outreach)
    from leadfinder.directory_routes import directory
    app.register_blueprint(directory)
    from leadfinder.lead_routes import lead_edit
    app.register_blueprint(lead_edit)
    from leadfinder.crm_routes import crm
    app.register_blueprint(crm)
    from leadfinder.workspace_gate import WorkspaceGate,WorkspaceBusy
    from leadfinder.backups import BackupService
    from leadfinder.backup_routes import backups
    gate=WorkspaceGate()
    app.extensions['workspace_gate']=gate
    app.extensions['backups']=BackupService(repository,integration_service,gate)
    app.register_blueprint(backups)
    @app.errorhandler(WorkspaceBusy)
    def workspace_busy(error):
        return jsonify(error=str(error)),409
    @app.before_request
    def workspace_mutation():
        workspace=g.get('workspace')
        if workspace and request.method=='POST' and not request.path.startswith('/api/backups/'):
            gate.enter(workspace['id']);g.workspace_lease=workspace['id']
    @app.teardown_request
    def release_workspace(error):
        identity=g.pop('workspace_lease',None)
        if identity is not None:
            gate.leave(identity)
    from leadfinder.ai.service import AIService
    from leadfinder.ai.routes import ai
    app.extensions['ai_service']=AIService(repository,ai_provider)
    app.register_blueprint(ai)
    from leadfinder.ai.agent import AgentService
    from leadfinder.ai.agent_tools import AgentTools
    from leadfinder.ai.agent_routes import agents
    app.extensions['agent_service']=AgentService(app.extensions['ai_service'],AgentTools(repository,outreach_store,app.extensions['campaign_service'],app.extensions['search_service'],app.extensions['postcode_resolver']))
    app.register_blueprint(agents)
    integration_service.restore_sessions()
    from leadfinder.scheduler import CampaignScheduler
    app.extensions['scheduler']=CampaignScheduler(app.extensions['campaign_service'],gate)
    if not app.config['TESTING']:
        app.extensions['scheduler'].start()
    return app
