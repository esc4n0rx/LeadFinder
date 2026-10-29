"""Official model suggestions checked on 2026-10-28; live catalogs can refresh them."""

PROVIDERS = {
    'openai': {'name':'OpenAI · ChatGPT','default':'gpt-6.1-terra',
        'models':['gpt-6.1-terra','gpt-6.1-sol','gpt-6-astra','gpt-6-luna'],
        'base':'https://api.openai.com/v1','keys_url':'https://platform.openai.com/api-keys',
        'docs_url':'https://developers.openai.com/api/docs/models'},
    'openrouter': {'name':'OpenRouter','default':'openai/gpt-6.1-terra',
        'models':['openai/gpt-6.1-terra','anthropic/claude-sonnet-5.5'],
        'base':'https://openrouter.ai/api/v1','keys_url':'https://openrouter.ai/settings/keys',
        'docs_url':'https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties'},
    'claude': {'name':'Anthropic · Claude','default':'claude-sonnet-5-5',
        'models':['claude-sonnet-5-5','claude-haiku-5-5','claude-opus-5-5','claude-fable-5-1'],
        'base':'https://api.anthropic.com/v1','keys_url':'https://platform.claude.com/settings/keys',
        'docs_url':'https://platform.claude.com/docs/en/models/overview'},
}


class AIError(ValueError):
    pass


def provider_spec(provider):
    if not isinstance(provider,str) or provider not in PROVIDERS:
        raise AIError('Provedor de IA não reconhecido.')
    return PROVIDERS[provider]
