"""Encrypted, workspace-scoped portable backups with validated, atomic restores."""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
from pathlib import Path,PurePosixPath
import shutil
import sqlite3
import tempfile
import threading
import time
from uuid import uuid4
import zipfile

from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from leadfinder.ai.credentials import CredentialVault
from leadfinder.repository import now
from leadfinder.workspace_gate import WorkspaceBusy

MAGIC=b'LEADFINDER8\n'
MAX_ARCHIVE=64*1024*1024
MAX_EXPANDED=128*1024*1024
TABLES=('lead_categories','lead_funnels','searches','leads','search_leads','lead_category_links','lead_contacts',
        'lead_profiles','lead_notes','lead_events','reminders','message_templates','campaigns',
        'campaign_messages','campaign_jobs','outreach_events','ai_integrations','ai_threads','ai_turns','ai_tool_calls',
        'product_context','whatsapp_integrations')
REMAP={'searches':{'lead_category_id':'lead_categories'},'search_leads':{'search_id':'searches','lead_id':'leads'},
       'lead_category_links':{'lead_id':'leads','category_id':'lead_categories'},
       **{table:{'lead_id':'leads'} for table in ('lead_contacts','lead_profiles','lead_notes','lead_events','reminders')},
       **{table:{'campaign_id':'campaigns'} for table in ('campaign_messages','campaign_jobs','outreach_events')},
       'ai_turns':{'thread_id':'ai_threads'},'ai_tool_calls':{'thread_id':'ai_threads','turn_id':'ai_turns'}}
SKIP={'Cache','Code Cache','GPUCache','ShaderCache','GrShaderCache','Crashpad','CacheStorage',
      'DawnGraphiteCache','DawnWebGPUCache','BrowserMetrics','Safe Browsing'}


class BackupError(ValueError):
    pass


