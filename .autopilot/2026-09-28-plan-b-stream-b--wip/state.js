window.STATE =
{
  "slug": "plan-b-stream-b",
  "dir": "2026-09-28-plan-b-stream-b--wip",
  "title": "План Б · поток B: удаление группами, дизайн-система на рецептных слайдах, слайд без примера (#244)",
  "mode": "semi",
  "depth": "normal",
  "polish": null,
  "tier": "T1",
  "briefFile": "2026-09-28-brief.md",
  "memoryFile": null,
  "skillDir": "C:/Users/gulin/.claude/skills/autopilot",
  "startedAt": "2026-09-28T19:48:43+03:00",
  "updatedAt": "2026-09-28T20:43:05+03:00",
  "finishedAt": null,
  "stages": [
    {
      "id": "preflight",
      "status": "done",
      "startedAt": "2026-09-28T19:48:43+03:00",
      "finishedAt": "2026-09-28T19:49:53+03:00"
    },
    {
      "id": "manifest",
      "status": "done",
      "startedAt": "2026-09-28T19:48:50+03:00",
      "finishedAt": "2026-09-28T19:49:53+03:00"
    },
    {
      "id": "briefing",
      "status": "done",
      "startedAt": "2026-09-28T19:49:53+03:00",
      "finishedAt": "2026-09-28T19:59:40+03:00"
    },
    {
      "id": "spec",
      "status": "done",
      "startedAt": "2026-09-28T19:59:40+03:00",
      "finishedAt": "2026-09-28T19:59:40+03:00"
    },
    {
      "id": "plan",
      "status": "done",
      "startedAt": "2026-09-28T19:59:40+03:00",
      "note": "3 таска, ярус T1",
      "finishedAt": "2026-09-28T20:01:44+03:00"
    },
    {
      "id": "build",
      "status": "active",
      "startedAt": "2026-09-28T20:01:44+03:00"
    },
    {
      "id": "review",
      "status": "active",
      "startedAt": "2026-09-28T20:40:08+03:00",
      "note": "ревью таска 01"
    },
    {
      "id": "final",
      "status": "pending"
    }
  ],
  "requirements": {
    "total": 30,
    "done": 0,
    "inTicket": 30,
    "inSpec": 0,
    "placeholder": 0,
    "deferred": 0,
    "dropped": 0
  },
  "tickets": [
    {
      "id": "01",
      "title": "Писатель удаляет незаполненное группами паспорта (change 4)",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R10",
        "R11",
        "R12",
        "R13",
        "R14",
        "R26",
        "R27",
        "R28",
        "R29i",
        "R30i"
      ],
      "blockedBy": [],
      "wave": 1,
      "zone": [
        "rendering/recipe_slide.py",
        "tests/unit/test_the_writer_removes_whole_groups.py",
        "openspec/changes/the-writer-removes-whole-groups/"
      ],
      "status": "review",
      "retries": 0,
      "repairs": 0,
      "handoffs": 1,
      "startedAt": "2026-09-28T20:02:05+03:00"
    },
    {
      "id": "02",
      "title": "Дизайн-система подгоняет рецептный слайд (change 5а)",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R06",
        "R07",
        "R15",
        "R16",
        "R17",
        "R18",
        "R19",
        "R20",
        "R21",
        "R26",
        "R27",
        "R29i",
        "R30i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "rendering/recipe_slide.py",
        "rendering/writer.py",
        "layout/by_design.py",
        "openspec/changes/the-design-system-lays-out-recipe-slides/"
      ],
      "status": "pending",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0
    },
    {
      "id": "03",
      "title": "Слайд без примера верстается дизайн-системой (change 5б)",
      "requirements": [
        "R01",
        "R02",
        "R03",
        "R06",
        "R07",
        "R22",
        "R23",
        "R24",
        "R25",
        "R26",
        "R27",
        "R29i",
        "R30i"
      ],
      "blockedBy": [
        "01"
      ],
      "wave": 2,
      "zone": [
        "rendering/writer.py (SlideDegrader, _render_slide)",
        "layout/fitting.py",
        "rendering/{smartart,charts,tables}.py",
        "openspec/changes/no-example-goes-by-design/"
      ],
      "status": "in-progress",
      "retries": 0,
      "repairs": 0,
      "handoffs": 0,
      "startedAt": "2026-09-28T20:39:02+03:00"
    }
  ],
  "singlePass": null,
  "tests": {
    "passed": 2385,
    "failed": 0
  },
  "debt": {
    "placeholders": [],
    "assumptions": [],
    "emptyEnv": []
  },
  "additions": [],
  "coverage": {
    "findings": 11,
    "missing": 7,
    "half": 4,
    "extra": 15,
    "actions": "7 пропусков и 4 половины дописаны в spec (ист. 1,3,13,16,20,22,22a,25,27,28); 15 «лишних» — углубления R## (R08.1, R08.2, R10, R16.1 и т.п.), оставлены"
  },
  "concerns": [
    "T01 manifest: куб-иллюстрация VK Tech (s02–s04, s09) уходит с незаполненной g06 — место-картинку писатель не заполняет; в proposal «незакрыто», решает тимлид",
    "T01 spec: recipe_slide.py:414 — пустое место-картинка в заполненной группе остаётся (ист. 8 говорит «удаляется»); решение записано в proposal",
    "T01 spec: proposal.md:76 — замер audit через reaudit из скрипта, а не CLI `deckforge audit`; по смыслу то же",
    "T01: после rebase на origin/plan-b (#249 — ёмкость паспорта кеглем порога) перемерить строку 3"
  ],
  "reviewers": {
    "manifestSpec": "rev-ms (a86b1a6872adbaf5f)",
    "craft": "rev-craft (a8578713ef4e9b863)"
  },
  "blind": null
}
