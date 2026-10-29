'use strict';
(() => {
  const {api,toast,escape:e}=window.LeadFinder;
  const el=id=>document.getElementById(id);
  const stages={new:'Novo',contacted:'Contatado',replied:'Respondeu',demo:'Demonstração',customer:'Cliente',lost:'Perdido'};
  const outcomes={draft:'Rascunho',scheduled:'Agendado',pending:'Pendente',sent:'Aceita pelo WhatsApp',uncertain:'Sem confirmação',failed:'Falhou',simulated:'Simulação',sending:'Em envio'};
  const stageOptions=value=>Object.entries(stages).map(([id,label])=>`<option value="${id}" ${value===id?'selected':''}>${label}</option>`).join('');
  const date=value=>new Date(value).toLocaleString('pt-BR');
  let dossierId=null,boardRequest=0,restoreToken=null,boardTimer;
  el('directory-stage').insertAdjacentHTML('beforeend',stageOptions(''));
  el('bulk-stage').insertAdjacentHTML('beforeend',stageOptions(''));
  const download=async(path,data,name)=>{
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-LeadFinder-Token':document.querySelector('meta[name=leadfinder-token]').content},body:JSON.stringify(data)});
    if(!response.ok)throw new Error((await response.json()).error || 'Não foi possível baixar o arquivo.');
    const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  async function openDossier(id) {
    const lead=await api(`/api/leads/${id}/dossier`);dossierId=lead.id;
    if(el('lead-dialog').open)el('lead-dialog').close();
    const website=safeUrl(lead.website),maps=safeUrl(lead.maps_url);
    const details=lead.details || {};
    const more=[['Horários',lead.hours],['Plus Code',lead.plus_code],['Coordenadas',lead.latitude!=null?lead.latitude+', '+lead.longitude:null],['Descrição',details.description],['Características',details.attributes?.join(' · ')],['Preço',details.price],['Situação no Maps',details.business_status]].filter(([,value])=>value!=null&&value!=='');
    el('dossier-content').innerHTML=`<div class="dossier-heading"><div><h2 id="dossier-title">${e(lead.name)}</h2><p>${e(lead.category || 'Estabelecimento')}${lead.categories.length?' · '+e(lead.categories.map(c=>c.name).join(', ')):''}</p></div><div class="directory-row-actions"><button type="button" class="secondary-button" data-edit-lead="${lead.id}">Editar</button><button type="button" class="text-button" data-delete-lead="${lead.id}">Excluir</button></div>${maps?`<a class="text-button" href="${e(maps)}" target="_blank" rel="noopener noreferrer">Maps ↗</a>`:''}</div>
      <div class="dossier-grid"><section><div class="dossier-info"><p>${e(lead.phone || 'Telefone não informado')}</p><p>${e(lead.address || 'Endereço não informado')}</p>${website?`<a href="${e(website)}" target="_blank" rel="noopener noreferrer">${e(website)} ↗</a>`:''}<p>${lead.rating!=null?'★ '+e(lead.rating)+' · ':''}${lead.review_count!=null?e(lead.review_count)+' avaliações':''}</p><p>Primeira coleta: ${date(lead.first_seen_at)}<br>Atualização: ${date(lead.last_seen_at)}</p></div>
      ${more.length?`<details class="dossier-more"><summary>Mais informações do estabelecimento</summary><dl class="detail-grid">${more.map(([label,value])=>`<div class="detail-row"><dt>${e(label)}</dt><dd>${e(value)}</dd></div>`).join('')}</dl></details>`:''}<div class="field"><label for="dossier-stage">Etapa deste lead</label><select id="dossier-stage">${stageOptions(lead.stage)}</select></div>
      <h3>Anotações</h3><form id="dossier-note-form"><label for="dossier-note">Nova anotação</label><textarea id="dossier-note" required maxlength="4000" rows="3" placeholder="O que você precisa lembrar sobre esta oportunidade?"></textarea><button type="submit" class="secondary-button">Salvar anotação</button></form><div>${lead.notes.map(note=>`<div class="dossier-note"><small>${date(note.created_at)}</small><p>${e(note.body)}</p></div>`).join('')}</div>
      <h3>Próxima ação</h3><form id="dossier-reminder-form"><div class="field"><label for="dossier-task">Lembrete</label><input id="dossier-task" required minlength="2" maxlength="160" placeholder="Ex.: confirmar demonstração"></div><div class="field"><label for="dossier-due">Quando retornar</label><input id="dossier-due" type="datetime-local" required></div><button type="submit" class="secondary-button">Criar lembrete</button></form><div>${lead.reminders.map(task=>taskRow(task)).join('')}</div>
      <h3>Buscas de origem</h3><p class="field-help">${e(lead.searches.map(search=>search.term+(search.location?' · '+search.location:'')).join(' / '))}</p></section>
      <section><h3>Linha do tempo</h3><ol class="dossier-timeline">${lead.timeline.map(item=>`<li><time>${date(item.created_at)} · ${e({discovery:'Descoberta',note:'Anotação',stage:'Etapa comercial',reminder:'Lembrete',categories:'Categorias',organization:'Organização',contact:'Contato',message:outcomes[item.status] || 'Mensagem'}[item.kind] || item.kind)}</time><p>${e(item.body)}</p>${item.campaign_id?`<button type="button" class="text-button" data-open-campaign="${e(item.campaign_id)}">${e(item.campaign_name)} ↗</button>`:''}</li>`).join('')}</ol></section></div>`;
    el('dossier-feedback').hidden=true;
    if(!el('dossier-dialog').open)el('dossier-dialog').showModal();
  }
  function taskRow(task) {
    return `<article class="task-row ${!task.completed_at&&new Date(task.due_at)<new Date()?'overdue':''}"><div><strong>${e(task.title)}</strong>${task.lead_name?`<button type="button" class="text-button" data-dossier="${task.lead_id}">${e(task.lead_name)} ↗</button>`:''}<small>${task.completed_at?'Concluído em '+date(task.completed_at):'Retorno programado'}</small></div><time>${date(task.due_at)}</time><button type="button" class="secondary-button" data-reminder-id="${task.id}" data-completed="${!task.completed_at}">${task.completed_at?'Reabrir':'Concluir'}</button></article>`;
  }
  async function refreshTasks() {
    const data=await api('/api/reminders?filter='+el('tasks-filter').value);
    el('tasks-list').innerHTML=data.items.length?data.items.map(taskRow).join(''):'<div class="outreach-empty">Nenhum lembrete neste filtro. Crie a próxima ação na ficha de um lead.</div>';
  }
  document.querySelectorAll('[data-close-crm-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  el('dossier-content').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;
    try {
      if(event.target.id==='dossier-note-form')await api(`/api/leads/${dossierId}/notes`,{method:'POST',body:JSON.stringify({body:el('dossier-note').value})});
      else await api(`/api/leads/${dossierId}/reminders`,{method:'POST',body:JSON.stringify({title:el('dossier-task').value,due_at:new Date(el('dossier-due').value).toISOString()})});
      await openDossier(dossierId);toast('Ficha atualizada.');document.dispatchEvent(new CustomEvent('leadfinder:crm-updated'));
    } catch(error) {el('dossier-feedback').hidden=false;el('dossier-feedback').textContent=error.message;}
    finally {button.disabled=false;}
  });
  el('dossier-content').addEventListener('change',async event=>{
    if(event.target.id!=='dossier-stage')return;
    try {await api('/api/leads/bulk',{method:'POST',body:JSON.stringify({ids:[dossierId],changes:{stage:event.target.value}})});await openDossier(dossierId);document.dispatchEvent(new CustomEvent('leadfinder:crm-updated'));}
    catch(error){toast(error.message,true);}
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-dossier]'),reminder=event.target.closest('[data-reminder-id]'),campaign=event.target.closest('[data-open-campaign]');
    try {
      if(button)await openDossier(button.dataset.dossier);
      if(reminder){reminder.disabled=true;await api('/api/reminders/'+reminder.dataset.reminderId,{method:'POST',body:JSON.stringify({completed:reminder.dataset.completed==='true'})});if(el('dossier-dialog').open)await openDossier(dossierId);if(document.body.dataset.view==='tasks')await refreshTasks();document.dispatchEvent(new CustomEvent('leadfinder:crm-updated'));}
      if(campaign){el('dossier-dialog').close();switchView('automation');document.dispatchEvent(new CustomEvent('leadfinder:open-campaign',{detail:campaign.dataset.openCampaign}));}
    } catch(error){toast(error.message,true);if(reminder)reminder.disabled=false;}
  });

  function boardCard(lead) {
    return `<article class="pipeline-card" draggable="true" data-drag-lead="${lead.id}"><span class="pipeline-grip" draggable="true" aria-hidden="true" title="Arrastar lead">⠿</span><button type="button" class="lead-link" data-dossier="${lead.id}">${e(lead.name)}</button><small>${e(lead.categories.map(c=>c.name).join(' · ') || lead.category || 'Sem categoria')}</small><small>${e(lead.phone || 'Sem telefone')}</small>${lead.next_action?`<small>Próxima ação: ${date(lead.next_action)}</small>`:''}<select data-card-stage="${lead.id}" aria-label="Etapa de ${e(lead.name)}">${stageOptions(lead.stage)}</select></article>`;
  }
  async function refreshBoard() {
    const request=++boardRequest;el('pipeline-feedback').textContent='Atualizando oportunidades…';
    try {
      const data=await api('/api/crm/board?'+new URLSearchParams({q:el('pipeline-query').value.trim(),funnel_id:el('pipeline-saved').value}));if(request!==boardRequest)return;
      el('pipeline-board').innerHTML=data.columns.map(column=>`<section class="pipeline-column" data-drop-stage="${column.stage}"><h3>${e(column.label)} <span class="count-badge">${column.total}</span></h3><div class="pipeline-cards">${column.items.map(boardCard).join('') || '<p class="field-help">Nenhuma oportunidade nesta etapa.</p>'}</div>${column.total>25?`<button class="text-button" type="button" data-more-stage="${column.stage}" data-page="1" data-total="${column.total}">Carregar mais</button>`:''}</section>`).join('');el('pipeline-feedback').textContent='Arraste um cartão ou use o seletor de etapa.';
    } catch(error){el('pipeline-feedback').textContent=error.message;}
  }
  async function moveLead(id,stage) {await api('/api/leads/bulk',{method:'POST',body:JSON.stringify({ids:[Number(id)],changes:{stage}})});await refreshBoard();}
  el('pipeline-board').addEventListener('change',event=>{const select=event.target.closest('[data-card-stage]');if(select)moveLead(select.dataset.cardStage,select.value).catch(error=>toast(error.message,true));});
  el('pipeline-board').addEventListener('dragstart',event=>{const card=event.target.closest('[data-drag-lead]');if(card)event.dataTransfer.setData('text/plain',card.dataset.dragLead);});
  el('pipeline-board').addEventListener('dragover',event=>{const column=event.target.closest('[data-drop-stage]');if(column){event.preventDefault();column.classList.add('drag-over');}});
  el('pipeline-board').addEventListener('dragleave',event=>event.target.closest('[data-drop-stage]')?.classList.remove('drag-over'));
  el('pipeline-board').addEventListener('drop',event=>{event.preventDefault();const column=event.target.closest('[data-drop-stage]');if(column){column.classList.remove('drag-over');const id=event.dataTransfer.getData('text/plain');if(/^\d+$/.test(id))moveLead(id,column.dataset.dropStage).catch(error=>toast(error.message,true));}});
  el('pipeline-board').addEventListener('click',async event=>{
    const button=event.target.closest('[data-more-stage]');if(!button)return;button.disabled=true;
    try {const page=Number(button.dataset.page)+1;const data=await api('/api/crm/board/'+button.dataset.moreStage+'?'+new URLSearchParams({page,q:el('pipeline-query').value.trim(),funnel_id:el('pipeline-saved').value}));button.parentElement.querySelector('.pipeline-cards').insertAdjacentHTML('beforeend',data.items.map(boardCard).join(''));button.dataset.page=page;button.hidden=page*25>=data.total;}
    catch(error){toast(error.message,true);}finally{button.disabled=false;}
  });
  el('pipeline-refresh').addEventListener('click',refreshBoard);
  el('pipeline-query').addEventListener('input',()=>{clearTimeout(boardTimer);boardTimer=setTimeout(refreshBoard,250);});
  el('tasks-filter').addEventListener('change',()=>refreshTasks().catch(error=>toast(error.message,true)));

  el('directory-bulk').addEventListener('click',async()=>{
    try {const data=await api('/api/categories');el('bulk-categories').innerHTML=data.items.map(c=>`<label class="checkbox-row"><input type="checkbox" value="${c.id}"><span>${e(c.name)}</span></label>`).join('');el('bulk-form').reset();el('bulk-feedback').textContent='';el('bulk-dialog').showModal();}
    catch(error){toast(error.message,true);}
  });
  el('bulk-form').addEventListener('submit',async event=>{
    event.preventDefault();event.submitter.disabled=true;
    try {
      const changes={};if(el('bulk-stage').value)changes.stage=el('bulk-stage').value;if(el('bulk-status').value)changes.contact_status=el('bulk-status').value;
      if(el('bulk-category-mode').value!=='keep'){changes.category_mode=el('bulk-category-mode').value;changes.category_ids=[...el('bulk-categories').querySelectorAll('input:checked')].map(input=>Number(input.value));}
      await api('/api/leads/bulk',{method:'POST',body:JSON.stringify({ids:[...window.LeadDirectory.selected],changes})});el('bulk-dialog').close();await window.LeadDirectory.refresh();toast('Leads selecionados atualizados.');
    } catch(error){el('bulk-feedback').textContent=error.message;}finally{event.submitter.disabled=false;}
  });

  const contextFields={product:'product-name',differentials:'product-differentials',audience:'product-audience',offer:'product-offer',tone:'product-tone'};
  async function loadContext(){const data=await api('/api/product-context');for(const [field,id] of Object.entries(contextFields))el(id).value=data[field] || '';}
  el('product-context-form').addEventListener('submit',async event=>{
    event.preventDefault();event.submitter.disabled=true;
    try{await api('/api/product-context',{method:'POST',body:JSON.stringify(Object.fromEntries(Object.entries(contextFields).map(([field,id])=>[field,el(id).value])))});el('product-feedback').textContent='Contexto salvo. Será usado nas próximas interações com a IA.';toast('Contexto do produto salvo.');}
    catch(error){el('product-feedback').textContent=error.message;}finally{event.submitter.disabled=false;}
  });
  el('backup-export-form').addEventListener('submit',async event=>{
    event.preventDefault();event.submitter.disabled=true;el('backup-feedback').textContent='Preparando backup. A conexão do WhatsApp pode reiniciar brevemente.';
    try{await download('/api/backups/export',{password:el('backup-password').value},'leadfinder-workspace.lfbackup');el('backup-password').value='';el('backup-feedback').textContent='Backup baixado. Guarde o arquivo e sua senha.';}
    catch(error){el('backup-feedback').textContent=error.message;}finally{event.submitter.disabled=false;}
  });
  function invalidatePreview(){restoreToken=null;el('restore-preview').hidden=true;el('backup-restore-form').hidden=true;}
  el('restore-file').addEventListener('change',invalidatePreview);el('restore-password').addEventListener('input',invalidatePreview);
  el('backup-preview-form').addEventListener('submit',async event=>{
    event.preventDefault();event.submitter.disabled=true;invalidatePreview();el('backup-feedback').textContent='Validando arquivo e vínculos do workspace…';
    try{
      const form=new FormData();form.set('file',el('restore-file').files[0]);form.set('password',el('restore-password').value);form.set('csrf_token',document.querySelector('meta[name=leadfinder-token]').content);
      const response=await fetch('/api/backups/preview',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw new Error(data.error);
      restoreToken=data.token;el('restore-preview').innerHTML=`<strong>${e(data.name)}</strong><p>Criado em ${date(data.created_at)}</p><p>${data.counts.leads} leads · ${data.counts.lead_categories} categorias · ${data.counts.campaigns} campanhas · ${data.counts.reminders} lembretes</p><p>${data.ai_integrations} integração(ões) de IA · sessão WhatsApp ${data.whatsapp_session?'incluída':'não incluída'}</p>`;el('restore-preview').hidden=false;el('backup-restore-form').hidden=false;el('backup-feedback').textContent='Prévia válida por 10 minutos. Revise os dados antes de confirmar.';
    }catch(error){el('backup-feedback').textContent=error.message;}finally{event.submitter.disabled=false;}
  });
  el('backup-restore-form').addEventListener('submit',async event=>{
    event.preventDefault();if(!restoreToken)return;event.submitter.disabled=true;el('backup-feedback').textContent='Restaurando workspace…';
    try{await api('/api/backups/restore',{method:'POST',body:JSON.stringify({token:restoreToken,password:el('restore-password').value,confirmation:el('restore-confirmation').value,account_password:el('restore-account-password').value})});window.location.assign('/leads');}
    catch(error){el('backup-feedback').textContent=error.message;event.submitter.disabled=false;}
  });
  async function loadFunnels(){const select=el('pipeline-saved'),previous=select.value||document.body.dataset.initialFunnel;const data=await api('/api/funnels');select.innerHTML='<option value="">Todos os leads</option>'+data.items.map(item=>`<option value="${item.id}">${e(item.name)}</option>`).join('');select.value=previous;if(select.selectedIndex<0)select.value='';document.body.dataset.initialFunnel='';}
  el('pipeline-saved').addEventListener('change',refreshBoard);
  async function activate(view){if(view==='pipeline'){await loadFunnels();await refreshBoard();}if(view==='tasks')await refreshTasks();if(view==='workspace')await loadContext();}
  document.addEventListener('leadfinder:view',event=>activate(event.detail).catch(error=>toast(error.message,true)));
  document.addEventListener('leadfinder:crm-updated',()=>{if(document.body.dataset.view==='pipeline')refreshBoard();});
  window.LeadCRM={openDossier,stageOptions,stages,download};
  activate(document.body.dataset.view).catch(error=>toast(error.message,true));
})();