def password_cipher(password,salt):
    if not isinstance(password,str) or not 12<=len(password)<=200:
        raise BackupError('Use uma senha de backup entre 12 e 200 caracteres.')
    key=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=600000).derive(password.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def seal(raw,password):
    salt=os.urandom(16)
    return MAGIC+salt+password_cipher(password,salt).encrypt(raw)


def unseal(raw,password):
    if len(raw)>MAX_ARCHIVE or not raw.startswith((MAGIC,b'LEADFINDER7\n')):
        raise BackupError('Arquivo de backup inválido ou maior que 64 MB.')
    try:
        return password_cipher(password,raw[len(MAGIC):len(MAGIC)+16]).decrypt(raw[len(MAGIC)+16:])
    except (InvalidToken,ValueError):
        raise BackupError('A senha está incorreta ou o backup foi alterado.') from None


class BackupService:
    def __init__(self,repo,integration,gate):
        self.repo,self.integration,self.gate=repo,integration,gate
        self.root=Path(repo.database).parent
        self.vault=CredentialVault(self.root/'.ai-credentials.key')
        self.previews={}
        self.lock=threading.RLock()

    def idle(self,workspace_id):
        with self.repo.connection() as db:
            checks=(('searches',"status IN ('queued','running')"),('campaigns',"status='running'"),('ai_turns',"status='pending'"))
            if any(db.execute(f'SELECT 1 FROM {table} WHERE workspace_id=? AND {condition} LIMIT 1',(workspace_id,)).fetchone() for table,condition in checks):
                raise WorkspaceBusy('Finalize ou pause buscas, disparos e gerações de IA antes do backup.')

    def suspend(self,workspace_id):
        method=getattr(self.integration.provider,'suspend',None)
        if method:
            method(workspace_id)

    def resume(self,workspace_id):
        config=self.integration.store.integration(workspace_id)
        if config and config['enabled']:
            self.integration._restore(workspace_id)

    def snapshot(self,workspace_id):
        packet={'format':8,'created_at':now(),'tables':{}}
        with self.repo.connection() as db:
            db.execute('BEGIN')
            workspace=db.execute('SELECT id,name FROM workspaces WHERE id=?',(workspace_id,)).fetchone()
            packet['workspace']=dict(workspace)
            for table in TABLES:
                if table=='search_leads':
                    query='SELECT * FROM search_leads WHERE search_id IN (SELECT id FROM searches WHERE workspace_id=?)'
                elif table=='campaign_messages':
                    query='SELECT * FROM campaign_messages WHERE campaign_id IN (SELECT id FROM campaigns WHERE workspace_id=?)'
                else:
                    query=f'SELECT * FROM {table} WHERE workspace_id=?'
                packet['tables'][table]=[dict(row) for row in db.execute(query,(workspace_id,))]
        output=io.BytesIO()
        archive_key=None
        if packet['tables']['ai_integrations']:
            archive_key=Fernet.generate_key();archive_cipher=Fernet(archive_key)
            for config in packet['tables']['ai_integrations']:
                config['encrypted_key']=archive_cipher.encrypt(self.vault.decrypt(config['encrypted_key']).encode()).decode()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('workspace.json',json.dumps(packet,ensure_ascii=False))
            if archive_key:
                archive.writestr('ai-key',archive_key)
            profile=self.root/'whatsapp'/f'session-workspace-{int(workspace_id)}'
            total=0;count=0
            if profile.exists():
                for path in profile.rglob('*'):
                    relative=path.relative_to(profile)
                    if not path.is_file() or path.is_symlink() or any(part in SKIP for part in relative.parts) or path.name in ('LOCK','LOG','LOG.old','DevToolsActivePort','SingletonLock','SingletonCookie','SingletonSocket'):
                        continue
                    total+=path.stat().st_size;count+=1
                    if total>MAX_EXPANDED or count>6000:
                        raise BackupError('A sessão do WhatsApp excede o limite do backup. Remova caches do navegador e tente novamente.')
                    archive.write(path,'whatsapp/'+relative.as_posix())
        return output.getvalue()

    def export(self,workspace_id,password):
        password_cipher(password,b'0'*16)
        with self.gate.exclusive(workspace_id),self.integration.operation(workspace_id):
            self.idle(workspace_id);self.suspend(workspace_id)
            try:
                result=seal(self.snapshot(workspace_id),password)
                if len(result)>MAX_ARCHIVE:
                    raise BackupError('O backup excede 64 MB.')
                return result
            finally:
                self.resume(workspace_id)

    def unpack(self,raw,password):
        try:
            archive=zipfile.ZipFile(io.BytesIO(unseal(raw,password)))
            entries=archive.infolist()
            if len(entries)>6002 or sum(entry.file_size for entry in entries)>MAX_EXPANDED:
                raise BackupError('O conteúdo expandido excede o limite do backup.')
            names=set();files={}
            for entry in entries:
                path=PurePosixPath(entry.filename)
                reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
                unsafe=any(':' in part or part.rstrip(' .')!=part or part.split('.')[0].upper() in reserved for part in path.parts)
                if unsafe or entry.filename!=path.as_posix() or entry.is_dir() or path.is_absolute() or '..' in path.parts or '\\' in entry.filename or entry.filename in names or (entry.external_attr>>16)&0o170000==0o120000:
                    raise BackupError('Caminho inválido no backup.')
                if entry.filename not in ('workspace.json','ai-key') and not entry.filename.startswith('whatsapp/'):
                    raise BackupError('O backup contém um arquivo desconhecido.')
                names.add(entry.filename);files[entry.filename]=archive.read(entry)
            packet=json.loads(files['workspace.json'])
            if isinstance(packet,dict) and packet.get('format')==7 and isinstance(packet.get('tables'),dict):
                packet['tables'].setdefault('lead_funnels',[])
                packet['tables'].setdefault('ai_tool_calls',[])
            if not isinstance(packet,dict) or set(packet)!= {'format','created_at','workspace','tables'} or not isinstance(packet['created_at'],str) or packet.get('format') not in (7,8) or set(packet['tables'])!=set(TABLES) or type(packet['workspace']['id']) is not int or not isinstance(packet['workspace']['name'],str) or not 2<=len(packet['workspace']['name'])<=80:
                raise BackupError('Formato de workspace incompatível.')
            if len(files['workspace.json'])>32*1024*1024:
                raise BackupError('O catálogo do backup é muito grande.')
            return packet,files
        except BackupError:
            raise
        except (KeyError,TypeError,ValueError,zipfile.BadZipFile,RuntimeError,OSError):
            raise BackupError('Não foi possível validar o conteúdo do backup.') from None

    def apply_data(self,db,workspace_id,packet,files,cipher):
        source=packet['workspace']['id'];tables=packet['tables'];maps={}
        columns={table:{r[1] for r in db.execute(f'PRAGMA table_info({table})')} for table in TABLES}
        for table,rows in tables.items():
            if not isinstance(rows,list) or len(rows)>100000:
                raise BackupError('Tabela inválida no backup.')
            for row in rows:
                if not isinstance(row,dict) or set(row)!=columns[table] or ('workspace_id' in row and row['workspace_id']!=source):
                    raise BackupError('O backup contém um vínculo inválido de workspace.')
                json_fields={'leads':{'details':dict},'ai_turns':{'suggestions':list,'usage':dict,'context_snapshot':dict},'product_context':{'data':dict},'lead_funnels':{'filters':dict},'ai_tool_calls':{'arguments':dict,'result':dict,'preview':dict}}.get(table,{})
                for field,expected in json_fields.items():
                    if field in ('context_snapshot','result','preview') and row[field] is None:
                        continue
                    try:
                        decoded=json.loads(row[field])
                    except (ValueError,TypeError):
                        raise BackupError('O backup contém um campo de dados inválido.') from None
                    if not isinstance(decoded,expected):
                        raise BackupError('O backup contém um campo de dados incompatível.')
        for table in reversed(TABLES):
            if table=='campaign_messages':
                db.execute('DELETE FROM campaign_messages WHERE campaign_id IN (SELECT id FROM campaigns WHERE workspace_id=?)',(workspace_id,))
            elif table=='search_leads':
                db.execute('DELETE FROM search_leads WHERE search_id IN (SELECT id FROM searches WHERE workspace_id=?)',(workspace_id,))
            else:
                db.execute(f'DELETE FROM {table} WHERE workspace_id=?',(workspace_id,))
        for table in TABLES:
            maps[table]={}
            for original in tables[table]:
                row=dict(original);old=row.get('id')
                if 'workspace_id' in row:
                    row['workspace_id']=workspace_id
                if 'id' in row:
                    if old in maps[table]:
                        raise BackupError('Identificador repetido no backup.')
                    if table in ('searches','campaigns','ai_threads','ai_tool_calls'):
                        row['id']=uuid4().hex
                    else:
                        del row['id']
                for field,parent in REMAP.get(table,{}).items():
                    if row[field] is not None:
                        if row[field] not in maps[parent]:
                            raise BackupError('Referência ausente no backup.')
                        row[field]=maps[parent][row[field]]
                if table in ('searches','campaigns') and row['status'] in ('running','queued','scheduled'):
                    row.update(status='interrupted',finished_at=now())
                    if table=='campaigns':
                        row.update(error='Restaurado do backup. Revise e retome manualmente os pendentes.',pause_requested=0,cancel_requested=0)
                if table=='campaign_messages' and row['status']=='sending':
                    row.update(status='uncertain',error='Tentativa restaurada sem confirmação. Verifique antes de retomar.')
                if table=='campaign_jobs':
                    row['status']='done'
                if table=='ai_turns' and row['status']=='pending':
                    row.update(status='failed',error='Geração interrompida no backup. Não houve nova chamada à API.')
                if table=='lead_funnels':
                    filters=json.loads(row['filters'])
                    if filters.get('category_id'):filters['category_id']=maps['lead_categories'].get(filters['category_id'],-1)
                    row['filters']=json.dumps(filters)
                if table=='ai_tool_calls':
                    if row['status'] in ('pending','executing','interrupted'):row['status']='cancelled'
                    row['preview']=None
                    row['result']=json.dumps({'restored':True,'message':'Histórico importado. Consulte os recursos restaurados pelas abas. Nenhuma ação foi repetida.'})
                if table=='whatsapp_integrations':
                    row['enabled']=0
                if table=='ai_integrations':
                    try:
                        secret=Fernet(files['ai-key'].strip()).decrypt(row['encrypted_key'].encode())
                        row['encrypted_key']=cipher.encrypt(secret).decode()
                    except (KeyError,ValueError,InvalidToken):
                        raise BackupError('A chave de criptografia das integrações não corresponde ao backup.') from None
                cursor=db.execute(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})",tuple(row.values()))
                if 'id' in original:
                    maps[table][old]=row.get('id',cursor.lastrowid)
        db.execute('UPDATE workspaces SET name=? WHERE id=?',(packet['workspace']['name'],workspace_id))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise BackupError('O backup possui vínculos inconsistentes.')

    def preview(self,workspace_id,user_id,raw,password):
        packet,files=self.unpack(raw,password)
        with self.gate.exclusive(workspace_id):
            self.idle(workspace_id)
            with tempfile.TemporaryDirectory(dir=self.root,prefix='restore-check-') as folder:
                target=sqlite3.connect(str(Path(folder)/'validate.sqlite3'));target.row_factory=sqlite3.Row
                try:
                    with self.repo.connection() as db:
                        db.backup(target)
                    target.execute('PRAGMA foreign_keys=ON')
                    with target:
                        self.apply_data(target,workspace_id,packet,files,Fernet(Fernet.generate_key()))
                except (sqlite3.Error,TypeError,OverflowError,UnicodeError):
                    raise BackupError('O backup não passou na validação do banco de dados. Nada foi alterado.') from None
                finally:
                    target.close()
        token=uuid4().hex+uuid4().hex
        with self.lock:
            self.previews={key:item for key,item in self.previews.items() if item['expires']>time.monotonic() and item['workspace']!=workspace_id}
            if len(self.previews)>=2:
                raise BackupError('Há outras prévias de restauração abertas. Aguarde expirarem e tente novamente.')
            self.previews[token]={'workspace':workspace_id,'user':user_id,'packet':packet,'files':files,'expires':time.monotonic()+600,'password_hash':hashlib.sha256(password.encode()).digest()}
        return {'token':token,'name':packet['workspace']['name'],'created_at':packet['created_at'],
                'counts':{table:len(packet['tables'][table]) for table in ('leads','lead_categories','message_templates','campaigns','reminders','ai_threads')},
                'ai_integrations':len(packet['tables']['ai_integrations']),'whatsapp_session':any(name.startswith('whatsapp/') for name in files)}

    def remove_profile(self,path):
        root=(self.root/'whatsapp').resolve();target=path.resolve()
        if target.parent!=root or not target.name.startswith(('session-workspace-','.restore-','.previous-')):
            raise BackupError('Diretório de sessão inválido.')
        if target.exists():
            shutil.rmtree(target)

    def restore(self,workspace_id,user_id,token,password,confirmation):
        if not isinstance(token,str) or len(token)!=64:
            raise BackupError('A prévia expirou. Selecione o arquivo novamente.')
        with self.lock:
            preview=self.previews.get(token)
        if not preview or preview['workspace']!=workspace_id or preview['user']!=user_id or preview['expires']<time.monotonic():
            raise BackupError('A prévia expirou. Selecione o arquivo novamente.')
        if not isinstance(password,str) or not hmac.compare_digest(preview['password_hash'],hashlib.sha256(password.encode()).digest()):
            raise BackupError('Informe a mesma senha usada na prévia.')
        with self.gate.exclusive(workspace_id),self.integration.operation(workspace_id):
            self.idle(workspace_id)
            with self.repo.connection() as db:
                workspace=db.execute('SELECT name FROM workspaces WHERE id=?',(workspace_id,)).fetchone()
            if confirmation!=workspace['name']:
                raise BackupError('Digite o nome atual do workspace para confirmar a substituição.')
            self.suspend(workspace_id)
            root=self.root/'whatsapp';root.mkdir(exist_ok=True)
            staging=root/('.restore-'+uuid4().hex);previous=root/('.previous-'+uuid4().hex)
            profile=root/f'session-workspace-{int(workspace_id)}';swapped=False;committed=False
            try:
                recovery=self.root/'backups';recovery.mkdir(exist_ok=True)
                (recovery/f'workspace-{int(workspace_id)}-{uuid4().hex}.lfbackup').write_bytes(seal(self.snapshot(workspace_id),password))
                staging.mkdir()
                for name,content in preview['files'].items():
                    if name.startswith('whatsapp/'):
                        destination=staging/PurePosixPath(name).relative_to('whatsapp')
                        if not destination.resolve().is_relative_to(staging.resolve()):
                            raise BackupError('Caminho inválido na sessão.')
                        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(content)
                with self.repo.connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    self.apply_data(db,workspace_id,preview['packet'],preview['files'],self.vault.cipher(create=True))
                    if profile.exists():
                        profile.rename(previous)
                    staging.rename(profile);swapped=True
                committed=True
                with self.lock:
                    self.previews.pop(token,None)
                self.integration.restore_errors.pop(workspace_id,None)
                self.integration.last_states.pop(workspace_id,None)
                return {'ok':True,'message':'Workspace restaurado. Disparos e agendamentos não foram iniciados. Conecte/restaure a sessão do WhatsApp quando desejar.'}
            except (OSError,sqlite3.Error):
                raise BackupError('Não foi possível concluir a restauração. A base anterior foi preservada. Confira o espaço em disco e tente novamente.') from None
            finally:
                if not committed:
                    if swapped:
                        self.remove_profile(profile)
                    if previous.exists():
                        previous.rename(profile)
                    self.resume(workspace_id)
                else:
                    try:
                        self.remove_profile(previous)
                    except (OSError,BackupError):
                        logging.getLogger(__name__).warning('Workspace restaurado; uma cópia anterior da sessão permaneceu no diretório de recuperação.')
                try:
                    self.remove_profile(staging)
                except (OSError,BackupError):
                    logging.getLogger(__name__).warning('Não foi possível remover um diretório temporário de restauração.')
