"""Native client-tool protocols, normalized without persisting reasoning content."""
import json
from leadfinder.ai.catalog import AIError,provider_spec


class AgentProvider:
    def __init__(self,providers):
        self.providers=providers

    def step(self,provider,key,model,history,prompt,tools,workspace=''):
        spec=provider_spec(provider)
        if provider=='openai':
            path='/responses'
            payload={'model':model,'instructions':prompt,'input':history,'store':False,'max_output_tokens':6000,
                     'tools':[{'type':'function',**tool,'strict':True} for tool in tools],
                     'parallel_tool_calls':False,'include':['reasoning.encrypted_content']}
            if model.startswith(('gpt-6','gpt-5','o3','o4')):
                payload['reasoning']={'effort':'low'}
        elif provider=='claude':
            path='/messages'
            payload={'model':model,'system':prompt,'messages':history,'max_tokens':6000,
                     'tools':[{'name':tool['name'],'description':tool['description'],'input_schema':tool['parameters']} for tool in tools]}
        else:
            path='/chat/completions'
            payload={'model':model,'messages':[{'role':'system','content':prompt},*history],'max_tokens':6000,
                     'tools':[{'type':'function','function':tool} for tool in tools]}
        result=self.providers.transport.request('POST',spec['base']+path,self.providers.headers(provider,key,workspace),payload)
        try:
            calls=[]
            if provider=='openai':
                if result.get('status') not in (None,'completed'):
                    raise AIError('O modelo não concluiu a etapa. Confira as ações registradas antes de repetir.')
                output=result.get('output',[])
                text='\n'.join(part['text'] for item in output if item.get('type')=='message'
                               for part in item.get('content',[]) if part.get('type')=='output_text')
                calls=[{'id':item['call_id'],'name':item['name'],'arguments':json.loads(item['arguments'])} for item in output if item.get('type')=='function_call']
                history.extend(output)  # Includes encrypted reasoning required by stateless Responses.
            elif provider=='claude':
                if result.get('stop_reason') in ('max_tokens','refusal'):
                    raise AIError('O modelo interrompeu a etapa. Confira as ações e reformule o pedido.')
                content=result.get('content',[])
                text='\n'.join(item['text'] for item in content if item.get('type')=='text')
                calls=[{'id':item['id'],'name':item['name'],'arguments':item['input']} for item in content if item.get('type')=='tool_use']
                history.append({'role':'assistant','content':content})
            else:
                choice=result['choices'][0]
                if choice.get('finish_reason') in ('length','error','content_filter'):
                    raise AIError('O modelo interrompeu a etapa. Confira as ações antes de continuar.')
                message=choice['message'];text=message.get('content') or ''
                calls=[{'id':item['id'],'name':item['function']['name'],'arguments':json.loads(item['function']['arguments'])} for item in message.get('tool_calls',[])]
                history.append({'role':'assistant','content':message.get('content'),**({'tool_calls':message['tool_calls']} if message.get('tool_calls') else {})})
            if not isinstance(text,str) or len(text)>40000 or len(calls)>4 or len({call['id'] for call in calls})!=len(calls):
                raise AIError('A etapa retornou conteúdo ou chamadas acima do limite permitido.')
            if any(not isinstance(call['id'],str) or len(call['id'])>200 or not isinstance(call['name'],str) or not isinstance(call['arguments'],dict) for call in calls):
                raise AIError('O modelo retornou uma ferramenta com formato inválido.')
            if not calls and not text.strip():
                raise AIError('O modelo não retornou uma resposta nem uma ação válida.')
            usage={k:v for k,v in result.get('usage',{}).items() if k in ('input_tokens','output_tokens','prompt_tokens','completion_tokens','total_tokens') and type(v) is int}
            return text,calls,usage
        except (KeyError,TypeError,IndexError,ValueError,AttributeError):
            raise AIError('Não foi possível interpretar a resposta de ferramentas deste modelo. Nada foi repetido automaticamente.') from None

    @staticmethod
    def results(provider,history,outputs):
        def encoded(result):
            raw=json.dumps(result,ensure_ascii=False)
            return raw if len(raw)<=12000 else json.dumps({'truncated':True,'excerpt':raw[:11000]},ensure_ascii=False)
        if provider=='openai':
            history.extend({'type':'function_call_output','call_id':call['id'],'output':encoded(result)} for call,result in outputs)
        elif provider=='claude':
            history.append({'role':'user','content':[{'type':'tool_result','tool_use_id':call['id'],'content':encoded(result)} for call,result in outputs]})
        else:
            history.extend({'role':'tool','tool_call_id':call['id'],'content':encoded(result)} for call,result in outputs)
