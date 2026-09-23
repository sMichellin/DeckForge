window.STATE =
{
  "slug": "slide-recipes",
  "dir": "2026-09-23-slide-recipes--wip",
  "title": "Слайды по рецептам шаблона: слайды-примеры вместо белого макета",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T2",
  "briefFile": "2026-09-23-brief.md",
  "memoryFile": "AGENTS.md",
  "skillDir": "/c/Users/gulin/.claude/skills/autopilot",
  "startedAt": "2026-09-23T17:09:26+03:00",
  "updatedAt": "2026-09-23T17:26:19+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-09-23T17:09:26+03:00",
      "finishedAt": "2026-09-23T17:10:19+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-09-23T17:10:19+03:00",
      "finishedAt": "2026-09-23T17:10:19+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-09-23T17:10:19+03:00",
      "finishedAt": "2026-09-23T17:12:37+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-09-23T17:12:37+03:00",
      "finishedAt": "2026-09-23T17:15:39+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-09-23T17:15:39+03:00",
      "finishedAt": "2026-09-23T17:17:28+03:00",
      "note": "6 тасков, ярус T2, 5 волн; 02–06 ждут тимлида"
    },
    {
      "id": "build",
      "status": "active",
      "startedAt": "2026-09-23T17:17:28+03:00",
      "note": "1 из 6 — предложение готово; 02–06 ждут «ок» тимлида"
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
    "total": 23,
    "done": 2,
    "inTicket": 21,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "OpenSpec-предложение для тимлида",
      "requirements": [
        "R21i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "openspec/changes/slide-recipes/"
      ],
      "status": "done",
      "retries": 0,
      "repairs": 1,
      "handoffs": 0,
      "startedAt": "2026-09-23T17:17:28+03:00",
      "repairFindings": [
        "ссылка tasks-design-system.md:45–47 → 47–49",
        "один change на две capability — разбить по волнам (AGENTS.md п.3)"
      ],
      "finishedAt": "2026-09-23T17:26:19+03:00",
      "files": [
        "openspec/changes/slide-recipes/proposal.md"
      ],
      "tests": null,
      "commit": "pending"
    },
    {
      "id": "02",
      "title": "Контракт: поля домена и парсер",
      "requirements": [
        "R13",
        "R14",
        "R18i",
        "R19i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "src/deckforge/domain/",
        "schemas/",
        "src/deckforge/parsing/ooxml/examples.py"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "note": "ждёт «ок» тимлида по предложению"
    },
    {
      "id": "03",
      "title": "Каталог рецептов в дизайн-системе и на её странице",
      "requirements": [
        "R03",
        "R04",
        "R05",
        "R06",
        "R09",
        "R10",
        "R11",
        "R18i",
        "R20i"
      ],
      "blockedBy": [
        "02"
      ],
      "wave": 3,
      "zone": [
        "src/deckforge/designsystem/",
        "src/deckforge/export/design_system_page.py"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "note": "ждёт «ок» тимлида по предложению"
    },
    {
      "id": "04",
      "title": "Writer: копия примера с нашим текстом",
      "requirements": [
        "R01",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R13",
        "R14",
        "R16i",
        "R23i"
      ],
      "blockedBy": [
        "03"
      ],
      "wave": 4,
      "zone": [
        "src/deckforge/rendering/"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "note": "ждёт «ок» тимлида по предложению"
    },
    {
      "id": "05",
      "title": "План и композиция по рецептам",
      "requirements": [
        "R02",
        "R12",
        "R14",
        "R17i",
        "R19i",
        "R20i"
      ],
      "blockedBy": [
        "03"
      ],
      "wave": 4,
      "zone": [
        "src/deckforge/planning/",
        "src/deckforge/composition/",
        "prompts/deck_planner/",
        "prompts/slide_composer/"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "note": "ждёт «ок» тимлида по предложению"
    },
    {
      "id": "06",
      "title": "Конвейер, аудит и живой замер",
      "requirements": [
        "R01",
        "R02",
        "R14",
        "R17i",
        "R22i",
        "R23i"
      ],
      "blockedBy": [
        "04",
        "05"
      ],
      "wave": 5,
      "zone": [
        "src/deckforge/pipeline/",
        "src/deckforge/audit/",
        "scripts/run_metrics.py"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "note": "ждёт «ок» тимлида по предложению"
    }
  ],
  "singlePass": null,
  "tests": null,
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "findings": 13,
    "missing": 3,
    "half": 8,
    "extra": 14,
    "actions": "репозиторий вписан (Реш.§0); «план выбирает рецепт» — план выбирает вид из меню ДС, пример — счёт (Реш.§4); структурные слайды получают рецепты (Ист.7а); пороги, повторы, содержательный слайд, превью, формат id — определены (Реш.§2,§4); «брейншторм» снят дополнением «давай а»; лишнее — углубления R##.n (normal), путь Б — Вне рамок"
  },
  "concerns": [
    "после «ок» тимлида перенарезать таски 03/05/06 на 03a/03b, 05a/05b, 06a/06b — как в зонтичном предложении"
  ],
  "reviewers": {
    "manifestSpec": "a4947f08ddc4ea4ea",
    "craft": null
  },
  "blind": null
}
