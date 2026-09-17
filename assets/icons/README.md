# Иконки

`lucide/icon-nodes.json` — элементы SVG всех иконок Lucide из пакета
[`lucide-static@1.46.0`](https://www.npmjs.com/package/lucide-static/v/1.46.0), без изменений.
Лицензия — `lucide/LICENSE` (ISC; часть иконок, унаследованных от Feather, — MIT).

Читает `deckforge.rendering.icons`: pptx получает иконку нативной фигурой (`a:custGeom`),
html — встроенным SVG. Имя в `IconBlock.query` — имя иконки Lucide (`shield-check`;
`ShieldCheck` и `shield_check` тоже находятся).

Обновление: заменить файл на `icon-nodes.json` новой версии пакета и прогнать
`tests/unit/test_rendering_icons.py` — тест переводит в сегменты каждую иконку.
