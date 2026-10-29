# Contribuir com o LeadFinder

Use Python 3.11+, instale o projeto conforme o README e rode `python -m unittest discover -s tests -v` antes de enviar alterações.

- Mantenha a separação entre descoberta, contas/workspaces, modelos, execução dos disparos e o adaptador de WhatsApp.
- Separe HTTP, domínio/orquestração, persistência e navegação. Mudanças no DOM do Maps pertencem ao adaptador de coleta.
- Preserve os dados existentes quando um campo não puder ser lido. Não invente informações ausentes.
- Adicione testes de comportamento para parsing, persistência e alterações na coleta. Não faça chamadas reais ao Maps nos testes unitários.
- Descreva o problema, a mudança de comportamento e o que foi validado no pull request. Para mudanças na interface, inclua capturas em desktop e mobile.
- Não envie bancos de leads, perfis de navegador, tokens ou dados pessoais para o repositório.

O esquema v8 migra bases anteriores em `migrations.py`, com backup e transação. Mudanças de esquema devem incluir migração, teste com dados existentes e verificação de isolamento por workspace. Testes automatizados de mensagens usam um provedor fictício: nunca envie mensagens reais nos testes. Preserve snapshots, idempotência de início e resultados incertos sem reenvio automático.

Integrações de IA separam transporte, credenciais e orquestração em `leadfinder/ai/`. Testes usam transporte injetado: não faça gerações pagas nos testes e nunca grave chaves reais em fixtures, capturas ou logs. Confira `python -m unittest tests.test_ai` e `python -m tests.browser_ai` para mudanças nessa área.
