'use strict';
(() => {
  const {api,toast,escape,icon}=window.LeadFinder;
  const el=id=>document.getElementById(id);
  let categories=[],page=1,request=0,editingLead=null,filterTimer,searchId='';
  const selected=new Set();let pageIds=[];
  const filters=()=>({search_id:searchId,q:el('directory-query').value.trim(),category_id:el('directory-category').value?Number(el('directory-category').value):null,contact_status:el('directory-status').value,stage:el('directory-stage').value});
  function selectionChanged(){el('lead-selection-count').textContent=selected.size+' selecionados';el('directory-bulk').disabled=!selected.size;el('directory-campaign').disabled=!selected.size;el('directory-ai').disabled=!selected.size;el('directory-select-page').checked=pageIds.length>0&&pageIds.every(id=>selected.has(id));el('directory-select-page').indeterminate=pageIds.some(id=>selected.has(id))&&!el('directory-select-page').checked;}
  const statuses={new:'Sem contato',contacted:'Contato iniciado',conversed:'Já houve conversa'};
  const statusOptions=value=>Object.entries(statuses).map(([key,label])=>`<option value="${key}" ${key===value?'selected':''}>${label}</option>`).join('');
  const date=value=>value?new Date(value).toLocaleDateString('pt-BR'):'—';
  function feedback(id,message='') { el(id).textContent=message;el(id).hidden=!message; }

  async function loadCategories() {
    const data=await api('/api/categories');
    categories=data.items;
    for (const [id,prefix] of [['discovery-category','<option value="">Sem categoria</option>'],['directory-category','<option value="">Todas as categorias</option><option value="0">Sem categoria</option>']]) {
      const select=el(id),previous=select.value;
      select.innerHTML=prefix+categories.map(c=>`<option value="${c.id}">${escape(c.name)}</option>`).join('');
      select.value=previous;
      if (select.selectedIndex<0) select.value='';
    }
  }

  async function refresh() {
    const sequence=++request;
    const params=new URLSearchParams({page,search_id:searchId,q:el('directory-query').value.trim(),category_id:el('directory-category').value,
      contact_status:el('directory-status').value,stage:el('directory-stage').value,grouped:el('directory-sort').value==='category'});
    feedback('directory-feedback','Atualizando leads…');
    el('directory-feedback').classList.remove('error');
    try {
      const data=await api('/api/leads?'+params);
      if (sequence!==request) return;
      if (page>1 && !data.items.length) { page--;return refresh(); }
      feedback('directory-feedback');
      el('directory-count').textContent=data.total;
      el('directory-table').hidden=!data.items.length;
      el('directory-empty').hidden=!!data.items.length;
      let previousGroup=null;
      pageIds=data.items.map(lead=>lead.id);
      el('directory-body').innerHTML=data.items.map(lead=>{
        const selectedCategory=categories.find(c=>String(c.id)===el('directory-category').value);
        const group=selectedCategory?.name || lead.categories[0]?.name || 'Sem categoria';
        let heading='';
        if (el('directory-sort').value==='category' && group!==previousGroup) {
          heading=`<tr class="directory-group"><td colspan="10">${escape(group)}</td></tr>`;previousGroup=group;
        }
        const website=safeUrl(lead.website);
        return heading+`<tr>
          <td class="selection-cell"><input type="checkbox" data-select-lead="${lead.id}" aria-label="Selecionar ${escape(lead.name)}" ${selected.has(lead.id)?'checked':''}></td>
          <td><button type="button" class="lead-link business-name" data-dossier="${lead.id}">${escape(lead.name)}</button><div class="business-category">${escape(lead.category || 'Categoria do Maps não informada')}</div></td>
          <td><div class="directory-tags">${lead.categories.length?lead.categories.map(c=>`<span class="directory-tag">${escape(c.name)}</span>`).join(''):'<span class="directory-muted">Sem categoria</span>'}</div></td>
          <td><span class="contact-phone">${escape(lead.phone || 'Não informado')}</span>${website?`<a class="contact-site" href="${escape(website)}" target="_blank" rel="noopener noreferrer">${escape(new URL(website).hostname)} ↗</a>`:''}</td>
          <td><span class="location-text" title="${escape(lead.address || '')}">${escape(lead.address || 'Não informado')}</span></td>
          <td>${lead.rating!=null?`<span class="rating-star">★</span> ${escape(lead.rating)}`:'—'}<div class="review-count">${lead.review_count!=null?escape(lead.review_count)+' avaliações':'Sem avaliações'}</div></td>
          <td><select class="directory-status" data-lead-status="${lead.id}" aria-label="Status de ${escape(lead.name)}">${statusOptions(lead.contact_status)}</select></td>
          <td><select class="directory-status" data-lead-stage="${lead.id}" aria-label="Etapa comercial de ${escape(lead.name)}">${window.LeadCRM?.stageOptions(lead.stage) || '<option>Novo</option>'}</select></td>
          <td class="directory-date">${date(lead.last_seen_at)}<small>Desde ${date(lead.first_seen_at)}</small>${lead.next_action?`<small>Próxima ação: ${date(lead.next_action)}</small>`:''}</td>
          <td><div class="directory-row-actions"><button class="text-button" type="button" data-edit-lead="${lead.id}">Editar</button><button class="text-button" type="button" data-delete-lead="${lead.id}">Excluir</button><button class="secondary-button" type="button" data-organize-lead="${lead.id}">Organizar</button><button class="detail-button" type="button" data-directory-detail="${lead.id}" aria-label="Detalhes de ${escape(lead.name)}">${icon('external')}</button></div></td>
        </tr>`;
      }).join('');
      selectionChanged();
      el('directory-results').textContent=data.total?`${(page-1)*data.per_page+1}–${Math.min(page*data.per_page,data.total)} de ${data.total} leads`:'Nenhum lead para os filtros selecionados.';
      el('directory-pagination').hidden=data.total<=data.per_page;
      el('directory-prev').disabled=page===1;
      el('directory-next').disabled=page*data.per_page>=data.total;
      el('directory-page').textContent=`${page} / ${Math.max(1,Math.ceil(data.total/data.per_page))}`;
    } catch(error) {
      if (sequence!==request) return;
      el('directory-table').hidden=true;el('directory-empty').hidden=true;el('directory-pagination').hidden=true;
      el('directory-feedback').classList.add('error');feedback('directory-feedback',error.message);
    }
  }

  function renderCategories() {
    el('categories-list').innerHTML=categories.length?categories.map(c=>`<form class="category-edit" data-category-id="${c.id}"><div><input aria-label="Renomear categoria ${escape(c.name)}" value="${escape(c.name)}" required minlength="2" maxlength="60"><small>${c.lead_count} lead(s)</small></div><button type="submit" class="secondary-button" aria-label="Salvar categoria ${escape(c.name)}">Salvar</button><button type="button" class="text-button category-delete" data-delete-category="${c.id}" aria-label="Excluir categoria ${escape(c.name)}">Excluir</button></form>`).join(''):'<p class="directory-muted">Nenhuma categoria criada. Comece pelo grupo da sua próxima busca.</p>';
  }
  async function manageCategories() {
    el('categories-dialog').showModal();feedback('categories-feedback','Carregando categorias…');
    try { await loadCategories();renderCategories();feedback('categories-feedback'); }
    catch(error) { feedback('categories-feedback',error.message); }
  }
  document.querySelectorAll('[data-manage-categories]').forEach(button=>button.addEventListener('click',manageCategories));
  document.querySelectorAll('[data-close-directory-dialog]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  async function categoryMutation(button,operation) {
    button.disabled=true;feedback('categories-feedback');
    try { await operation();await loadCategories();renderCategories();if(document.body.dataset.view==='leads')await refresh();toast('Categorias atualizadas.'); }
    catch(error) { feedback('categories-feedback',error.message); }
    finally { button.disabled=false; }
  }
  el('category-create').addEventListener('submit',event=>{
    event.preventDefault();
    categoryMutation(event.submitter,async()=>{const created=await api('/api/categories',{method:'POST',body:JSON.stringify({name:el('category-name').value.trim()})});el('category-name').value='';await loadCategories();el('discovery-category').value=String(created.id);});
  });
  el('categories-list').addEventListener('submit',event=>{
    event.preventDefault();const form=event.target;
    categoryMutation(event.submitter,()=>api('/api/categories/'+form.dataset.categoryId,{method:'POST',body:JSON.stringify({name:form.querySelector('input').value.trim()})}));
  });
  el('categories-list').addEventListener('click',event=>{
    const button=event.target.closest('[data-delete-category]');if(!button)return;
    if(button.dataset.confirm!=='yes') { button.dataset.confirm='yes';button.textContent='Confirmar exclusão';feedback('categories-feedback','Os leads serão preservados. Clique novamente para excluir a categoria.');return; }
    categoryMutation(button,()=>api('/api/categories/'+button.dataset.deleteCategory+'/delete',{method:'POST',body:'{}'}));
  });

  async function openLead(id) {
    try {
      const [lead]=await Promise.all([api('/api/leads/'+id),loadCategories()]);
      editingLead=lead.id;el('organize-name').textContent=lead.name;el('organize-status').value=lead.contact_status;
      el('organize-categories').innerHTML=categories.length?categories.map(c=>`<label class="checkbox-row"><input type="checkbox" value="${c.id}" ${lead.categories.some(item=>item.id===c.id)?'checked':''}><span>${escape(c.name)}</span></label>`).join(''):'<p class="directory-muted">Crie categorias pelo atalho “Gerenciar categorias”.</p>';
      feedback('organize-feedback');el('organize-dialog').showModal();
    } catch(error) { toast(error.message,true); }
  }
  el('organize-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=event.submitter;button.disabled=true;feedback('organize-feedback');
    try {
      await api(`/api/leads/${editingLead}/organization`,{method:'POST',body:JSON.stringify({category_ids:[...el('organize-categories').querySelectorAll('input:checked')].map(input=>Number(input.value)),contact_status:el('organize-status').value})});
      el('organize-dialog').close();await loadCategories();await refresh();toast('Organização salva.');
    } catch(error) { feedback('organize-feedback',error.message); }
    finally { button.disabled=false; }
  });
  el('directory-body').addEventListener('click',event=>{
    const organize=event.target.closest('[data-organize-lead]');if(organize)openLead(organize.dataset.organizeLead);
    const detail=event.target.closest('[data-directory-detail]');if(detail)window.LeadCRM.openDossier(detail.dataset.directoryDetail).catch(error=>toast(error.message,true));
  });
  el('directory-body').addEventListener('change',async event=>{
    const checkbox=event.target.closest('[data-select-lead]');if(checkbox){const id=Number(checkbox.dataset.selectLead);if(checkbox.checked){if(selected.size>=1000){checkbox.checked=false;toast('Selecione até 1.000 leads.',true);return;}selected.add(id);}else selected.delete(id);selectionChanged();return;}
    const stage=event.target.closest('[data-lead-stage]');if(stage){stage.disabled=true;try{await api('/api/leads/bulk',{method:'POST',body:JSON.stringify({ids:[Number(stage.dataset.leadStage)],changes:{stage:stage.value}})});toast('Etapa atualizada.');}catch(error){toast(error.message,true);}finally{await refresh();}return;}
    const select=event.target.closest('[data-lead-status]');if(!select)return;
    select.disabled=true;
    try { await api(`/api/leads/${select.dataset.leadStatus}/organization`,{method:'POST',body:JSON.stringify({contact_status:select.value})});toast('Status de contato atualizado.'); }
    catch(error) { toast(error.message,true); }
    finally { await refresh(); }
  });
  for(const id of ['directory-category','directory-status','directory-sort','directory-stage'])el(id).addEventListener('change',()=>{page=1;refresh();});
  el('directory-query').addEventListener('input',()=>{clearTimeout(filterTimer);page=1;filterTimer=setTimeout(refresh,250);});
  el('directory-clear').addEventListener('click',()=>{searchId='';el('directory-search').value='';el('directory-query').value='';el('directory-category').value='';el('directory-status').value='';el('directory-stage').value='';page=1;refresh();});
  el('directory-select-page').addEventListener('change',event=>{for(const id of pageIds){if(event.target.checked&&selected.size<1000)selected.add(id);else if(!event.target.checked)selected.delete(id);}refresh();});
  el('directory-select-all').addEventListener('click',async event=>{event.target.disabled=true;try{const data=await api('/api/leads/selection',{method:'POST',body:JSON.stringify({filters:filters()})});selected.clear();data.ids.forEach(id=>selected.add(id));await refresh();toast(data.total+' leads selecionados.');}catch(error){toast(error.message,true);}finally{event.target.disabled=false;}});
  el('directory-clear-selection').addEventListener('click',()=>{selected.clear();refresh();});
  el('directory-export').addEventListener('click',async event=>{event.target.disabled=true;try{await window.LeadCRM.download('/api/leads/export',selected.size?{ids:[...selected]}:{filters:filters()},'leadfinder-leads.csv');toast('CSV exportado.');}catch(error){toast(error.message,true);}finally{event.target.disabled=false;}});
  el('directory-campaign').addEventListener('click',()=>{if(selected.size>100){toast('Selecione até 100 leads para uma campanha.',true);return;}document.dispatchEvent(new CustomEvent('leadfinder:campaign-targets',{detail:[...selected]}));});
  el('directory-ai').addEventListener('click',async event=>{event.target.disabled=true;try{const data=await api('/api/leads/brief',{method:'POST',body:JSON.stringify({ids:[...selected]})});document.dispatchEvent(new CustomEvent('leadfinder:ai-brief',{detail:data.brief}));}catch(error){toast(error.message,true);}finally{selectionChanged();}});
  el('directory-prev').addEventListener('click',()=>{page--;refresh();});
  el('directory-next').addEventListener('click',()=>{page++;refresh();});
  document.addEventListener('leadfinder:view',event=>{if(event.detail==='leads')loadCategories().then(refresh).catch(error=>toast(error.message,true));});
  document.addEventListener('leadfinder:leads-updated',()=>{if(document.body.dataset.view==='leads')refresh();});
  document.addEventListener('leadfinder:crm-updated',()=>{if(document.body.dataset.view==='leads')refresh();});
  el('directory-search').addEventListener('change',()=>{searchId=el('directory-search').value;page=1;refresh();});
  document.addEventListener('leadfinder:overview',event=>{const select=el('directory-search');select.innerHTML='<option value="">Todas as buscas</option>'+event.detail.searches.map(item=>`<option value="${escape(item.id)}">${escape(item.term)}</option>`).join('');select.value=searchId;});
  document.addEventListener('leadfinder:directory-search',event=>{searchId=event.detail;el('directory-search').value=searchId;page=1;refresh();});
  window.LeadDirectory={selected,refresh,filters};
  loadCategories().then(()=>{if(document.body.dataset.view==='leads')refresh();}).catch(error=>toast(error.message,true));
})();
