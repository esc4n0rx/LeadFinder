"""Private per-workspace Node processes. No listening HTTP port or shared QR state."""

import atexit
import json
import logging
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
from uuid import uuid4


class IntegrationError(ValueError):
    pass


class DeliveryUncertain(IntegrationError):
    def __init__(self, message, provider_id=None):
        super().__init__(message)
        self.provider_id = provider_id


class BridgeProcess:
    def __init__(self, node, script, on_state=None):
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.process = subprocess.Popen([node, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf-8', bufsize=1, creationflags=flags)
        self.state = {'status':'disconnected','qr':None,'phone':None,'error':None}
        self.pending = {}
        self.sending = 0
        self.lock = threading.Lock()
        self.on_state = on_state
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                with self.lock:
                    if message.get('event') == 'state':
                        self.state = message['state']
                    elif message.get('id') in self.pending:
                        self.pending[message['id']].put(message)
                if message.get('event') == 'state':
                    self._notify(message['state'])
        finally:
            with self.lock:
                self.state = {'status':'disconnected','qr':None,'phone':None,'error':'O processo de conexão foi encerrado.'}
                for result in self.pending.values():
                    result.put({'ok':False,'error':'A conexão foi encerrada.'})
            self._notify(dict(self.state))

    def _notify(self, state):
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:
                logging.getLogger(__name__).error('Não foi possível registrar a mudança de estado do WhatsApp.')

    def request(self, action, timeout=20, **values):
        request_id, result = uuid4().hex, queue.Queue()
        with self.lock:
            if self.process.poll() is not None:
                raise IntegrationError('O processo de conexão foi encerrado. Reconecte o WhatsApp.')
            self.pending[request_id] = result
            if action == 'send':
                self.sending += 1
            try:
                self.process.stdin.write(json.dumps({'id':request_id,'action':action,**values})+'\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self.pending.pop(request_id, None)
                if action == 'send':
                    self.sending -= 1
                raise IntegrationError('A conexão com o WhatsApp foi encerrada.') from error
        try:
            response = result.get(timeout=timeout)
            if not response.get('ok'):
                raise IntegrationError(response.get('error', 'Falha de conexão.'))
            return response['data']
        except queue.Empty as error:
            exception = DeliveryUncertain if action == 'send' else IntegrationError
            raise exception('O resultado da operação não foi confirmado. Verifique a conexão antes de repetir.') from error
        finally:
            with self.lock:
                self.pending.pop(request_id, None)
                if action == 'send':
                    self.sending -= 1

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()


class WhatsAppRuntime:
    def __init__(self, data_path, node=None, browser=None):
        self.root = Path(data_path).resolve()
        self.node = node or os.environ.get('LEADFINDER_NODE_BINARY') or shutil.which('node')
        self.browser = browser or os.environ.get('LEADFINDER_WHATSAPP_BROWSER')
        self.processes = {}
        self.lock = threading.RLock()
        self.on_state = None
        atexit.register(self.close)

    def set_state_listener(self, listener):
        self.on_state = listener

    def connect(self, workspace_id, phone):
        with self.lock:
            old = self.processes.get(workspace_id)
            if old and old.process.poll() is None:
                if old.state['status'] in ('starting','qr','authenticating','ready','mismatch'):
                    return dict(old.state)
                old.close()
            script = Path(__file__).with_name('whatsapp')/'bridge.cjs'
            if not self.node:
                raise IntegrationError('Instale Node.js 22.12+ ou configure LEADFINDER_NODE_BINARY. Consulte o README.')
            try:
                version = subprocess.check_output([self.node,'--version'],text=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).strip().lstrip('v').split('.')
                if (int(version[0]),int(version[1])) < (22,12):
                    raise IntegrationError('Esta integração requer Node.js 22.12 ou mais recente.')
            except (OSError,subprocess.SubprocessError,ValueError,IndexError) as error:
                raise IntegrationError('Não foi possível verificar o Node.js. Confira a instalação.') from error
            if not (script.parent/'node_modules'/'whatsapp-web.js').exists():
                raise IntegrationError('Instale a integração: npm ci --prefix leadfinder/integrations/whatsapp')
            if not self.browser:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as playwright:
                    browser_path = playwright.chromium.executable_path
            else:
                browser_path = self.browser
            if not Path(browser_path).is_file():
                raise IntegrationError('Navegador não encontrado. Execute python -m playwright install chromium.')
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                bridge = BridgeProcess(self.node, script,lambda state: self.on_state(workspace_id,state) if self.on_state else None)
            except OSError as error:
                raise IntegrationError('Não foi possível iniciar Node.js. Confira a instalação.') from error
            self.processes[workspace_id] = bridge
            return bridge.request('connect',phone=phone,clientId=f'workspace-{int(workspace_id)}',authPath=str(self.root),
                                  cachePath=str(self.root/f'cache-{int(workspace_id)}'),browser=str(browser_path))

    def status(self, workspace_id):
        with self.lock:
            bridge = self.processes.get(workspace_id)
        if not bridge:
            return {'status':'disconnected','qr':None,'phone':None,'error':None}
        with bridge.lock:
            state = dict(bridge.state)
            sending = bridge.sending
        if bridge.process.poll() is not None:
            return {'status':'error','qr':None,'phone':None,'error':'O processo de conexão foi encerrado. Reconecte para restaurar a sessão salva.'}
        if state['status'] == 'ready' and not sending:
            return bridge.request('status', timeout=10)
        return state

    def send(self, workspace_id, phone, body, sender_phone):
        with self.lock:
            bridge = self.processes.get(workspace_id)
        if not bridge:
            raise IntegrationError('Reconecte o WhatsApp antes de enviar.')
        try:
            result = bridge.request('send', timeout=60, phone=phone, body=body, senderPhone=sender_phone)
        except IntegrationError as error:
            # A closed pipe/process during a send does not prove non-delivery.
            raise DeliveryUncertain(str(error)) from error
        if result.get('uncertain'):
            raise DeliveryUncertain(result['error'], provider_id=result.get('messageId'))
        if result.get('rejected'):
            raise IntegrationError(result['error'])
        if not result.get('messageId'):
            raise DeliveryUncertain('O WhatsApp não confirmou o identificador da mensagem.')
        return result['messageId']

    def disconnect(self, workspace_id):
        with self.lock:
            bridge = self.processes.pop(workspace_id, None)
        if bridge:
            try:
                bridge.request('disconnect', timeout=25)
            finally:
                bridge.close()
        # Forget only this workspace's local browser credentials, even when offline.
        target = (self.root/f'session-workspace-{int(workspace_id)}').resolve()
        if target.parent != self.root or target == self.root:
            raise IntegrationError('Diretório da sessão inválido.')
        if target.exists():
            try:
                shutil.rmtree(target)
            except OSError as error:
                raise IntegrationError('A sessão ainda está em uso. Feche o navegador e tente desconectar novamente.') from error

    def verify(self, workspace_id, message_id, sender_phone):
        with self.lock:
            bridge=self.processes.get(workspace_id)
        if not bridge:
            raise IntegrationError('Reconecte o WhatsApp para verificar a mensagem.')
        return bridge.request('verify',timeout=15,messageId=message_id,senderPhone=sender_phone)

    def suspend(self, workspace_id):
        """Close Chrome without logging out or deleting its credentials."""
        with self.lock:
            bridge=self.processes.pop(workspace_id,None)
        if bridge:
            bridge.close()

    def close(self):
        with self.lock:
            processes, self.processes = list(self.processes.values()), {}
        for process in processes:
            process.close()
