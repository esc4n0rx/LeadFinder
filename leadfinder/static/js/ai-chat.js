/* Chat/prompt workflow adapted from Beautiful UI primitives; no simulated AI replies. */
(() => {
  'use strict';
  const {api,toast}=window.LeadFinder,{escape:e,richText,loading,recommendation}=window.BeautifulUI;
  const $=selector=>document.querySelector(selector),history=$('#ai-chat-history'),prompt=$('#ai-chat-prompt');
  const state={providers:[],threads:[],thread:null,inFlight:null,loading:null,poll:null,clock:null,mode:'ai',
    historyOpen:innerWidth>760,lastMobile:innerWidth<=760,drafts:new Map(),pendingSince:0};
  const configured=()=>state.providers.find(item=>item.provider===$('#ai-chat-provider').value);
  const pending=()=>Boolean(state.inFlight || state.thread?.turns.some(turn=>turn.status==='pending'));
  const currentDraftKey=()=>state.thread?.id || 'new';
  const nearBottom=()=>history.scrollHeight-history.scrollTop-history.clientHeight<90;
  function setUrl() {
    if(document.body.dataset.view!=='agents')return;
    const url=new URL(location.href);url.pathname='/agents';url.search='';
    if(state.mode==='ai'){if(state.thread)url.searchParams.set('conversation',state.thread.id);}
    window.history.replaceState(null,'',url.pathname+url.search);
  }
  function resizePrompt() {
    prompt.style.height='auto';prompt.style.height=Math.min(prompt.scrollHeight,innerWidth<=760?100:160)+'px';
    $('#ai-prompt-count').textContent=prompt.value.length.toLocaleString('pt-BR')+' / 6.000';
    updateControls();
  }
  function updateFrame() {
    if(state.mode!=='ai' || document.body.dataset.view!=='agents')return;
    const main=$('#main-content'),viewport=window.visualViewport?.height || innerHeight;
    document.body.dataset.chatCompact=String(viewport<500 && innerWidth<=760);
    main.style.setProperty('--chat-frame-height',Math.max(0,viewport-Math.max(0,main.getBoundingClientRect().top))+'px');
  }
  function setHistory(open,restoreFocus=false) {
    state.historyOpen=open;const mobile=innerWidth<=760;
    $('#ai-chat-layout').classList.toggle('ai-history-open',open);
    $('#ai-chat-layout').classList.toggle('ai-history-collapsed',!open);
    $('#ai-history-panel').inert=!open;$('#ai-history-panel').setAttribute('aria-hidden',String(!open));
    $('#ai-history-toggle').setAttribute('aria-expanded',String(open));
    $('#ai-history-backdrop').hidden=!mobile || !open;
    if(restoreFocus)$('#ai-history-toggle').focus();
  }
  function onResize() {
    const mobile=innerWidth<=760;
    if(mobile!==state.lastMobile){state.lastMobile=mobile;setHistory(!mobile);}
    updateFrame();resizePrompt();
  }
  function scrollBottom() {history.scrollTop=history.scrollHeight;$('#ai-scroll-bottom').hidden=true;}
  function updateControls() {
    const item=configured(),busy=pending();
    $('#ai-chat-model').value=item?.model || '';$('#ai-chat-model').title=item?.model || '';
    $('#ai-chat-provider').disabled=busy;
    $('#ai-send').disabled=busy || !item?.configured || !prompt.value.trim();
    $('#ai-send').setAttribute('aria-label',busy?'Aguardando resposta da IA':'Conversar com a IA');
    $('#ai-chat-connection').hidden=Boolean(item?.configured);
    $('#ai-chat-connection').textContent=item?.configured?'':'Conecte uma API em Integrações → Inteligência artificial para começar.';
    $('#ai-chat-status').textContent=busy?(state.inFlight && state.inFlight!==state.thread?.id?'Outra conversa está gerando uma resposta. Você pode continuar navegando.':'Consultando e executando as ações solicitadas.'):'Envios, agendamentos e exclusões exigem revisão e confirmação nesta interface.';
    history.setAttribute('aria-busy',String(Boolean(state.thread?.turns.some(turn=>turn.status==='pending'))));
  }
  function renderThreads() {
    const query=$('#ai-thread-search').value.trim().toLocaleLowerCase('pt-BR');
    const items=state.threads.filter(thread=>thread.title.toLocaleLowerCase('pt-BR').includes(query));
    $('#ai-thread-count').textContent=state.threads.length;
    $('#ai-thread-list').innerHTML=items.length?items.map(thread=>`<button type="button" data-ai-thread="${e(thread.id)}" class="ai-thread ${state.thread?.id===thread.id?'active':''}" ${state.thread?.id===thread.id?'aria-current="true"':''}><strong>${e(thread.title)}</strong><small>${e(new Date(thread.updated_at).toLocaleDateString('pt-BR',{day:'2-digit',month:'short'}))}</small></button>`).join(''):`<p class="ai-empty-note">${query?'Nenhuma conversa encontrada.':'Organize seu trabalho em uma conversa.'}</p>`;
  }
  async function loadThreads() {state.threads=(await api('/api/ai/threads')).items;renderThreads();}
  function usageDetails(turn) {
    if(!Object.keys(turn.usage || {}).length)return '';
    const input=turn.usage.input_tokens ?? turn.usage.prompt_tokens ?? 0,output=turn.usage.output_tokens ?? turn.usage.completion_tokens ?? 0;
    return `<details class="ai-response-details"><summary>Detalhes da resposta</summary><small>${e(turn.model)} · ${Number(input).toLocaleString('pt-BR')} tokens de entrada · ${Number(output).toLocaleString('pt-BR')} de saída</small></details>`;
  }
  const toolLabels={workspace_overview:'Consultar workspace',leads_list:'Consultar leads',leads_get:'Consultar ficha',categories_list:'Consultar categorias',categories_create:'Criar categoria',messages_list:'Consultar mensagens',messages_create:'Criar mensagem',messages_update:'Atualizar mensagem',leads_organize:'Organizar leads',leads_edit:'Editar lead',leads_delete:'Excluir leads',funnels_list:'Consultar funis',funnels_create:'Criar funil',searches_list:'Consultar buscas',searches_cancel:'Interromper busca',searches_start:'Iniciar extração',notes_create:'Salvar anotação',reminders_create:'Criar lembrete',reminders_list:'Consultar lembretes',reminders_complete:'Atualizar lembrete',campaigns_list:'Consultar disparos',campaigns_get:'Consultar disparo',campaigns_prepare:'Preparar disparo',campaigns_start:'Iniciar disparo',campaigns_resume:'Retomar disparo',campaigns_schedule:'Agendar disparo',campaigns_pause:'Pausar disparo',campaigns_cancel:'Cancelar disparo',campaigns_verify:'Verificar tentativa',product_context_get:'Consultar produto',product_context_set:'Atualizar produto'};
  function actionSummary(action){const result=action.result || {};return result.error || result.message || (action.status==='pending'?'Revise os dados antes de confirmar.':result.name || (result.deleted!=null?result.deleted+' lead(s) excluído(s).':result.updated!=null?'Registros atualizados.':result.total!=null?result.total+' resultado(s) encontrado(s).':result.items?result.items.length+' registro(s) encontrado(s).':'Resultado registrado no workspace.'));}
  const actionLabels={pending:'Aguardando revisão',executing:'Executando',completed:'Concluído',failed:'Falhou',cancelled:'Cancelado',interrupted:'Interrompido'};
  function renderActions(actions){return actions.map(action=>`<section class="agent-action" data-action-id="${e(action.id)}"><div><strong>${e(toolLabels[action.tool] || 'Ação não disponível')}</strong><span class="count-badge">${e(actionLabels[action.status] || action.status)}</span></div><p>${e(actionSummary(action))}</p>${action.link?`<a class="text-button" href="${e(action.link)}">Abrir resultado ↗</a>`:''}${action.status==='pending'&&action.requires_confirmation?`<button type="button" class="secondary-button" data-review-action="${e(action.id)}">Revisar ação</button> <button type="button" class="text-button" data-cancel-action="${e(action.id)}">Cancelar</button>`:''}</section>`).join('');}
  async function reloadActions(){if(state.thread){state.thread=await api('/api/ai/threads/'+state.thread.id);renderThread();}document.dispatchEvent(new CustomEvent('leadfinder:leads-updated'));document.dispatchEvent(new CustomEvent('leadfinder:crm-updated'));window.LeadFinder.refreshOverview();}
  history.addEventListener('click',async event=>{
    const review=event.target.closest('[data-review-action]'),cancel=event.target.closest('[data-cancel-action]');if(!review&&!cancel)return;
    const button=review||cancel;button.disabled=true;
    try{if(cancel){await api('/api/agents/actions/'+cancel.dataset.cancelAction+'/cancel',{method:'POST',body:'{}'});await reloadActions();return;}
      const data=await api('/api/agents/actions/'+review.dataset.reviewAction+'/preview'),preview=data.preview,dialog=$('#agent-confirm-dialog');dialog.dataset.action=review.dataset.reviewAction;
      $('#agent-confirm-title').textContent=data.action.tool==='leads_delete'?'Excluir leads':'Confirmar ação de envio';
      $('#agent-confirm-details').textContent=preview.leads?preview.leads.map(lead=>lead.name+' · '+(lead.phone||'Sem telefone')).join('\n'):'Remetente: +'+preview.campaign.sender_phone+' · Intervalo: '+preview.campaign.interval_seconds+'s\n\n'+preview.campaign.messages.map(item=>item.target_name+' · +'+item.phone+'\n'+item.template_name+'\n'+item.body).join('\n\n──────────\n\n');
      $('#agent-confirm-help').textContent=preview.leads?preview.count+' lead(s) serão apagados, junto com suas notas e lembretes.':'Confira destinatários e textos. '+(preview.due_at?'Agendado para '+new Date(preview.due_at).toLocaleString():'A execução começará após confirmar.');
      dialog.showModal();
    }catch(error){toast(error.message,true);}finally{button.disabled=false;}
  });
  $('#agent-confirm-cancel').addEventListener('click',()=>$('#agent-confirm-dialog').close());
  $('#agent-confirm-submit').addEventListener('click',async event=>{event.target.disabled=true;try{const action=await api('/api/agents/actions/'+$('#agent-confirm-dialog').dataset.action+'/confirm',{method:'POST',body:JSON.stringify({confirmed:true})});$('#agent-confirm-dialog').close();if(action.tool==='leads_delete'&&action.status==='completed'){for(const id of action.arguments.ids)window.LeadDirectory?.selected.delete(id);}await reloadActions();toast(action.result?.error || action.result?.message || 'Ação registrada.',action.status!=='completed');}catch(error){toast(error.message,true);}finally{event.target.disabled=false;}});
  function renderThread(forceBottom=false) {
    const wasAtBottom=nearBottom(),oldScroll=history.scrollTop,turns=state.thread?.turns || [];
    $('#ai-assistant-title').textContent=state.thread?.title || 'Nova conversa';
    history.innerHTML=turns.length?`<div class="ai-transcript-content">${turns.map(turn=>`<article class="ai-turn"><div class="ai-user-message"><small>Você</small><p>${e(turn.user_text)}</p></div><div class="ai-assistant-message"><div class="ai-response-byline"><span class="ai-response-mark" aria-hidden="true">✦</span><strong>Agente do workspace</strong><small>${e(({openai:'OpenAI',openrouter:'OpenRouter',claude:'Claude'})[turn.provider] || turn.provider)}</small></div>${turn.status==='pending'?loading('Preparando sua resposta',Math.max(0,(Date.now()-new Date(turn.created_at).getTime())/1000)):turn.status==='failed'?`<div class="ai-error-card"><strong>Não foi possível concluir este pedido.</strong><p>${e(turn.error)}</p><button type="button" class="secondary-button" data-ai-edit="${turn.id}">Editar pedido</button></div>`:`<div class="ai-rich-text">${richText(turn.reply || '')}</div>${turn.error?`<p class="ai-error">${e(turn.error)}</p>`:''}<div class="ai-suggestions">${turn.suggestions.map((draft,index)=>recommendation(draft,turn.id,index)).join('')}</div>${usageDetails(turn)}`}${renderActions(turn.actions || [])}</div></article>`).join('')}</div>`:`<div class="ai-chat-empty"><span class="ai-empty-mark" aria-hidden="true">✦</span><span class="overline">SUA PRÓXIMA CONVERSA COMEÇA AQUI</span><h4>O que vamos criar hoje?</h4><p>Converse naturalmente sobre seu workspace.<br>Posso buscar e organizar leads, criar mensagens e funis.</p><div class="ai-starter-prompts"><button type="button" data-ai-starter="Quero apresentar meu produto. Me ajude a definir o público, os benefícios e um CTA claro.">Apresentar meu produto <span>↗</span></button><button type="button" data-ai-starter="Quero melhorar o CTA de uma mensagem. Vou compartilhar o texto e meu objetivo.">Melhorar uma mensagem <span>↗</span></button><button type="button" data-ai-starter="Quero criar um follow-up curto e gentil para minha campanha. Me ajude a definir o contexto.">Criar um follow-up <span>↗</span></button></div></div>`;
    if(forceBottom || wasAtBottom)scrollBottom();else{history.scrollTop=oldScroll;$('#ai-scroll-bottom').hidden=nearBottom();}
    clearInterval(state.clock);
    const active=turns.find(turn=>turn.status==='pending');
    if(active)state.clock=setInterval(()=>{history.querySelectorAll('[data-ai-elapsed]').forEach(node=>node.textContent=Math.max(0,Math.floor((Date.now()-new Date(active.created_at).getTime())/1000))+'s');},1000);
    updateControls();renderThreads();setUrl();
  }
  function schedulePoll() {
    clearTimeout(state.poll);
    if(!state.thread?.turns.some(turn=>turn.status==='pending'))return;
    const id=state.thread.id;
    state.poll=setTimeout(async()=>{
      try{const thread=await api('/api/ai/threads/'+id);if(state.thread?.id===id){state.thread=thread;renderThread();schedulePoll();}}
      catch(error){$('#ai-chat-status').textContent=error.message+' Abra a conversa novamente para consultar o resultado.';}
    },2500);
  }
  async function openThread(id) {
    const changing=state.thread?.id!==id;
    state.drafts.set(currentDraftKey(),prompt.value);clearTimeout(state.poll);
    const thread=await api('/api/ai/threads/'+id);state.thread=thread;
    prompt.value=state.drafts.get(id) || '';resizePrompt();
    const latest=thread.turns.at(-1);
    if(changing && !pending() && latest && state.providers.some(item=>item.configured && item.provider===latest.provider))$('#ai-chat-provider').value=latest.provider;
    renderThread(true);schedulePoll();if(innerWidth<=760)setHistory(false,true);
  }
  async function activate() {
    if(state.loading){try{await state.loading;}catch{}return;}
    state.loading=(async()=>{
      const selected=$('#ai-chat-provider').value;
      state.providers=(await api('/api/integrations/ai')).providers;
      const available=state.providers.filter(item=>item.configured);
      $('#ai-chat-provider').innerHTML=available.length?available.map(item=>`<option value="${item.provider}">${e(({openai:'OpenAI',openrouter:'OpenRouter',claude:'Claude'})[item.provider])}</option>`).join(''):'<option value="">Conectar uma API</option>';
      if(available.some(item=>item.provider===selected))$('#ai-chat-provider').value=selected;
      await loadThreads();
      if(state.thread && state.inFlight===state.thread.id){renderThread();return;}
      const requested=document.body.dataset.aiThread;
      const identity=state.thread?.id || (/^[a-f0-9]{32}$/.test(requested || '')?requested:state.threads[0]?.id);
      document.body.dataset.aiThread='';
      if(identity)await openThread(identity);else renderThread();
    })();
    try{await state.loading;}catch(error){$('#ai-chat-status').textContent=error.message;toast(error.message,true);}
    finally{state.loading=null;updateControls();}
  }
  $('#ai-history-toggle').addEventListener('click',()=>setHistory(!state.historyOpen));
  $('#ai-history-backdrop').addEventListener('click',()=>setHistory(false,true));
  $('#ai-thread-search').addEventListener('input',renderThreads);
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && innerWidth<=760 && state.historyOpen){setHistory(false,true);event.preventDefault();}});
  $('#ai-chat-provider').addEventListener('change',updateControls);
  history.addEventListener('scroll',()=>{$('#ai-scroll-bottom').hidden=nearBottom();},{passive:true});
  $('#ai-scroll-bottom').addEventListener('click',scrollBottom);
  prompt.addEventListener('input',()=>{state.drafts.set(currentDraftKey(),prompt.value);resizePrompt();});
  prompt.addEventListener('keydown',event=>{if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();if(!$('#ai-send').disabled)$('#ai-chat-form').requestSubmit();}});
  $('#ai-new-thread').addEventListener('click',async()=>{
    try{state.drafts.set(currentDraftKey(),prompt.value);state.thread=await api('/api/ai/threads',{method:'POST',body:'{}'});prompt.value='';resizePrompt();renderThread(true);await loadThreads();if(innerWidth<=760)setHistory(false,true);else prompt.focus();}catch(error){toast(error.message,true);}
  });
  $('#ai-thread-list').addEventListener('click',event=>{const button=event.target.closest('[data-ai-thread]');if(button)openThread(button.dataset.aiThread).catch(error=>toast(error.message,true));});
  $('#ai-chat-form').addEventListener('submit',async event=>{
    event.preventDefault();const text=prompt.value.trim(),provider=$('#ai-chat-provider').value;
    if(pending() || !text || !configured()?.configured)return;
    let id=state.thread?.id;const key=crypto.randomUUID();
    state.inFlight=id || 'new';prompt.value='';state.drafts.set(currentDraftKey(),'');resizePrompt();
    try {
      if(!id){state.thread=await api('/api/ai/threads',{method:'POST',body:'{}'});id=state.thread.id;state.inFlight=id;}
      state.thread.turns.push({id:'local-'+key,status:'pending',provider,model:configured().model,user_text:text,created_at:new Date().toISOString(),usage:{},suggestions:[]});renderThread(true);schedulePoll();
      const result=await api('/api/agents/threads/'+id+'/chat',{method:'POST',body:JSON.stringify({provider,message:text,request_key:key,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone})});
      state.inFlight=null;
      if(state.thread?.id===id){state.thread=await api('/api/ai/threads/'+id);renderThread();schedulePoll();}
      else toast('A resposta da outra conversa está disponível no histórico.');
      if(result.status==='failed')toast(result.error,true);document.dispatchEvent(new CustomEvent('leadfinder:leads-updated'));window.LeadFinder.refreshOverview();
      await loadThreads();
    } catch(error) {
      state.inFlight=null;
      if(!prompt.value){prompt.value=text;resizePrompt();}
      toast(error.message,true);$('#ai-chat-status').textContent=error.message+' Consulte o histórico antes de repetir.';
      if(id && state.thread?.id===id){try{state.thread=await api('/api/ai/threads/'+id);renderThread();schedulePoll();}catch{}}
    } finally {state.inFlight=null;updateControls();}
  });
  history.addEventListener('click',async event=>{
    const starter=event.target.closest('[data-ai-starter]');if(starter){prompt.value=(prompt.value?prompt.value+'\n':'')+starter.dataset.aiStarter;resizePrompt();prompt.focus();return;}
    const edit=event.target.closest('[data-ai-edit]');if(edit){const turn=state.thread?.turns.find(item=>String(item.id)===edit.dataset.aiEdit);if(turn){prompt.value=turn.user_text;resizePrompt();prompt.focus();}return;}
    const button=event.target.closest('[data-ai-use],[data-ai-copy]');if(!button)return;
    const turn=state.thread?.turns.find(item=>item.id===Number(button.dataset.aiUse || button.dataset.aiCopy));
    const draft=turn?.suggestions[Number(button.dataset.aiIndex)];if(!draft)return;
    if(button.dataset.aiUse){switchView('messages');document.dispatchEvent(new CustomEvent('leadfinder:ai-draft',{detail:draft}));}
    else{try{await navigator.clipboard.writeText(draft.body);toast('Texto copiado.');}catch{toast('Não foi possível copiar. Selecione o texto da mensagem para copiar.',true);}}
  });
  window.addEventListener('resize',onResize);window.visualViewport?.addEventListener('resize',updateFrame);
  document.addEventListener('leadfinder:view',event=>{if(event.detail==='agents'){window.scrollTo({top:0,behavior:'instant'});requestAnimationFrame(updateFrame);activate();}});
  document.addEventListener('leadfinder:ai-brief',async event=>{
    if(pending()){toast('Aguarde a geração atual antes de iniciar outra campanha.',true);return;}
    try{
      switchView('agents');
      state.thread=await api('/api/ai/threads',{method:'POST',body:'{}'});
      prompt.value=event.detail;state.drafts.set(currentDraftKey(),prompt.value);resizePrompt();renderThread(true);await loadThreads();
      if(innerWidth<=760)setHistory(false);prompt.focus();toast('Briefing preparado com os segmentos da seleção. Revise e envie para a IA.');
    }catch(error){toast(error.message,true);}
  });
  setHistory(state.historyOpen);if(document.body.dataset.view==='agents'){requestAnimationFrame(updateFrame);activate();}
})();
