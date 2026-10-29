(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const token = $('meta[name="leadfinder-token"]').content;
  let initialized = false, busy = false, timer;
  const labels = {restoring:'Restaurando sessão…',not_configured:'Não configurado',disconnected:'Desconectado',starting:'Abrindo WhatsApp…',qr:'Escaneie o QR code',authenticating:'Autenticando…',ready:'Conectado',mismatch:'Confira o número',error:'Falha na conexão'};
  function toast(message,error=false) {
    const node = document.createElement('div'); node.className = 'toast'+(error?' error':''); node.textContent=message;
    $('#toast-region').append(node); setTimeout(()=>node.remove(),7000);
  }
  async function api(path, data) {
    const response = await fetch(path,{method:data?'POST':'GET',headers:{'Content-Type':'application/json','X-LeadFinder-Token':token},...(data?{body:JSON.stringify(data)}:{})});
    const result = await response.json();
    if (result.redirect) window.location.assign(result.redirect);
    if (!response.ok) throw new Error(result.error || 'Não foi possível concluir a operação.');
    return result;
  }
  function render(state) {
    if (!initialized) {
      if (state.configured) { $('#wa-name').value=state.name; $('#wa-phone').value='+'+state.configured_phone; }
      initialized=true;
    }
    $('#wa-events').replaceChildren(...(state.events || []).map(event=>{const li=document.createElement('li');li.className=event.level;const time=document.createElement('time');time.textContent=new Date(event.created_at).toLocaleString('pt-BR');li.append(time,document.createTextNode(event.message));return li;}));
    $('#wa-status').textContent=labels[state.status] || state.status;
    $('#wa-status').className='status-badge'+(['error','mismatch'].includes(state.status)?' failed':'');
    const qr=state.status==='qr' && /^data:image\/png;base64,/.test(state.qr || '');
    $('#wa-qr').hidden=!qr;
    if (qr) $('#wa-qr').src=state.qr; else $('#wa-qr').removeAttribute('src');
    $('#wa-placeholder').hidden=Boolean(qr) || state.status==='ready';
    $('#wa-detail').textContent=state.error || (state.status==='ready'?'Conectado ao número +'+state.phone+'. Sua integração está pronta para enviar.':state.status==='qr'?'WhatsApp → Aparelhos conectados → Conectar aparelho. O QR code se renova automaticamente.':labels[state.status]);
    $('#wa-connect').disabled=busy || !state.configured || ['restoring','starting','qr','authenticating','ready','mismatch'].includes(state.status);
    $('#wa-connect').textContent=state.status==='disconnected'?'Conectar / restaurar sessão':'Conectar WhatsApp';
    $('#wa-disconnect').disabled=busy || !state.configured;
  }
  async function refresh() {
    clearTimeout(timer);
    try { if (!busy) render(await api('/api/integrations/whatsapp')); }
    catch (error) { $('#wa-detail').textContent=error.message; }
    finally { timer=setTimeout(refresh,2500); }
  }
  async function action(path,data,success) {
    if (busy) return;
    busy=true; $('#wa-connect').disabled=true; $('#wa-disconnect').disabled=true;
    try { const state=await api(path,data); render(state); toast(success); }
    catch(error) { toast(error.message,true); }
    finally { busy=false; refresh(); }
  }
  $('#wa-config').addEventListener('submit',event=>{ event.preventDefault(); action('/api/integrations/whatsapp',{name:$('#wa-name').value.trim(),phone:$('#wa-phone').value.trim()},'Integração salva.'); });
  $('#wa-connect').addEventListener('click',()=>action('/api/integrations/whatsapp/connect',{},'Conexão iniciada. Aguarde o QR code ou a restauração da sessão.'));
  $('#wa-disconnect').addEventListener('click',()=>action('/api/integrations/whatsapp/disconnect',{},'Integração desconectada neste aplicativo.'));
  refresh();
})();
