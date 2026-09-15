# fix-xgrammar-version-conflict

Статус: proposed → applied

## Explore

CI (`poetry install --with dev`) падает на шаге «Resolving dependencies»,
хотя запрашивается только группа `dev`: группа `inference` не помечена
`optional`, поэтому poetry резолвит её в любом случае.

Конфликт: `vllm = "^0.29"` (0.29.0) требует `xgrammar >=0.2.1,<1.0.0`,
а зафиксировано `xgrammar = "^0.1"` (>=0.1,<0.2). Диапазоны не пересекаются.

Ссылка на упавший прогон:
https://github.com/sMichellin/slide_write_gen_vid/actions/runs/34967106473/job/104374068733

## Propose

Поднять нижние границы у зависимостей `vllm 0.29.0`, которые в pyproject.toml
зафиксированы на устаревших диапазонах, до того, что реально требует сам vllm
(сверено по `requires_dist` пакета `vllm==0.29.0` на PyPI):

```
xgrammar               = ">=0.2.1,<1.0.0"     # было ^0.1
transformers           = ">=5.10.4,<6.0"      # было ^4.50
fastapi                = ">=0.133.0,<0.137.0" # было ^0.124; vllm требует fastapi[standard]<0.137.0,>=0.133.0,
                                               # а fastapi 0.124.x капал starlette на <0.51.0, что конфликтует
                                               # с vllm'овским starlette>=1.0.1
opencv-python-headless = ">=4.13.0,<5.0"      # было ^4.11
```

Полная сверка `requires_dist` пакета `vllm==0.29.0` на PyPI против всех
наших прямых зависимостей (скриптом, не вручную) — пересекающихся имён
без конфликта: `torch==2.13.0` (укладывается в `^2.6`), `pydantic>=2.12.0`
(в `^2.13`), `openai>=2.0.0` (в `^2.0`), `numpy`/`pillow`/`pyyaml` (без
версийных требований от vllm), `pandas` (у vllm — только под extra
`bench`, который мы не запрашиваем).

Обоснование по правилу 8 AGENTS.md: это не новые зависимости, а починка
constraint'ов существующих — верхние границы не менялись.

## Apply

`pyproject.toml`: `xgrammar`, `transformers` в `[tool.poetry.group.inference.dependencies]`;
`fastapi`, `opencv-python-headless` в `[tool.poetry.dependencies]`.

## Apply (продолжение)

Настоящий корень проблемы — не версии сами по себе, а то, что группа
`inference` не была помечена `optional = true`: poetry резолвил и ставил
`vllm`/`torch`/`torchvision` (CUDA-колёса, многие ГБ) при **любом**
`poetry install`, даже с `--with dev`, где эта группа не нужна вовсе —
это прямо противоречит комментарию в `docker/Dockerfile` ("инференс сюда
не тащим — отдельным сервисом"). Из-за этого ранер GitHub Actions упёрся
в `OSError: [Errno 28] No space left on device` на установке torchvision.

Добавил `[tool.poetry.group.inference] optional = true` — теперь группа
ставится только по явному `--with inference` (как и задумано: CI и
`docker/Dockerfile` запрашивают только `dev`/`dev,ui`).

## Verify

CI job `poetry install --with dev` резолвит и завершается без ошибок
(проверяется в этом PR).

## Archive

Переносится в `openspec/changes/` архив после мержа и зелёного CI.
