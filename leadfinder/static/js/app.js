'use strict';

const $ = (selector) => document.querySelector(selector);
const token = $('meta[name="leadfinder-token"]').content;
const state = { page: 1, query: '', searchId: '', onlyPhone: true, baseTotal: 0, active: null, searches: [], view: 'catalog', listRequest: 0, pollTimer: null, overviewBusy: false, connectionError: false };
const labels = {queued: 'Na fila', running: 'Coletando', completed: 'Concluída', partial: 'Parcial', failed: 'Falhou', cancelled: 'Interrompida', interrupted: 'Interrompida'};
const activeStatus = (search) => search && ['queued', 'running'].includes(search.status);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const format = (value) => new Intl.NumberFormat('pt-BR').format(value ?? 0);
const date = (value) => new Intl.DateTimeFormat('pt-BR', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'}).format(new Date(value));
const initials = (name) => name.split(/\s+/).slice(0,2).map(part => part[0]).join('').toUpperCase();
const icon = (name) => `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><use href="#icon-${name}"></use></svg>`;

function safeUrl(value) {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}
function domain(value) { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return ''; } }
function link(value, label, className = '') {
  const url = safeUrl(value);
  return url ? `<a class="${className}" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(label)}</a>` : escape(label);
}
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'Content-Type':'application/json','X-LeadFinder-Token':token,...options.headers}});
  const data = await response.json();
  if (data.redirect && [401,403].includes(response.status)) window.location.assign(data.redirect);
  if (!response.ok) throw new Error(data.error || 'Não foi possível concluir a solicitação.');
  return data;
}
function toast(message, error = false) {
  const node = document.createElement('div');
  node.className = `toast${error ? ' error' : ''}`;
  node.textContent = message;
  $('#toast-region').append(node);
  setTimeout(() => node.remove(), error ? 9000 : 5500);
}

async function refreshOverview() {
  if (state.overviewBusy) return;
  state.overviewBusy = true;
  try {
    const data = await api('/api/overview');
    state.searches = data.searches;
    state.baseTotal = data.stats.total;
    $('#stat-total').textContent = format(data.stats.total);
    $('#stat-phone').textContent = format(data.stats.with_phone);
    $('#stat-website').textContent = format(data.stats.with_website);
    $('#nav-count').textContent = format(data.stats.total);
    const previous = state.active;
    const running = state.searches.find(activeStatus);
    state.active = running || null;
    if (previous && !running) {
      const finished = state.searches.find(search => search.id === previous.id);
      if (finished) {toast(finished.message, finished.status === 'failed');if(finished.saved && state.view==='catalog')openSearchLeads(finished.id);}
    }
    renderProgress();
    renderHistory();
    document.dispatchEvent(new CustomEvent('leadfinder:overview',{detail:data}));
    state.connectionError = false;
    if (running || previous) {

      document.dispatchEvent(new CustomEvent('leadfinder:leads-updated'));
    }
  } catch (error) {
    if (!state.connectionError) toast('A conexão com a base local foi interrompida. Tentando reconectar…', true);
    state.connectionError = true;
  } finally {
    state.overviewBusy = false;
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(refreshOverview, state.active ? 1600 : 6000);
  }
}
function renderProgress() {
  const search = state.active;
  $('#progress-panel').hidden = !search;
  $('#search-button').disabled = Boolean(search);
  if (!search) return;
  $('#progress-term').textContent = `${search.term}${search.location ? ' · ' + search.location : ''}`;
  $('#progress-message').textContent = search.message;
  $('#progress-count').textContent = `${format(search.found)} encontrados · ${format(search.processed)} processados`;
  $('#progress-saved').textContent = `${format(search.saved)} catalogados · ${format(search.skipped_phone)} telefone não encontrado · ${format(search.skipped_distance)} fora do raio · ${format(search.skipped_coordinates)} sem coordenadas`;
  const progress = $('#progress-bar');
  if (search.found && search.processed) { progress.value = Math.min(100, search.processed / search.found * 100); } else { progress.removeAttribute('value'); }
  $('#cancel-button').disabled = Boolean(search.cancel_requested);
  $('#cancel-button').textContent = search.cancel_requested ? 'Interrompendo…' : 'Interromper';
}
function renderHistory() {
  $('#history-list').innerHTML = state.searches.length ? state.searches.map(s => `<article class="history-row"><div class="history-icon">${icon('search')}</div><div class="history-info"><strong>${escape(s.term)}${s.postcode ? ` · CEP ${escape(s.postcode)} · ${escape(s.radius_km)} km` : s.location ? ' · ' + escape(s.location) : ''}</strong><p>${escape(s.message)}</p><p>${s.require_phone ? 'Somente com telefone · ' : ''}${format(s.skipped_phone)} sem telefone · ${format(s.skipped_distance)} fora do raio · ${format(s.skipped_coordinates)} sem coordenadas</p></div><div class="history-meta">${date(s.created_at)}<small>${format(s.saved)} catalogados · máximo ${s.max_results}</small></div><span class="status-badge ${escape(s.status)}">${escape(labels[s.status] || s.status)}</span><button class="history-open" data-search="${s.id}">Ver leads ↗</button></article>`).join('') : '<div class="history-empty">Suas buscas aparecerão aqui quando você fizer a primeira descoberta.</div>';
}
function switchView(view) {
  state.view = view;
  if ($('#settings-view')) $('#settings-view').hidden = !['profile','integrations','ai'].includes(view);
  $('.account-menu').classList.toggle('settings-active', ['profile','integrations','ai'].includes(view));
  $('#agents-view').hidden = view !== 'agents';
  $('#history-view').hidden = view !== 'history';
  $('#messages-view').hidden = view !== 'messages';
  $('#automation-view').hidden = view !== 'automation';
  $('#directory-view').hidden = view !== 'leads';
  for (const section of ['pipeline','tasks','workspace']) $('#'+section+'-view').hidden=view!==section;
  $('.workspace-top').hidden = view !== 'catalog';
  $('#page-title').textContent = {catalog:'Estabelecimentos',agents:'Agentes',leads:'Leads',pipeline:'Funil comercial',tasks:'Lembretes',workspace:'Workspace',history:'Histórico de buscas',messages:'Mensagens',automation:'Automação',profile:'Meu perfil',integrations:'Integrações',ai:'Inteligência artificial'}[view] || 'Estabelecimentos';
  document.body.dataset.view=view;
  history.replaceState(null,'',{catalog:'/',agents:'/agents',leads:'/leads',pipeline:'/pipeline',tasks:'/tasks',workspace:'/workspace',history:'/history',messages:'/messages',automation:'/automation',profile:'/profile',integrations:'/profile/integrations',ai:'/profile/integrations/ai'}[view] || '/');
  document.dispatchEvent(new CustomEvent('leadfinder:view',{detail:view}));
  document.title = `LeadFinder — ${$('#page-title').textContent}`;
  document.querySelectorAll('.nav-item[data-view]').forEach(button => { button.classList.toggle('active',button.dataset.view === view); button.setAttribute('aria-current', button.dataset.view === view ? 'page' : 'false'); });
}

