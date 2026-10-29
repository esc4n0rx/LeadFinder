/* Provider cards and searchable settings dialog; Beautiful UI Search/Card adaptation. */
(() => {
  'use strict';
  const root=document.querySelector('#ai-provider-cards');if(!root)return;
  const {api,toast}=window.LeadFinder,{escape:e}=window.BeautifulUI;
  const dialog=document.querySelector('#ai-config-dialog'),body=document.querySelector('#ai-config-dialog-body');
  const state={providers:[],models:new Map(),tested:new Set(),matches:[],active:-1,busy:false};
  const find=id=>state.providers.find(item=>item.provider===id);
  const shortName=id=>({openai:'OpenAI',openrouter:'OpenRouter',claude:'Claude'}[id] || id);
  function renderCards() {
    root.innerHTML=state.providers.map(item=>`<article class="ai-provider-card" data-ai-provider="${item.provider}"><div class="ai-provider-title"><span class="ai-provider-mark">${item.provider==='openrouter'?'OR':item.provider==='claude'?'C':'O'}</span><span class="status-badge ${item.configured?'ai-connected':''}">${state.tested.has(item.provider)?'Validada agora':item.configured?'Chave salva':'Não conectado'}</span></div><h3>${e(shortName(item.provider))}</h3><p class="ai-provider-description">${e({openai:'Modelos GPT para suas campanhas.',openrouter:'Vários modelos em uma única API.',claude:'Escrita e refinamento com Claude.'}[item.provider])}</p><div class="ai-provider-model"><span>Modelo selecionado</span><strong title="${e(item.model)}">${e(item.model)}</strong></div><button class="${item.configured?'secondary':'primary'}-button" type="button" data-ai-configure="${item.provider}">${item.configured?'Configurar integração':'Conectar provedor'} ↗</button></article>`).join('');
  }
  async function load() {
    state.providers=(await api('/api/integrations/ai')).providers;
    state.providers.forEach(item=>{if(!state.models.has(item.provider))state.models.set(item.provider,item.models);});renderCards();
  }
  function renderDialog(item) {
    dialog.dataset.provider=item.provider;
    document.querySelector('#ai-config-title').textContent=shortName(item.provider);
    body.innerHTML=`<form data-ai-config="${item.provider}"><fieldset><p class="ai-config-intro">Conecte sua chave e escolha o modelo que vai ajudar nas mensagens.</p><div><label for="ai-key-${item.provider}">Chave de API</label><input id="ai-key-${item.provider}" name="api_key" type="password" autocomplete="new-password" spellcheck="false" maxlength="512" ${item.configured?'':'required'} placeholder="${item.configured?'Chave salva · final '+e(item.key_hint):'Cole sua chave de API'}"><small>${item.configured?'Deixe em branco para manter a chave atual.':'Sua chave fica criptografada neste computador.'}</small></div><div class="ai-model-picker"><label for="ai-model-${item.provider}">Modelo ${e(item.name)}</label><div class="ai-model-input"><input id="ai-model-${item.provider}" name="model" required maxlength="150" value="${e(item.model)}" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="ai-model-options"><button type="button" class="icon-button" data-ai-show-models aria-label="Mostrar modelos">⌄</button></div><div id="ai-model-options" role="listbox" aria-label="Modelos disponíveis" hidden></div><small>Busque pelo nome ou informe o ID de um modelo de texto.</small></div>${item.provider==='claude'?`<details class="ai-advanced"><summary>Opções avançadas</summary><label for="ai-workspace-claude">ID do workspace Anthropic</label><input id="ai-workspace-claude" name="provider_workspace" maxlength="108" value="${e(item.provider_workspace)}" placeholder="wrkspc_…"><small>Opcional. Preencha somente se sua chave exigir seleção de workspace.</small></details>`:''}<div class="ai-config-tools"><button class="secondary-button" type="button" data-ai-action="test" ${item.configured?'':'disabled'}>Testar conexão</button><button class="text-button" type="button" data-ai-action="models" ${item.configured?'':'disabled'}>Atualizar modelos</button></div><p class="ai-provider-feedback" role="status">${state.tested.has(item.provider)?'Chave validada e modelo encontrado no catálogo.':item.configured?'Configuração salva. Teste a chave e o modelo sem gerar mensagens.':'Salve a chave para testar a conexão e atualizar os modelos.'}</p><div class="ai-provider-links"><a href="${item.keys_url}" target="_blank" rel="noopener noreferrer">Obter chave ↗</a><a href="${item.docs_url}" target="_blank" rel="noopener noreferrer">Documentação ↗</a></div></fieldset><footer class="ai-config-footer"><button class="text-button ai-remove-key" type="button" data-ai-action="remove" ${item.configured?'':'disabled'}>Remover chave</button><div><button class="secondary-button" type="button" data-ai-cancel>Cancelar</button><button class="primary-button" type="submit">Salvar ${e(item.name)}</button></div></footer></form>`;
    state.active=-1;
  }
  function feedback(message,error=false) {
    const node=body.querySelector('.ai-provider-feedback');if(!node)return;
    node.textContent=message;node.classList.toggle('ai-error',error);
  }
  function dirty() {
    const form=body.querySelector('form'),item=find(dialog.dataset.provider);if(!form || !item)return false;
    return Boolean(form.elements.api_key.value.trim()) || form.elements.model.value!==item.model || (form.elements.provider_workspace?.value || '')!==item.provider_workspace;
  }
  function updateTools() {
    const item=find(dialog.dataset.provider);
    body.querySelectorAll('[data-ai-action]').forEach(button=>button.disabled=state.busy || !item?.configured || dirty());
    if(dirty())feedback('Alterações não salvas. Salve antes de testar ou atualizar o catálogo.');
  }
  function closeModels() {
    const list=body.querySelector('#ai-model-options'),input=body.querySelector('[name=model]');
    if(list)list.hidden=true;if(input){input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');}state.active=-1;
  }
  function showModels(all=false) {
    const input=body.querySelector('[name=model]'),list=body.querySelector('#ai-model-options');if(!input || !list)return;
    const query=all?'':input.value.trim().toLocaleLowerCase('pt-BR');
    state.matches=(state.models.get(dialog.dataset.provider) || []).filter(model=>(model.id+' '+model.name).toLocaleLowerCase('pt-BR').includes(query)).slice(0,60);
    state.active=-1;
    list.innerHTML=state.matches.length?state.matches.map((model,index)=>`<button type="button" role="option" id="ai-model-option-${index}" aria-selected="${model.id===input.value}" data-ai-model="${index}"><strong>${e(model.name)}</strong><small>${e(model.id)}</small></button>`).join(''):'<p class="ai-model-empty">Nenhum resultado. Você pode informar outro ID e salvar.</p>';
    list.hidden=false;input.setAttribute('aria-expanded','true');
  }
  function chooseModel(index) {
    const model=state.matches[index];if(!model)return;
    const input=body.querySelector('[name=model]');input.value=model.id;closeModels();input.focus();updateTools();
  }
  function setBusy(value) {
    state.busy=value;document.querySelector('#ai-config-close').disabled=value;body.querySelector('fieldset').disabled=value;
    body.querySelectorAll('.ai-config-footer button').forEach(button=>button.disabled=value);
    if(!value)updateTools();
  }
  root.addEventListener('click',event=>{
    const button=event.target.closest('[data-ai-configure]');if(!button)return;
    renderDialog(find(button.dataset.aiConfigure));dialog.showModal();
  });
  const close=()=>{if(!state.busy)dialog.close();};
  document.querySelector('#ai-config-close').addEventListener('click',close);
  dialog.addEventListener('cancel',event=>{const list=body.querySelector('#ai-model-options');if(state.busy || (list && !list.hidden)){event.preventDefault();if(!state.busy)closeModels();}});
  dialog.addEventListener('close',()=>{const key=body.querySelector('[name=api_key]');if(key)key.value='';body.replaceChildren();root.querySelector('[data-ai-configure="'+dialog.dataset.provider+'"]')?.focus();});
  dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom)close();}});
  body.addEventListener('input',event=>{updateTools();if(event.target.name==='model')showModels();});
  body.addEventListener('focusin',event=>{if(event.target.name==='model')showModels(true);});
  body.addEventListener('focusout',event=>{if(event.target.name==='model')setTimeout(()=>{if(!document.activeElement?.closest('.ai-model-picker'))closeModels();},0);});
  body.addEventListener('keydown',event=>{
    if(event.target.name!=='model')return;
    const list=body.querySelector('#ai-model-options');
    if(event.key==='Escape' && !list.hidden){event.preventDefault();event.stopPropagation();closeModels();}
    if(['ArrowDown','ArrowUp'].includes(event.key)) {
      event.preventDefault();if(list.hidden)showModels(true);
      if(!state.matches.length)return;
      state.active=(state.active+(event.key==='ArrowDown'?1:-1)+state.matches.length)%state.matches.length;
      list.querySelectorAll('[role=option]').forEach((option,index)=>option.classList.toggle('active',index===state.active));
      const active=list.querySelector('#ai-model-option-'+state.active);event.target.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});
    }
    if(event.key==='Enter' && !list.hidden && state.active>=0){event.preventDefault();chooseModel(state.active);}
  });
  body.addEventListener('submit',async event=>{
    event.preventDefault();if(state.busy)return;closeModels();
    const provider=dialog.dataset.provider,form=event.target,values=Object.fromEntries(new FormData(form));setBusy(true);feedback('Salvando integração…');
    try {
      const item=await api('/api/integrations/ai/'+provider,{method:'POST',body:JSON.stringify(values)});
      form.elements.api_key.value='';state.providers=state.providers.map(current=>current.provider===provider?item:current);state.tested.delete(provider);renderCards();renderDialog(item);feedback('Configuração salva. Teste a conexão para conferir a chave e o modelo.');toast('Integração de IA salva.');
    } catch(error){feedback(error.message,true);}
    finally {setBusy(false);}
  });
  body.addEventListener('click',async event=>{
    if(event.target.closest('[data-ai-cancel]')){close();return;}
    if(event.target.closest('[data-ai-show-models]')){const input=body.querySelector('[name=model]');input.focus();showModels(true);return;}
    const option=event.target.closest('[data-ai-model]');if(option){chooseModel(Number(option.dataset.aiModel));return;}
    const button=event.target.closest('[data-ai-action]');if(!button || state.busy)return;
    const provider=dialog.dataset.provider,action=button.dataset.aiAction;closeModels();setBusy(true);feedback('Consultando o provedor…');
    try {
      const result=await api('/api/integrations/ai/'+provider+'/'+action,action==='models'?{}:{method:'POST',body:'{}'});
      if(action==='remove'){state.tested.delete(provider);await load();renderDialog(find(provider));feedback('Chave removida deste workspace.');}
      else if(action==='models'){state.models.set(provider,result.models);feedback(`${result.models.length} modelos disponíveis. Busque um modelo no campo acima e salve sua escolha.`);}
      else{state.tested.add(provider);renderCards();feedback(result.message);}
    } catch(error){feedback(error.message,true);}
    finally {setBusy(false);}
  });
  load().catch(error=>{root.textContent=error.message;toast(error.message,true);});
})();
