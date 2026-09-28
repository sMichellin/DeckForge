# layout-fitting

## ADDED Requirements

### Requirement: Вписывание слайда без примера меряет каждую схему
`fit_slide` SHALL принимать `by_example: bool = False` (только по имени). При `True` на слайде
без рецепта (`recipe_id is None`) составной компонент любого паттерна из `NATIVE_PATTERNS` SHALL вписываться по своей раскладке (`diagram_geometry` строит
`hierarchy` и `pyramid` наравне с `process`, `cycle`, `timeline`, `matrix`), а не пропускаться
в расчёте, что писатель заменит его списком. При `False` поведение SHALL оставаться прежним:
паттерн вне `SUPPORTED_PATTERNS` не вписывается.

#### Scenario: Иерархия на пути by_example
- **WHEN** слайд с SmartArt `hierarchy` вписывается с `by_example=True`
- **THEN** у блока есть запись в `fit_report`

#### Scenario: Прежний путь
- **WHEN** тот же слайд вписывается без параметра
- **THEN** записи о блоке в `fit_report` нет, как до change
