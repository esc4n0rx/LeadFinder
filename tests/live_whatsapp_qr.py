"""Opt-in native handshake check. No QR scan, account link, or message sending."""

import tempfile
import time
from pathlib import Path

from leadfinder.integrations.whatsapp_runtime import WhatsAppRuntime


def main():
    with tempfile.TemporaryDirectory() as directory:
        runtime=WhatsAppRuntime(Path(directory)/'whatsapp')
        try:
            runtime.connect(1,'5521999991111')
            deadline=time.monotonic()+100
            previous=None
            while time.monotonic()<deadline:
                state=runtime.status(1)
                if state['status']!=previous:
                    print('WhatsApp bridge status:',state['status'],flush=True)
                    previous=state['status']
                if state['status']=='qr':
                    assert state['qr'].startswith('data:image/png;base64,')
                    print('PASS: native WhatsApp Web QR generated; not displayed, scanned, or persisted; no messages sent.',flush=True)
                    return
                if state['status'] in ('error','mismatch'):
                    raise RuntimeError(state['error'])
                time.sleep(1)
            raise RuntimeError('QR generation timed out')
        finally:
            runtime.close()


if __name__=='__main__':
    main()
