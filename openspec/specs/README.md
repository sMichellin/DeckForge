# Живые спецификации

Источник истины по требованиям. Каждая capability — папка со `spec.md`.
Наполняются по мере прохождения changes через `/opsx:archive`.

Формат — обычный Markdown с требованиями и сценариями:

```markdown
## ADDED Requirements

### Requirement: Извлечение цветовой палитры темы
Парсер SHALL извлекать все 12 цветов схемы из ppt/theme/theme1.xml
и сохранять их в TemplateManifest.theme.colors.

#### Scenario: Шаблон с нестандартными именами цветов
- **WHEN** в theme1.xml цвета заданы через srgbClr внутри clrScheme
- **THEN** манифест содержит 12 записей с ключами dk1…folHlink
- **AND** ни один ключ не пустой
```
