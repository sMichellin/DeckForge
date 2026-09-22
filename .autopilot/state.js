window.STATE =
{
  "slug": "design-system-page",
  "dir": "2026-09-22-design-system-page--wip",
  "title": "Страница «Дизайн-система шаблона» из манифеста",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-09-22-brief.md",
  "memoryFile": "AGENTS.md",
  "skillDir": "/c/Users/gulin/.claude/skills/autopilot",
  "startedAt": "2026-09-22T11:45:06+03:00",
  "updatedAt": "2026-09-22T15:54:09+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-09-22T11:45:06+03:00",
      "finishedAt": "2026-09-22T11:46:32+03:00"
    },
    {
      "id": "manifest",
      "status": "active",
      "startedAt": "2026-09-22T11:46:32+03:00"
    },
    {
      "id": "briefing",
      "status": "pending"
    },
    {
      "id": "spec",
      "status": "pending"
    },
    {
      "id": "plan",
      "status": "pending"
    },
    {
      "id": "build",
      "status": "pending"
    },
    {
      "id": "review",
      "status": "pending"
    },
    {
      "id": "final",
      "status": "pending"
    }
  ],
  "requirements": {
    "total": 26,
    "done": 29,
    "inTicket": 0,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Слой designsystem и структура дизайн-системы",
      "requirements": [
        "R02",
        "R06",
        "R14",
        "R17",
        "R19",
        "R20i",
        "R22i",
        "G01"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "openspec/changes/design-system-page/",
        "src/deckforge/designsystem/"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-09-22T12:03:39+03:00",
      "finishedAt": "2026-09-22T15:16:49+03:00",
      "tests": "1421 passed",
      "commit": "2249cb3"
    },
    {
      "id": "02",
      "title": "Измеренное: роли цветов, доли, сочетания, контрасты",
      "requirements": [
        "R03",
        "R04",
        "R05",
        "R06",
        "R10",
        "R12",
        "R25",
        "R26",
        "R27"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "src/deckforge/designsystem/measure.py"
      ],
      "status": "done",
      "retries": 2,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-09-22T14:55:29+03:00",
      "commit": "7d5ec42",
      "finishedAt": "2026-09-22T15:32:37+03:00",
      "tests": "1445 passed, 21 skipped"
    },
    {
      "id": "03",
      "title": "Достроенное: плашки, списки, элементы слайда, правила",
      "requirements": [
        "R08",
        "R09",
        "R11",
        "R12",
        "R13",
        "R16",
        "R17",
        "R28",
        "R29"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "src/deckforge/designsystem/synth.py"
      ],
      "status": "done",
      "retries": 2,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-09-22T14:55:29+03:00",
      "commit": "aa3441d",
      "finishedAt": "2026-09-22T15:20:25+03:00",
      "tests": "1421 passed, 21 skipped"
    },
    {
      "id": "04",
      "title": "Страница: семь разделов, живые примеры, анатомия",
      "requirements": [
        "R02",
        "R07",
        "R15",
        "R17",
        "R19",
        "R20i",
        "G01",
        "G02"
      ],
      "blockedBy": [
        "02",
        "03"
      ],
      "wave": 3,
      "zone": [
        "src/deckforge/export/design_system_page.py"
      ],
      "status": "review",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-09-22T15:32:37+03:00",
      "tests": "1456 passed, 21 skipped"
    },
    {
      "id": "05",
      "title": "Команда design-system и прогон на шаблонах",
      "requirements": [
        "R01",
        "R18",
        "R21i",
        "R22i"
      ],
      "blockedBy": [
        "04"
      ],
      "wave": 4,
      "zone": [
        "src/deckforge/cli.py",
        "artifacts/design-system/"
      ],
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-09-22T15:54:09+03:00"
    }
  ],
  "singlePass": null,
  "tests": "1456 passed, 21 skipped",
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "findings": 12,
    "missing": 9,
    "written": 8,
    "deferredByDesign": 1,
    "halfCovered": 3,
    "note": "гейт G2 нашёл 8 потерянных кусков образца — дописаны в спецификацию строками R25–R29 и уточнениями историй"
  },
  "concerns": [
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/models.py:60",
      "what": "SpacingScale.base_source — свободная строка, набор значений в описании не совпадает с выдаваемым derive; метку читает таск 04",
      "kind": "craft"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/models.py:236",
      "what": "SynthElement: у плашки три цветовые роли, полей два — таск 03 запишет одно, таск 04 прочитает другое",
      "kind": "craft",
      "watch": "проверить на возврате таска 03"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/models.py:242",
      "what": "SynthElement.group/.kind — свободные строки вместо перечисления; словарь разделов изобретает таск 03, а группирует по нему таск 04",
      "kind": "craft",
      "watch": "проверить на возврате таска 03"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/models.py:124",
      "what": "ThemeSlot.color_hex — литеральный паттерн вместо импортированного HEX_COLOR",
      "kind": "craft"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/derive.py:54",
      "what": "_font_family аннотирован str при фактическом FontRef, из-за чего стоит type: ignore",
      "kind": "craft"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/derive.py:84",
      "what": "astuple_margins — единственный помощник без подчёркивания, лишняя публичная поверхность слоя",
      "kind": "craft"
    },
    {
      "ticket": "01",
      "file": "tests/unit/designsystem/test_derive.py:248",
      "what": "проверка на холодных шаблонах пропускается: корпус пуст на этой машине, хотя файлы лежат в архив/slidewright",
      "kind": "craft",
      "watch": "закрыть в таске 05 прогоном на холодном"
    },
    {
      "ticket": "01",
      "file": "tests/unit/designsystem/test_derive.py:105",
      "what": "ветка guides_source == inferred (признак сетки DERIVED) не проверена утверждением",
      "kind": "craft"
    },
    {
      "ticket": "01",
      "file": "src/deckforge/designsystem/models.py:144",
      "what": "ревью сочло литеральные #RRGGBB в PaletteRole/Combination/ContrastPair нарушением — не находка: это цвета слайдов-примеров, которых в теме нет, и они попадают в :root страницы, а не в код",
      "kind": "spec",
      "verdict": "отклонено оркестратором"
    },
    {
      "ticket": "03",
      "file": "src/deckforge/designsystem/synth.py:118,236",
      "what": "роль сравнивается строкой role.role.value == 'background', а не ColorRoleKind.BACKGROUND — переименование значения молча уронит фон в запасные слоты",
      "kind": "craft"
    },
    {
      "ticket": "03",
      "file": "src/deckforge/designsystem/synth.py:549",
      "what": "STEP_SOURCE.get(..., 'grid.margins_emu') — незнакомый base_source даёт правилу ложный источник числа; неизвестный источник должен убирать правило, а не подставлять правдоподобное поле",
      "kind": "craft"
    },
    {
      "ticket": "03",
      "file": "src/deckforge/designsystem/synth.py:554",
      "what": "widest выбирает компонент по числу слайдов, а не по ширине — имя врёт",
      "kind": "craft"
    },
    {
      "ticket": "02+03",
      "file": "synth.py:34 и measure.py:66",
      "what": "два списка акцентных слотов в одном слое расходятся составом (в measure добавлены hlink/folHlink) — один перечень должен жить в одном месте",
      "kind": "craft"
    },
    {
      "ticket": "02",
      "file": "src/deckforge/designsystem/measure.py",
      "what": "COMBINATIONS_SHOWN = 8 выбран исполнителем; на 10 и 12 хвост уменьшается на 3–7 пунктов, длина раздела растёт",
      "kind": "craft"
    }
  ],
  "reviewers": {
    "manifestSpec": "reviewer-manifest",
    "craft": "reviewer-craft"
  },
  "blind": null
}
