"""Poll durable SQLite jobs; stopping the process does not lose schedules."""
import atexit
import logging
import threading

from leadfinder.workspace_gate import WorkspaceBusy


class CampaignScheduler:
    def __init__(self,service,gate):
        self.service,self.gate=service,gate
        self.stop=threading.Event()
        self.thread=None

    def tick(self):
        with self.service.store.repo.connection() as db:
            from leadfinder.repository import now
            workspaces=[row[0] for row in db.execute("SELECT DISTINCT workspace_id FROM campaign_jobs WHERE status='queued' AND available_at<=?",(now(),))]
        for workspace_id in workspaces:
            try:
                self.gate.enter(workspace_id)
            except WorkspaceBusy:
                continue
            try:
                self.service.process_due(workspace_id)
            finally:
                self.gate.leave(workspace_id)

    def start(self):
        if self.thread:
            return
        def run():
            while not self.stop.wait(1):
                try:
                    self.tick()
                except Exception:
                    logging.getLogger(__name__).exception('Não foi possível processar a fila de campanhas.')
        self.thread=threading.Thread(target=run,daemon=True,name='leadfinder-scheduler')
        self.thread.start();atexit.register(self.stop.set)
