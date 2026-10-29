"""Accounts, revocable sessions, and workspace ownership persistence."""

import hashlib
import secrets
import sqlite3
import time

from werkzeug.security import generate_password_hash

from leadfinder.repository import now


class AccountError(ValueError):
    pass


class AccountStore:
    def __init__(self, repository):
        self.repository = repository

    def create_user(self, name, username, email, password):
        password_hash = generate_password_hash(password)
        try:
            with self.repository.connection() as db:
                row = db.execute('INSERT INTO users(name,username,username_key,email,email_key,password_hash,created_at) VALUES(?,?,?,?,?,?,?) RETURNING id',
                                 (name, username, username.casefold(), email, email.casefold(), password_hash, now())).fetchone()
                return row['id']
        except sqlite3.IntegrityError as error:
            raise AccountError('Este nome de usuário ou email já está cadastrado.') from error

    def find_username(self, username):
        with self.repository.connection() as db:
            row = db.execute('SELECT * FROM users WHERE username_key=?', (username.casefold(),)).fetchone()
            return dict(row) if row else None

    def get_user(self, user_id):
        with self.repository.connection() as db:
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            return dict(row) if row else None

    def workspace(self, user_id):
        with self.repository.connection() as db:
            row = db.execute('SELECT * FROM workspaces WHERE owner_id=?', (user_id,)).fetchone()
            return dict(row) if row else None

    def legacy_count(self, user_id):
        with self.repository.connection() as db:
            eligible = db.execute('SELECT 1 FROM workspaces WHERE id=1 AND owner_id IS NULL AND ?=(SELECT MIN(id) FROM users)', (user_id,)).fetchone()
            return db.execute('SELECT COUNT(*) FROM leads WHERE workspace_id=1').fetchone()[0] if eligible else 0

    def setup_workspace(self, user_id, name):
        with self.repository.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT id FROM workspaces WHERE owner_id=?', (user_id,)).fetchone()
            if existing:
                return existing['id']
            legacy = db.execute('SELECT id FROM workspaces WHERE id=1 AND owner_id IS NULL AND ?=(SELECT MIN(id) FROM users)', (user_id,)).fetchone()
            if legacy:
                db.execute('UPDATE workspaces SET owner_id=?,name=? WHERE id=1', (user_id, name))
                return 1
            return db.execute('INSERT INTO workspaces(owner_id,name,created_at) VALUES(?,?,?) RETURNING id', (user_id, name, now())).fetchone()['id']

    def new_session(self, user_id):
        token = secrets.token_urlsafe(32)
        with self.repository.connection() as db:
            db.execute('DELETE FROM auth_sessions WHERE expires_at<?', (time.time(),))
            db.execute('INSERT INTO auth_sessions VALUES(?,?,?)', (self.token_hash(token), user_id, time.time()+7*86400))
        return token

    def session_user(self, token):
        if not token or len(token) > 128:
            return None
        with self.repository.connection() as db:
            row = db.execute('SELECT u.* FROM users u JOIN auth_sessions s ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?', (self.token_hash(token), time.time())).fetchone()
            return dict(row) if row else None

    def revoke_session(self, token):
        with self.repository.connection() as db:
            db.execute('DELETE FROM auth_sessions WHERE token_hash=?', (self.token_hash(token or ''),))

    def update_profile(self, user_id, name, username, email, password=None):
        password_hash = generate_password_hash(password) if password else None
        try:
            with self.repository.connection() as db:
                db.execute('UPDATE users SET name=?,username=?,username_key=?,email=?,email_key=?,password_hash=COALESCE(?,password_hash) WHERE id=?',
                           (name, username, username.casefold(), email, email.casefold(), password_hash, user_id))
                # Identity/password changes revoke every previous session.
                db.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
        except sqlite3.IntegrityError as error:
            raise AccountError('Este nome de usuário ou email já está cadastrado.') from error

    def login_blocked(self, key):
        with self.repository.connection() as db:
            row = db.execute('SELECT * FROM login_attempts WHERE key=? AND expires_at>?', (key, time.time())).fetchone()
            return row is not None and row['failures'] >= 8

    def record_login(self, key, success):
        with self.repository.connection() as db:
            db.execute('DELETE FROM login_attempts WHERE expires_at<?', (time.time(),))
            if success:
                db.execute('DELETE FROM login_attempts WHERE key=?', (key,))
            else:
                db.execute('INSERT INTO login_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET failures=failures+1', (key, time.time()+900))

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()