function showLead(id){return window.LeadCRM.openDossier(id);}
$('#search-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('#search-button').disabled = true;
  if ($('#postcode').value.trim()) toast('Confirmando a localização do CEP e preparando a busca…');
  try {
    const search = await api('/api/searches', {method:'POST',body:JSON.stringify({term:$('#term').value.trim(),location:$('#location').value.trim(),max_results:Number($('#limit').value),postcode:$('#postcode').value.trim(),radius_km:Number($('#radius').value),require_phone:$('#require-phone').checked,category_id:$('#discovery-category').value?Number($('#discovery-category').value):null})});
    state.active = search;
    state.page = 1;
    state.searchId = '';

    switchView('catalog');
    renderProgress();
    toast('Busca iniciada. Seus leads aparecerão durante a coleta.');
    await refreshOverview();
  } catch (error) { toast(error.message,true); $('#search-button').disabled = Boolean(state.active); }
});
$('#cancel-button').addEventListener('click', async () => {
  if (!state.active) return;
  $('#cancel-button').disabled = true;
  try { await api(`/api/searches/${state.active.id}/cancel`, {method:'POST',body:'{}'}); await refreshOverview(); }
  catch (error) { toast(error.message,true); $('#cancel-button').disabled = false; }
});
let postcodeRequest = 0;
$('#postcode').addEventListener('input', () => {
  postcodeRequest++;
  $('#postcode-preview').hidden = true;
  $('#location').disabled = Boolean($('#postcode').value.trim());
});
$('#resolve-postcode').addEventListener('click', async () => {
  const id = ++postcodeRequest;
  const code = $('#postcode').value.trim();
  if (!/^\d{5}-?\d{3}$/.test(code)) { toast('Informe um CEP com 8 dígitos.', true); $('#postcode').focus(); return; }
  $('#resolve-postcode').disabled = true;
  $('#resolve-postcode').textContent = 'Localizando…';
  try {
    const area = await api('/api/postcodes/' + encodeURIComponent(code));
    if (id !== postcodeRequest) return;
    $('#postcode-preview').textContent = `${area.address} · Referência aproximada: ${area.latitude.toFixed(5)}, ${area.longitude.toFixed(5)}.`;
    $('#postcode-preview').hidden = false;
  } catch (error) { toast(error.message, true); }
  finally { $('#resolve-postcode').disabled = false; $('#resolve-postcode').textContent = 'Confirmar CEP'; }
});
function openSearchLeads(id){switchView('leads');document.dispatchEvent(new CustomEvent('leadfinder:directory-search',{detail:id}));}
$('#history-list').addEventListener('click',event=>{const button=event.target.closest('[data-search]');if(button)openSearchLeads(button.dataset.search);});
document.querySelectorAll('.nav-item[data-view]').forEach(button => {const name=button.querySelector('span')?.textContent;if(name){button.setAttribute('aria-label',name);button.title=name;}button.addEventListener('click', () => switchView(button.dataset.view));});
function focusSearch() {
  switchView('catalog');
  $('#term').focus({preventScroll:true});
  $('#term').scrollIntoView({block:'center',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
}
function focusCatalog(){switchView('leads');$('#directory-query').focus({preventScroll:true});}
$('#new-search').addEventListener('click', focusSearch);
$('#quick-search').addEventListener('click', focusCatalog);
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) {
    event.preventDefault();
    focusCatalog();
  }
});
$('#close-dialog').addEventListener('click', () => $('#lead-dialog').close());
$('#lead-dialog').addEventListener('click', event => { if (event.target === $('#lead-dialog')) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });
window.LeadFinder = {api,toast,escape,icon,refreshOverview};
switchView(document.body.dataset.initialView || 'catalog');
refreshOverview();
