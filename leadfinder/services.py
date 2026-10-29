"""Background search orchestration, independent of Flask and browser details."""

import logging
import re
import threading
from uuid import uuid4

from leadfinder.repository import now
from leadfinder.geography import distance_km, valid_coordinates

logger = logging.getLogger(__name__)


class SearchBusy(Exception):
    pass


class CollectionStopped(Exception):
    pass


class ResultLimitReached(Exception):
    pass


class SearchService:
    def __init__(self, repository, collector_factory):
        self.repository = repository
        self.collector_factory = collector_factory
        self._lock = threading.Lock()
        self._active = set()

    def start(self, term, location, limit, *, workspace_id=1, area=None, require_phone=False, category_id=None):
        with self._lock:
            if workspace_id in self._active:
                raise SearchBusy('Já existe uma coleta neste workspace. Aguarde ou interrompa a busca atual.')
            if len(self._active) >= 2:
                raise SearchBusy('O servidor está ocupado. Tente novamente após uma coleta terminar.')
            self._active.add(workspace_id)
        search_id = uuid4().hex
        try:
            self.repository.create_search(search_id, term, location, limit, workspace_id=workspace_id, area=area, require_phone=require_phone, category_id=category_id)
            thread = threading.Thread(target=self._run, args=(search_id, term, location, limit, workspace_id, area, require_phone), daemon=True)
            thread.start()
        except Exception:
            with self._lock:
                self._active.discard(workspace_id)
            raise
        return self.repository.get_search(search_id)

    def _run(self, search_id, term, location, limit, workspace_id, area, require_phone):
        saved = processed = failed = 0
        skipped = {'skipped_phone': 0, 'skipped_distance': 0, 'skipped_coordinates': 0}

        def check_cancel():
            if self.repository.get_search(search_id)["cancel_requested"]:
                raise CollectionStopped()

        def progress(**values):
            check_cancel()
            self.repository.update_search(search_id, **values)

        def on_lead(lead):
            nonlocal saved, processed
            check_cancel()
            processed += 1
            reason = None
            if require_phone and len(re.sub(r'\D', '', lead.phone or '')) < 8:
                reason = 'skipped_phone'
            elif area:
                if not valid_coordinates(lead.latitude, lead.longitude):
                    reason = 'skipped_coordinates'
                elif distance_km(area.latitude, area.longitude, lead.latitude, lead.longitude) > area.radius_km:
                    reason = 'skipped_distance'
            if reason:
                skipped[reason] += 1
                reasons={'skipped_phone':'telefone não encontrado','skipped_coordinates':'coordenadas não disponíveis','skipped_distance':f'fora do raio de {area.radius_km:g} km' if area else 'fora do raio'}
                progress(processed=processed, **skipped, message=f'Ignorado: {lead.name} — {reasons[reason]}.')
                return
            self.repository.save_lead(search_id, lead)
            saved += 1
            progress(saved=saved, processed=processed, message=f"Salvo: {lead.name}")
            if saved >= limit:
                raise ResultLimitReached()

        def on_error(message):
            nonlocal processed, failed
            processed += 1
            failed += 1
            progress(processed=processed, failed=failed, message=message)

        try:
            progress(status="running", message="Abrindo o Google Maps…")
            candidates = min(300, max(100, limit * 3)) if (area or require_phone) else limit
            arguments = (term, location, candidates, on_lead, on_error, progress, check_cancel)
            try:
                collector = self.collector_factory()
                if area:
                    collector.collect(*arguments, area=area)
                else:
                    collector.collect(*arguments)
            except ResultLimitReached:
                pass
            check_cancel()
            message = f"Coleta concluída. {saved} estabelecimento(s) catalogado(s)."
            if failed:
                message += f" {failed} página(s) não puderam ser lidas."
            ignored = sum(skipped.values())
            if ignored:
                details=[]
                if skipped['skipped_phone']:details.append(f"{skipped['skipped_phone']} com telefone não encontrado")
                if skipped['skipped_distance']:details.append(f"{skipped['skipped_distance']} fora do raio")
                if skipped['skipped_coordinates']:details.append(f"{skipped['skipped_coordinates']} sem coordenadas")
                message += f' {ignored} local(is) ignorado(s): '+', '.join(details)+'.'
                if not saved and skipped['skipped_distance']:
                    message += ' Confira o CEP e o ponto de referência antes de ampliar o raio.'
            self.repository.update_search(search_id, status="partial" if failed else "completed", message=message, finished_at=now())
        except CollectionStopped:
            self.repository.update_search(search_id, status="cancelled", message="Coleta interrompida. Os leads salvos foram preservados.", finished_at=now())
        except Exception as error:
            logger.exception("Search %s failed", search_id)
            from leadfinder.collectors.google_maps import CollectorError

            message = str(error) if isinstance(error, CollectorError) else "Não foi possível concluir a coleta. Consulte o terminal para detalhes."
            self.repository.update_search(search_id, status="failed", message=message, finished_at=now())
        finally:
            with self._lock:
                self._active.discard(workspace_id)
