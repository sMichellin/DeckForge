# Tasks — the-cold-check-is-red

## 1. Замер

- [x] 1.1 `Grey_Elegant.otp` → `.pptx` в `tests/fixtures/templates/cold/` (в `.gitignore`), падение `assert 0 > 0` воспроизведено
- [x] 1.2 `framed`/`kept` на трёх шаблонах кейса и на холодном — до правки
- [x] 1.3 каталог рецептов DNA, Focus, Piano, Portfolio — пуст

## 2. Данные теста

- [x] 2.1 `_text(capacity)`: слова фразы, пока влезают; иначе первые `capacity` знаков; вместимость ноль — фраза целиком
- [x] 2.2 докстринг модуля и комментарии — правдивы
- [x] 2.3 `kept > 0` и прежние ассерты — без изменений

## 3. Проверка

- [x] 3.1 `pytest -m "cold or slow" tests/integration/test_fit_recipe_deck.py` с холодным шаблоном — зелёный, вывод в PR
- [x] 3.2 `framed`/`kept` после — ни один не обнулился
- [x] 3.3 полный pytest, ruff, mypy, `scripts/lint_no_template_constants.py`, `openspec validate the-cold-check-is-red`

## 4. Вопрос владельцу

- [ ] 4.1 холодный шаблон в CI: класть ли `Grey_Elegant.pptx` в репозиторий (бинарь, лицензия)
