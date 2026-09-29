# inference

## ADDED Requirements

### Requirement: Роли локального llama.cpp не размышляют
Каждая роль реестра `configs/models.local.yaml`, идущая на локальный сервер (`endpoint_ref: vlm`),
SHALL объявлять `disable_thinking: true`: размышление расходует бюджет токенов раньше ответа,
и разметка макетов уходит в эвристику.

#### Scenario: Разметка макетов судьёй
- **WHEN** `vlm_judge` размечает макет шаблона на локальном сервере
- **THEN** запрос уходит с `chat_template_kwargs.enable_thinking=false`

#### Scenario: Новая роль на локальном сервере
- **WHEN** в реестр добавлена роль с `endpoint_ref: vlm` без `disable_thinking`
- **THEN** тест `test_every_local_llama_role_has_thinking_off` красный
