/* Beautiful UI primitives adapted to vanilla JS for LeadFinder.
 * Copyright (c) 2026 Shane Levine — MIT.
 * Sources: LoadingState.tsx, ChatComposer.tsx, PromptBar.tsx,
 * RecommendationCard.tsx and Search at beautifului.dev/r/.
 * Full license: /static/licenses/beautiful-ui-LICENSE.txt
 */
(() => {
  'use strict';
  const escape=value=>String(value ?? '').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  function loading(label='Preparando resposta',elapsed=0) {
    const cells=Array.from({length:9},(_,index)=>`<span class="bui-pixel bui-pixel-${index}"></span>`).join('');
    return `<div class="bui-loading" role="status"><span class="bui-loader-grid" aria-hidden="true">${cells}</span><span>${escape(label)}</span><time data-ai-elapsed>${Math.max(0,Math.floor(elapsed))}s</time></div>`;
  }
  function richText(text) {
    const lines=String(text || '').split('\n'),parts=[];let paragraph=[],list=[],listType='';
    const inline=value=>escape(value).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
    const flushParagraph=()=>{if(paragraph.length){parts.push('<p>'+paragraph.map(inline).join('<br>')+'</p>');paragraph=[];}};
    const flushList=()=>{if(list.length){parts.push(`<${listType}>${list.map(line=>'<li>'+inline(line)+'</li>').join('')}</${listType}>`);list=[];listType='';}};
    for(const line of lines) {
      const ordered=line.match(/^\s*\d+[.)]\s+(.+)/),unordered=line.match(/^\s*[-•]\s+(.+)/);
      if(ordered || unordered){flushParagraph();const type=ordered?'ol':'ul';if(listType && listType!==type)flushList();listType=type;list.push((ordered || unordered)[1]);}
      else if(!line.trim()){flushParagraph();flushList();}else{flushList();paragraph.push(line);}
    }
    flushParagraph();flushList();return parts.join('');
  }
  function recommendation(draft,turn,index) {
    return `<section class="ai-suggestion bui-recommendation"><div class="ai-suggestion-heading"><span class="ai-draft-number">${index+1}</span><h4>${escape(draft.name)}</h4><span class="ai-draft-label">Rascunho</span></div><p>${escape(draft.body)}</p><div class="ai-suggestion-actions"><button type="button" class="primary-button" aria-label="Usar no editor" data-ai-use="${turn}" data-ai-index="${index}">Usar no editor ↗</button><button type="button" class="text-button" data-ai-copy="${turn}" data-ai-index="${index}">Copiar texto</button></div></section>`;
  }
  window.BeautifulUI={escape,loading,richText,recommendation};
})();
