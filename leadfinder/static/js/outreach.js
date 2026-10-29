(() => {
  'use strict';
  const {api,toast,escape:e} = window.LeadFinder;
  const $ = selector => document.querySelector(selector);
  const state = {templates:[], selectedTemplates:[], selectedTargets:new Set(), targets:[], page:1,total:0,campaign:null,ready:false,busy:false,listVersion:0,connection:null,pollError:false,senderName:document.body.dataset.userName};
  const labels = {draft:'Rascunho',scheduled:'Agendado',running:'Em andamento',completed:'Concluído',partial:'Parcial',cancelled:'Cancelado',paused:'Pausado',interrupted:'Interrompido',pending:'Pendente',sending:'Enviando',sent:'Enviado ao WhatsApp',simulated:'Simulado',failed:'Falhou',uncertain:'Sem confirmação'};
  const variables = ['nome','empresa','telefone','endereco','categoria','site','meu_nome','workspace'];
  let timer, searchTimer;
  function blankEditor() {
    $('#message-id').value=''; $('#message-name').value=''; $('#message-body').value='';
    $('#message-name').focus(); preview();
  }
  function preview() {
    const values={nome:'Café Horizonte (fictício)',empresa:'Café Horizonte (fictício)',telefone:'',endereco:'Endereço de teste',categoria:'Cliente fictício',site:'https://example.org',meu_nome:state.senderName,workspace:document.body.dataset.workspace};
    const body=$('#message-body').value;
    $('#message-length').textContent=body.length.toLocaleString('pt-BR')+' / 4.000';
    $('#message-preview-text').textContent=body ? body.replace(/{{\s*([a-z_]+)\s*}}/g,(match,key)=>Object.hasOwn(values,key)?values[key]:match) : 'Sua mensagem personalizada aparece aqui.';
  }
  function renderTemplates() {
    $('#template-list').innerHTML=state.templates.length ? state.templates.map(t=>`<article class="template-card"><button class="template-open" data-edit="${t.id}"><strong>${e(t.name)}</strong><span>${e(t.body.slice(0,110))}</span></button><button class="template-archive text-button" data-archive="${t.id}" aria-label="Arquivar ${e(t.name)}">Arquivar</button></article>`).join('') : '<div class="outreach-empty">Sua primeira mensagem começa no editor ao lado.</div>';
    state.selectedTemplates=state.selectedTemplates.filter(id=>state.templates.some(t=>t.id===id));
    $('#campaign-template-list').innerHTML=state.templates.length ? state.templates.map(t=>{const order=state.selectedTemplates.indexOf(t.id);return `<label class="choice-row"><input type="checkbox" data-template="${t.id}" ${order>=0?'checked':''}><span><strong>${e(t.name)}</strong><small>${e(t.body.slice(0,85))}</small></span>${order>=0?`<b class="sequence-number">${order+1}</b>`:''}</label>`;}).join('') : '<p class="field-help">Crie uma mensagem em Mensagens antes de preparar um disparo.</p>';
  }
  async function loadTemplates() {
    const result=await api('/api/messages'); state.templates=result.items; renderTemplates();
  }
  $('#message-variables').innerHTML=variables.map(v=>`<button type="button" class="variable-chip" data-variable="${v}">{{${v}}}</button>`).join('');
  $('#message-variables').addEventListener('click',event=>{
    const button=event.target.closest('[data-variable]'); if(!button)return;
    const field=$('#message-body'); field.setRangeText('{{'+button.dataset.variable+'}}',field.selectionStart,field.selectionEnd,'end'); field.focus(); preview();
  });
  document.addEventListener('leadfinder:ai-draft',event=>{const draft=event.detail;$('#message-id').value='';$('#message-name').value=draft.name;$('#message-body').value=draft.body;preview();$('#message-name').focus();toast('Sugestão no editor. Revise e salve a mensagem.');});
  $('#message-new').addEventListener('click',blankEditor);
  $('#message-body').addEventListener('input',preview);
  $('#message-form').addEventListener('submit',async event=>{
    event.preventDefault(); if(state.busy)return; state.busy=true;
    try { const id=$('#message-id').value; const result=await api('/api/messages'+(id?'/'+id:''),{method:'POST',body:JSON.stringify({name:$('#message-name').value.trim(),body:$('#message-body').value})}); $('#message-id').value=result.id; await loadTemplates(); toast('Mensagem salva.'); }
    catch(error){toast(error.message,true);} finally{state.busy=false;$('#prepare-campaign').disabled=false;if(state.campaign)renderCampaign(state.campaign);}
  });
  $('#template-list').addEventListener('click',async event=>{
    const edit=event.target.closest('[data-edit]'), archive=event.target.closest('[data-archive]');
    if(edit){ const template=state.templates.find(t=>t.id===Number(edit.dataset.edit)); $('#message-id').value=template.id; $('#message-name').value=template.name; $('#message-body').value=template.body; preview(); }
    if(archive){try{await api('/api/messages/'+archive.dataset.archive+'/archive',{method:'POST',body:'{}'}); if($('#message-id').value===archive.dataset.archive)blankEditor(); await loadTemplates(); toast('Mensagem arquivada. Disparos já preparados mantêm a cópia original.');}catch(error){toast(error.message,true);}}
  });
  $('#campaign-template-list').addEventListener('change',event=>{
    const id=Number(event.target.dataset.template); if(!id)return;
    if(event.target.checked){ if(state.selectedTemplates.length>=5){event.target.checked=false;toast('Selecione até 5 mensagens.',true);return;} state.selectedTemplates.push(id); }
    else state.selectedTemplates=state.selectedTemplates.filter(value=>value!==id);
    renderTemplates();
  });
  function renderTargets() {
    $('#target-count').textContent=state.selectedTargets.size+' selecionados';
    $('#target-list').innerHTML=state.targets.length?state.targets.map(t=>`<label class="choice-row"><input type="checkbox" data-target="${t.id}" ${state.selectedTargets.has(t.id)?'checked':''}><span><strong>${e(t.name)}</strong><small>${e(t.phone)}</small></span></label>`).join(''):'<p class="field-help">Nenhum estabelecimento com telefone nesta seleção.</p>';
    $('#targets-page').textContent=`${state.page} / ${Math.max(1,Math.ceil(state.total/25))}`;
    $('#targets-prev').disabled=state.page<=1; $('#targets-next').disabled=state.page*25>=state.total;
  }
  async function loadTargets() {
    const version=++state.listVersion;
    const params=new URLSearchParams({page:state.page,q:$('#target-query').value.trim(),search_id:$('#target-search').value,category_id:$('#target-category').value,contact_status:$('#target-contact-status').value,stage:$('#target-stage').value});
    const result=await api('/api/outreach/targets?'+params);
    if(version!==state.listVersion)return;
    state.targets=result.items;state.total=result.total;renderTargets();
  }
  function modeChanged() {
    const mode=$('#campaign-mode').value,real=mode==='real',test=mode==='test';
    $('#real-targets').hidden=!real; $('#fictional-target').hidden=!['test','simulated'].includes(mode);
    $('#fictional-phone').required=test;
    $('#fictional-phone-optional').hidden=test;
    $('label[for=fictional-phone]').firstChild.textContent=test?'Telefone do destinatário de teste ':'Telefone do cliente fictício ';
    $('label[for=fictional-name]').textContent=test?'Nome do destinatário de teste':'Nome do cliente fictício';
    $('#campaign-mode-notice').textContent=test?'Envio real: o número informado receberá as mensagens pelo WhatsApp conectado. Revise o destinatário antes de iniciar.':'Simulação local: o telefone só personaliza os dados. Nenhuma mensagem será enviada pelo WhatsApp.';
    if(real)loadTargets().catch(error=>toast(error.message,true));
  }
  $('#campaign-mode').addEventListener('change',modeChanged);
  modeChanged();
  function outcomeLabel(campaign) {
    if(campaign.status==='completed')return campaign.simulated?'Simulação concluída · sem envio':'Envios aceitos pelo WhatsApp';
    return labels[campaign.status]||campaign.status;
  }
  function eventLog(events) {
    return `<section class="operation-log"><h3>Histórico de execução</h3><ol>${(events||[]).map(event=>`<li class="${e(event.level)}"><time>${e(new Date(event.created_at).toLocaleString('pt-BR'))}</time>${e(event.message)}</li>`).join('')||'<li>Sem eventos registrados nesta execução anterior. Consulte os resultados por mensagem.</li>'}</ol></section>`;
  }
  $('#target-list').addEventListener('change',event=>{
    const id=Number(event.target.dataset.target);if(!id)return;
    if(event.target.checked){if(state.selectedTargets.size>=100){event.target.checked=false;toast('Selecione até 100 destinatários.',true);return;}state.selectedTargets.add(id);}else state.selectedTargets.delete(id);
    $('#target-count').textContent=state.selectedTargets.size+' selecionados';
  });
  $('#select-page').addEventListener('click',()=>{state.targets.forEach(t=>{if(state.selectedTargets.size<100)state.selectedTargets.add(t.id);});renderTargets();});
  $('#clear-targets').addEventListener('click',()=>{state.selectedTargets.clear();renderTargets();});
  $('#targets-prev').addEventListener('click',()=>{state.page--;loadTargets().catch(error=>toast(error.message,true));});
  $('#targets-next').addEventListener('click',()=>{state.page++;loadTargets().catch(error=>toast(error.message,true));});
  $('#target-search').addEventListener('change',()=>{state.page=1;loadTargets().catch(error=>toast(error.message,true));});
  $('#target-query').addEventListener('input',()=>{clearTimeout(searchTimer);state.page=1;searchTimer=setTimeout(()=>loadTargets().catch(error=>toast(error.message,true)),250);});
  function renderCampaign(campaign) {
    if(document.activeElement?.id==='campaign-schedule-at' && state.campaign?.id===campaign.id && campaign.status==='draft'){
      state.campaign=campaign;
      const schedule=$('[data-campaign-action="schedule"]');if(schedule)schedule.disabled=state.busy;
      const execute=$('#execute-campaign');if(execute)execute.disabled=state.busy||(!campaign.simulated&&!state.ready);
      return;
    }
    const scheduleValue=$('#campaign-schedule-at')?.value || '';
    state.campaign=campaign;
    $('#campaign-mode-badge').textContent=campaign.simulated?'Simulação local · sem envio':campaign.test_target?'WhatsApp · número de teste':'Envio real';
    const counts=campaign.counts;
    const outcome=`${counts.sent||0} enviados · ${counts.simulated||0} simulados · ${counts.failed||0} falhas · ${counts.uncertain||0} sem confirmação`;
    $('#campaign-detail').innerHTML=`<div class="review-summary"><strong>${e(campaign.name)}</strong><span class="status-badge">${e(outcomeLabel(campaign))}</span><p>${campaign.target_count} destinatário(s) · ${campaign.message_count} mensagem(ns)</p><small>${outcome}</small></div>${campaign.error?`<p class="campaign-alert">${e(campaign.error)}</p>`:''}${campaign.simulated?'<p class="simulation-notice">Este disparo usa somente o cliente fictício. Nenhuma mensagem será enviada pelo WhatsApp.</p>':`<p class="field-help">Envio real: a confirmação do servidor não comprova entrega ou leitura pelo destinatário.<br>Remetente: +${e(campaign.sender_phone)} · ${campaign.interval_seconds}s entre mensagens.</p>`}${campaign.status==='draft'?`<button id="execute-campaign" class="primary-button" ${state.busy||(!campaign.simulated&&!state.ready)?'disabled':''}>${campaign.simulated?'Executar simulação':'Iniciar disparo real'}</button>${!campaign.simulated&&!state.ready?'<p class="campaign-alert">Conecte a integração de WhatsApp para liberar o envio.</p>':''}`:''}${['draft','running'].includes(campaign.status)?`<button id="cancel-campaign" class="text-button" ${state.busy?'disabled':''}>Cancelar disparo</button>`:''}<div class="delivery-list">${campaign.messages.map(m=>`<article class="delivery-item"><div><strong>${e(m.target_name)}</strong><span class="status-badge">${e(m.status==='sent'?'Aceita pelo WhatsApp':labels[m.status]||m.status)}</span></div><small>${m.message_index+1}. ${e(m.template_name)}${m.phone?' · +'+e(m.phone):' · Cliente fictício'}</small><p class="chat-bubble">${e(m.body)}</p>${m.sent_at?`<small>${e(new Date(m.sent_at).toLocaleString('pt-BR'))}</small>`:''}${m.provider_id?`<small>ID WhatsApp: ${e(m.provider_id)}</small>`:''}${m.error?`<p class="campaign-alert">${e(m.error)}</p>`:''}</article>`).join('')}</div>${eventLog(campaign.events)}`;
    let controls='';
    if(campaign.status==='draft')controls+=`<div class="schedule-controls"><div><label for="campaign-schedule-at">Agendar data e hora</label><input id="campaign-schedule-at" type="datetime-local" aria-label="Agendar data e hora" ${state.busy?'disabled':''}></div><button type="button" class="secondary-button" data-campaign-action="schedule" ${state.busy?'disabled':''}>Confirmar agendamento</button><small>Executa somente com o LeadFinder aberto. Uma agenda vencida aguarda a conexão do WhatsApp.</small></div>`;
    if(campaign.status==='scheduled')controls+=`<p class="field-help">Agendado para ${e(new Date(campaign.scheduled_at).toLocaleString('pt-BR'))}. O LeadFinder precisa estar aberto.</p>`;
    if(campaign.status==='running')controls+=`<button type="button" class="secondary-button" data-campaign-action="pause" ${state.busy?'disabled':''}>Pausar disparo</button>`;
    if(['paused','interrupted','partial'].includes(campaign.status)&&counts.pending)controls+=`<button type="button" class="primary-button" data-campaign-action="resume" ${state.busy||counts.uncertain||(!campaign.simulated&&!state.ready)?'disabled':''}>Retomar ${counts.pending} pendente(s)</button>`;
    if(['scheduled','paused','interrupted','partial'].includes(campaign.status))controls+=`<button type="button" class="text-button" data-campaign-action="cancel" ${state.busy?'disabled':''}>Cancelar restantes</button>`;
    $('#campaign-detail .delivery-list').insertAdjacentHTML('beforebegin',`<div class="recovery-actions">${controls}</div>`);
    if($('#campaign-schedule-at'))$('#campaign-schedule-at').value=scheduleValue;
    $('#campaign-detail').querySelectorAll('.delivery-item').forEach((article,index)=>{const message=campaign.messages[index];if(message.status==='uncertain')article.insertAdjacentHTML('beforeend',`<div class="recovery-actions"><button type="button" class="secondary-button" data-verify-message="${message.id}" ${state.busy||!message.provider_id||!state.ready?'disabled':''}>Consultar confirmação</button><button type="button" class="text-button" data-resolve-message="${message.id}" data-resolution="sent" ${state.busy?'disabled':''}>Conferi: foi enviada</button><button type="button" class="text-button" data-resolve-message="${message.id}" data-resolution="failed" ${state.busy?'disabled':''}>Conferi: não foi enviada</button><small>Registre o resultado manual somente após verificar no celular. Nenhum destes botões reenvia mensagens.</small></div>`);});
  }
  async function refreshCampaigns() {
    const [connection,list]=await Promise.all([api('/api/integrations/whatsapp'),api('/api/campaigns')]);
    state.ready=connection.status==='ready';state.connection=connection;
    const descriptions={not_configured:'WhatsApp não configurado.',disconnected:'WhatsApp desconectado.',restoring:'Restaurando sessão salva…',starting:'Abrindo WhatsApp Web…',qr:'Leia o QR code em Perfil → Integrações.',authenticating:'Finalizando autenticação…',error:'Falha na integração.',mismatch:'Confira o número vinculado.'};
    $('#automation-connection').textContent=state.ready?'WhatsApp conectado. Envios reais disponíveis.':(connection.error || descriptions[connection.status] || 'Verifique a conexão.')+' Envios reais bloqueados.';
    $('#automation-connection').classList.toggle('connection-ready',state.ready);
    $('#automation-integration').textContent=state.ready?'WhatsApp conectado ↗':'Configurar WhatsApp ↗';
    $('#campaign-list').innerHTML=list.items.length?list.items.map(c=>`<article class="campaign-row"><div><strong>${e(c.name)}</strong><small>${c.simulated?'Simulação':'WhatsApp'} · ${c.target_count} destinatário(s) · ${c.counts.sent||c.counts.simulated||0}/${c.message_count} processadas</small></div><span class="status-badge">${e(outcomeLabel(c))}</span><button class="text-button" data-campaign="${c.id}">Ver detalhes</button></article>`).join(''):'<div class="outreach-empty">Seu primeiro disparo aparecerá aqui. Comece pelo cliente fictício.</div>';
    const selectedId=state.campaign?.id;
    if(selectedId){const campaign=await api('/api/campaigns/'+selectedId);if(state.campaign?.id===selectedId)renderCampaign(campaign);}
  }
  $('#campaign-form').addEventListener('submit',async event=>{
    event.preventDefault(); if(state.busy)return;state.busy=true;$('#prepare-campaign').disabled=true;
    try{
      const result=await api('/api/campaigns',{method:'POST',body:JSON.stringify({name:$('#campaign-name').value.trim(),simulated:$('#campaign-mode').value==='simulated',test_target:$('#campaign-mode').value==='test',fictional_name:$('#fictional-name').value.trim(),fictional_phone:$('#fictional-phone').value.trim(),interval_seconds:Number($('#campaign-interval').value),template_ids:state.selectedTemplates,target_ids:[...state.selectedTargets]})});
      renderCampaign(result.campaign);await refreshCampaigns();toast('Disparo preparado. Revise os textos antes de executar.');
      if(result.skipped.length)toast(result.skipped.map(s=>s.name+': '+s.reason).join(' · '),true);
    }catch(error){toast(error.message,true);}finally{state.busy=false;$('#prepare-campaign').disabled=false;if(state.campaign)renderCampaign(state.campaign);}
  });
  $('#campaign-detail').addEventListener('click',async event=>{
    const start=event.target.closest('#execute-campaign'),cancel=event.target.closest('#cancel-campaign');
    if(!state.campaign || (!start&&!cancel) || state.busy)return;
    state.busy=true; $('#prepare-campaign').disabled=true; if(start)start.disabled=true;if(cancel)cancel.disabled=true;
    try{const result=await api('/api/campaigns/'+state.campaign.id+(start?'/start':'/cancel'),{method:'POST',body:'{}'});renderCampaign(result);await refreshCampaigns();toast(start?'Execução iniciada. Acompanhe os resultados.':'Cancelamento solicitado. Uma mensagem já em envio pode terminar.');}
    catch(error){toast(error.message,true);await refreshCampaigns().catch(()=>{});}finally{state.busy=false;$('#prepare-campaign').disabled=false;if(state.campaign)renderCampaign(state.campaign);}
  });
  $('#campaign-detail').addEventListener('click',async event=>{
    const action=event.target.closest('[data-campaign-action]'),verify=event.target.closest('[data-verify-message]'),resolve=event.target.closest('[data-resolve-message]');
    if((!action&&!verify&&!resolve)||!state.campaign||state.busy)return;
    const button=action||verify||resolve;state.busy=true;button.disabled=true;
    try{
      let suffix,payload={};
      if(action){suffix='/'+action.dataset.campaignAction;if(action.dataset.campaignAction==='schedule'){const value=$('#campaign-schedule-at').value;if(!value)throw new Error('Escolha a data e hora do disparo.');payload={due_at:new Date(value).toISOString()};}}
      else{suffix='/messages/'+(verify?.dataset.verifyMessage || resolve.dataset.resolveMessage)+'/verify';if(resolve)payload.resolution=resolve.dataset.resolution;}
      renderCampaign(await api('/api/campaigns/'+state.campaign.id+suffix,{method:'POST',body:JSON.stringify(payload)}));await refreshCampaigns();toast(verify||resolve?'Resultado da tentativa atualizado.':'Disparo atualizado.');
    }catch(error){toast(error.message,true);}finally{state.busy=false;if(state.campaign)renderCampaign(state.campaign);}
  });
  for(const id of ['target-category','target-contact-status','target-stage'])$('#'+id).addEventListener('change',()=>{state.page=1;loadTargets().catch(error=>toast(error.message,true));});
  $('#select-filtered-targets').addEventListener('click',async event=>{event.target.disabled=true;try{const result=await api('/api/leads/selection',{method:'POST',body:JSON.stringify({filters:{q:$('#target-query').value.trim(),search_id:$('#target-search').value,category_id:$('#target-category').value?Number($('#target-category').value):null,contact_status:$('#target-contact-status').value,stage:$('#target-stage').value,only_phone:true}})});if(result.ids.length>100)throw new Error('Refine os filtros para até 100 destinatários.');state.selectedTargets=new Set(result.ids);renderTargets();}catch(error){toast(error.message,true);}finally{event.target.disabled=false;}});
  let campaignSelection=0;
  async function openCampaign(id){
    if(state.busy)return;
    const sequence=++campaignSelection;state.campaign=null;
    $('#campaign-detail').textContent='Carregando disparo…';
    const campaign=await api('/api/campaigns/'+id);
    if(sequence!==campaignSelection)return;
    renderCampaign(campaign);$('#campaign-detail').scrollIntoView({block:'nearest'});
  }
  $('#campaign-list').addEventListener('click',event=>{
    const button=event.target.closest('[data-campaign]');if(button)openCampaign(button.dataset.campaign).catch(error=>toast(error.message,true));
  });
  async function activate(view) {
    if(!['messages','automation'].includes(view))return;
    try{
      await loadTemplates();
      const connection=await api('/api/integrations/whatsapp');state.senderName=connection.name || document.body.dataset.userName;preview();
      if(view==='automation'){
        const categories=await api('/api/categories'),category=$('#target-category').value,stage=$('#target-stage').value;
        $('#target-category').innerHTML='<option value="">Todas as categorias</option><option value="0">Sem categoria</option>'+categories.items.map(c=>`<option value="${c.id}">${e(c.name)}</option>`).join('');$('#target-category').value=category;
        $('#target-stage').innerHTML='<option value="">Todas as etapas</option>'+window.LeadCRM.stageOptions('');$('#target-stage').value=stage;
        const overview=await api('/api/overview');const selected=$('#target-search').value;
        $('#target-search').innerHTML='<option value="">Todas as buscas</option>'+overview.searches.map(s=>`<option value="${e(s.id)}">${e(s.term)}</option>`).join('');$('#target-search').value=selected;
        await refreshCampaigns();
      }
    }catch(error){toast(error.message,true);}
  }
  async function poll(){clearTimeout(timer);try{if(document.body.dataset.view==='automation'&&!state.busy)await refreshCampaigns();state.pollError=false;}catch(error){$('#automation-connection').textContent='Falha ao atualizar resultados: '+error.message;if(!state.pollError){toast('Não foi possível atualizar o disparo: '+error.message,true);state.pollError=true;}}finally{timer=setTimeout(poll,2500);}}
  document.addEventListener('leadfinder:view',event=>activate(event.detail));
  document.addEventListener('leadfinder:campaign-targets',event=>{state.selectedTargets=new Set(event.detail);$('#campaign-mode').value='real';if(!$('#campaign-name').value)$('#campaign-name').value='Campanha para '+state.selectedTargets.size+' leads';modeChanged();switchView('automation');toast(state.selectedTargets.size+' leads trazidos para a campanha. Escolha as mensagens e revise.');});
  document.addEventListener('leadfinder:open-campaign',event=>openCampaign(event.detail).catch(error=>toast(error.message,true)));
  preview();activate(document.body.dataset.view);poll();
})();
