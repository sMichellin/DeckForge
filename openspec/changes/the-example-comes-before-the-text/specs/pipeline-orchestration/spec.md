# pipeline-orchestration

## ADDED Requirements

### Requirement: Путь сборки слайда задаётся конфигом
Конфиг прогона SHALL задавать путь сборки слайда `composition.path` одним из двух значений:
`legacy` (текст пишется до выбора примера) или `by_example` (пример выбирается до текста,
ADR-009). Без раздела `composition` путь SHALL быть `legacy`. Любое другое значение SHALL
быть ошибкой загрузки конфига.

#### Scenario: Раздела нет
- **WHEN** в конфиге прогона нет раздела `composition`
- **THEN** путь сборки — `legacy`

#### Scenario: Профиль переопределяет путь
- **WHEN** профиль прогона задаёт `composition.path: by_example`
- **THEN** путь сборки — `by_example`

#### Scenario: Опечатка в пути
- **WHEN** конфиг задаёт путь, которого нет среди `legacy` и `by_example`
- **THEN** загрузка конфига падает с ошибкой

### Requirement: Новый путь без своего узла не подменяется старым
Пока в графе нет узла `assign`, прогон с путём `by_example` SHALL отказывать при старте
с названием причины, а не собирать колоду путём `legacy`.

#### Scenario: Путь by_example до узла assign
- **WHEN** прогон запущен с `composition.path: by_example`
- **THEN** прогон не стартует, ошибка называет недостающий узел `assign`

### Requirement: Отчёт прогона называет путь сборки
Отчёт прогона `run.json` SHALL содержать поле `composition_path` — путь, которым собрана
колода.

#### Scenario: Путь в отчёте
- **WHEN** колода собрана путём `legacy`
- **THEN** в `run.json` стоит `composition_path: legacy`
