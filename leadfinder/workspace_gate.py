"""Prevent restores from racing workspace mutations or starting scheduled work."""
import threading
from contextlib import contextmanager


class WorkspaceBusy(ValueError):
    pass


class WorkspaceGate:
    def __init__(self):
        self.lock=threading.RLock()
        self.active={}
        self.frozen=set()

    def enter(self,workspace_id):
        with self.lock:
            if workspace_id in self.frozen:
                raise WorkspaceBusy('O workspace está preparando ou restaurando um backup. Aguarde terminar.')
            self.active[workspace_id]=self.active.get(workspace_id,0)+1

    def leave(self,workspace_id):
        with self.lock:
            self.active[workspace_id]=max(0,self.active.get(workspace_id,0)-1)

    @contextmanager
    def exclusive(self,workspace_id):
        with self.lock:
            if workspace_id in self.frozen or self.active.get(workspace_id,0):
                raise WorkspaceBusy('Há uma operação em andamento neste workspace. Aguarde antes de usar o backup.')
            self.frozen.add(workspace_id)
        try:
            yield
        finally:
            with self.lock:
                self.frozen.discard(workspace_id)
