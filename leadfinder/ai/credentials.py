"""Encrypt local credentials; the encryption key is separate from SQLite backups."""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from leadfinder.ai.catalog import AIError


class CredentialVault:
    def __init__(self, path):
        self.path = Path(path)

    def cipher(self, create=False):
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            try:
                descriptor=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(Fernet.generate_key())
        try:
            return Fernet(self.path.read_bytes().strip())
        except (OSError,ValueError) as error:
            raise AIError('A chave local de criptografia está ausente ou inválida. Restaure .ai-credentials.key do backup antes de usar as integrações.') from error

    def encrypt(self, secret):
        return self.cipher(create=True).encrypt(secret.encode()).decode()

    def decrypt(self, encrypted):
        try:
            return self.cipher().decrypt(encrypted.encode()).decode()
        except (InvalidToken,UnicodeError) as error:
            raise AIError('Não foi possível ler a chave da integração. Restaure a chave local original ou cadastre a integração novamente.') from error
