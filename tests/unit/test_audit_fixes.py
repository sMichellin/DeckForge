"""Авто-фиксы: на находке, которую чинить можно, и на той, где чинить нечем. Change (19).

Находки здесь **не пишутся руками, а получаются от самих проверок**. Фикс читает
`evidence` — номер пункта, ось промаха, — и тест на выдуманной находке доказывал бы
только то, что автор фикса и автор теста поняли друг друга. Пара «проверка → починка»
проверяется целиком, вместе с именами ключей.
"""

from __future__ import annotations

from deckforge.audit.deterministic.density import bullet_too_long, too_many_bullets
from deckforge.audit.deterministic.layout import off_guides, text_overflow
from deckforge.audit.deterministic.template import color_not_in_palette
from deckforge.audit.findings import make_finding
from deckforge.audit.fixes import FixApplier
from deckforge.audit.fixes.apply import shorten_to_words
from deckforge.audit.semantic import judge  # noqa: F401  регистрация вопросов судьи
from deckforge.domain.audit import Finding
from deckforge.domain.enums import AutoFix, ColorRef
from deckforge.domain.slide import BulletsBlock, ChartBlock, FitResult, TextBlock
from deckforge.domain.template import TemplateManifest
from tests.unit._audit_builders import bullets, chart, cm, context_for, deck, slide, title

#: 16 слов, придаточное начинается после восьмого.
LONG_BULLET = (
    "Выручка выросла на треть за счёт корпоративных клиентов, "
    "а средний чек остался прежним и не изменился"
)
#: 17 слов без единого знака препинания: резать некуда, кроме как по счёту.
UNBROKEN_BULLET = (
    "Команда выпустила новую версию продукта и показала её партнёрам "
    "на осенней отраслевой конференции в конце сентября этого года"
)


def with_guides(manifest: TemplateManifest) -> TemplateManifest:
    """Манифест с направляющими: в синтетическом шаблоне их нет вовсе."""
    grid = manifest.grid.model_copy(update={"guides_x_emu": [cm(3)], "guides_y_emu": [cm(6)]})
    return manifest.model_copy(update={"grid": grid})


def overflowing(size_pt: float | None = None) -> object:
    """Слайд с заголовком, который вёрстка уже померила и признала непомещающимся."""
    measured = FitResult(final_size_pt=size_pt or 40, overflow=True)
    return slide(title(size_pt=size_pt), fit_report={"b1": measured})


def skip_reason(report: object) -> str:
    finding: Finding = report.findings[0]  # type: ignore[attr-defined]
    return finding.evidence["fix_skipped"]


# --- shrink_font -------------------------------------------------------------


def test_shrink_font_steps_down_the_template_ladder(manifest: TemplateManifest) -> None:
    """Кегль не выдумывается: 40 pt уходит на 24 pt — следующую ступень шкалы шаблона."""
    colony = deck(overflowing())
    found = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))
    assert [f.auto_fix for f in found] == [AutoFix.SHRINK_FONT]

    fixed, report = FixApplier().apply(colony, found, manifest)

    block = fixed.slides[0].block("b1")
    assert isinstance(block, TextBlock)
    assert block.size_pt == 24
    assert report.findings[0].auto_fix_applied is True


def test_shrink_font_drops_the_stale_measurement(manifest: TemplateManifest) -> None:
    """Замер вписывания сделан на прежнем кегле: оставить его — показать чужое переполнение."""
    colony = deck(overflowing())
    found = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))

    fixed, _ = FixApplier().apply(colony, found, manifest)

    assert "b1" not in fixed.slides[0].fit_report


def test_shrink_font_at_the_last_rung_is_refused_not_invented(manifest: TemplateManifest) -> None:
    """12 pt — низ шкалы. Своих значений у починки нет, поэтому она отказывается."""
    colony = deck(overflowing(size_pt=12))
    found = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))

    fixed, report = FixApplier().apply(colony, found, manifest)

    block = fixed.slides[0].block("b1")
    assert isinstance(block, TextBlock)
    assert block.size_pt == 12
    assert report.findings[0].auto_fix_applied is False
    assert "последняя ступень" in skip_reason(report)


# --- snap_to_guide -----------------------------------------------------------


def test_block_is_pulled_onto_the_guide_it_almost_reached(manifest: TemplateManifest) -> None:
    aligned = with_guides(manifest)
    colony = deck(slide(title(), bullets("раз", "два", box=(3.05, 6, 8, 3))))
    found = list(off_guides(context_for("layout.off_guides", colony, aligned)))
    assert [f.evidence["axis"] for f in found] == ["x"]

    fixed, report = FixApplier().apply(colony, found, aligned)

    assert fixed.slides[0].block("b2").x == cm(3)
    assert report.findings[0].auto_fix_applied is True


def test_block_already_on_the_guide_gives_nothing_to_fix(manifest: TemplateManifest) -> None:
    aligned = with_guides(manifest)
    colony = deck(slide(title(), bullets("раз", "два", box=(3, 6, 8, 3))))

    assert list(off_guides(context_for("layout.off_guides", colony, aligned))) == []


def test_guide_beyond_tolerance_is_left_alone(manifest: TemplateManifest) -> None:
    """Находка из прошлого витка, блок с тех пор уехал: тянуть его через пол-слайда нельзя."""
    aligned = with_guides(manifest)
    colony = deck(slide(title(), bullets("раз", "два", box=(8, 6, 8, 3))))
    stale = make_finding(
        check_id="layout.off_guides",
        slide_id="s01",
        block_id="b2",
        reason="off:x",
        message="из прошлого витка",
        evidence={"axis": "x"},
    )

    fixed, report = FixApplier().apply(colony, [stale], aligned)

    assert fixed.slides[0].block("b2").x == cm(8)
    assert "дальше допуска" in skip_reason(report)


def test_block_in_a_placeholder_is_not_moved(manifest: TemplateManifest) -> None:
    """Положение выбрал автор шаблона — двигать его значит ломать чужой макет."""
    colony = deck(slide(title(), bullets("раз", "два")))
    stale = make_finding(
        check_id="layout.off_guides",
        slide_id="s01",
        block_id="b2",
        reason="off:x",
        message="блок в плейсхолдере",
        evidence={"axis": "x"},
    )

    _, report = FixApplier().apply(colony, [stale], with_guides(manifest))

    assert "плейсхолдере" in skip_reason(report)


# --- shorten_text ------------------------------------------------------------


def test_long_bullet_is_cut_on_a_clause_boundary(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets(LONG_BULLET, "короткий пункт")))
    found = list(bullet_too_long(context_for("density.bullet_too_long", colony, manifest)))
    assert [f.evidence["item_index"] for f in found] == ["0"]

    fixed, report = FixApplier().apply(colony, found, manifest)

    block = fixed.slides[0].block("b2")
    assert isinstance(block, BulletsBlock)
    assert block.items[0].text == "Выручка выросла на треть за счёт корпоративных клиентов"
    assert block.items[1].text == "короткий пункт"
    assert report.findings[0].auto_fix_applied is True


def test_bullet_without_a_clause_boundary_gets_an_ellipsis() -> None:
    """Резать нечем — обрыв честно помечается, а не выдаётся за законченную мысль."""
    assert shorten_to_words(UNBROKEN_BULLET, 15).endswith("…")
    assert len(shorten_to_words(UNBROKEN_BULLET, 15).split()) == 15


def test_bullet_within_the_limit_is_left_as_is(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets("короткий пункт", "и ещё один")))

    assert list(bullet_too_long(context_for("density.bullet_too_long", colony, manifest))) == []


# --- map_to_nearest_theme_color ----------------------------------------------


def test_series_of_the_same_colour_are_separated(manifest: TemplateManifest) -> None:
    """Свободный акцент выбирается самый далёкий: две похожие серии не лучше двух одинаковых."""
    colony = deck(slide(title(), chart(series_color_refs=[ColorRef.ACCENT1, ColorRef.ACCENT1])))
    context = context_for("template.color_not_in_palette", colony, manifest)
    found = list(color_not_in_palette(context))
    assert [f.auto_fix for f in found] == [AutoFix.MAP_TO_NEAREST_THEME_COLOR]

    fixed, report = FixApplier().apply(colony, found, manifest)

    block = fixed.slides[0].block("b3")
    assert isinstance(block, ChartBlock)
    assert block.series_color_refs == [ColorRef.ACCENT1, ColorRef.ACCENT3]
    assert report.findings[0].auto_fix_applied is True


def test_distinct_series_colours_are_not_a_finding(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), chart(series_color_refs=[ColorRef.ACCENT1, ColorRef.ACCENT2])))

    context = context_for("template.color_not_in_palette", colony, manifest)
    assert list(color_not_in_palette(context)) == []


# --- split_slide -------------------------------------------------------------


def test_extra_bullets_move_to_a_continuation_slide(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets(*(f"пункт {i}" for i in range(1, 8)))))
    found = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))
    assert [f.auto_fix for f in found] == [AutoFix.SPLIT_SLIDE]

    fixed, report = FixApplier().apply(colony, found, manifest)

    first, second = fixed.slides
    assert [len(b.items) for b in first.blocks if isinstance(b, BulletsBlock)] == [6]
    assert [len(b.items) for b in second.blocks if isinstance(b, BulletsBlock)] == [1]
    assert second.slide_id == "s01-2"
    assert report.findings[0].auto_fix_applied is True


def test_continuation_keeps_the_headline_and_says_it_continues(manifest: TemplateManifest) -> None:
    """Тот же заголовок дважды подряд читается как сбой генерации."""
    colony = deck(slide(title("Выручка выросла"), bullets(*(f"пункт {i}" for i in range(1, 8)))))
    found = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))

    fixed, _ = FixApplier().apply(colony, found, manifest)

    carried = fixed.slides[1].block("b1")
    assert isinstance(carried, TextBlock)
    assert carried.text == "Выручка выросла (продолжение)"


def test_continuation_lands_next_to_its_parent_not_at_the_end(
    manifest: TemplateManifest,
) -> None:
    crowded = slide(title(), bullets(*(f"пункт {i}" for i in range(1, 8))), slide_id="s01")
    colony = deck(crowded, slide(title(), slide_id="s02", layout_id="L01"))
    found = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))

    fixed, _ = FixApplier().apply(colony, found, manifest)

    assert [s.slide_id for s in fixed.slides] == ["s01", "s01-2", "s02"]


def test_continuation_of_a_recipe_slide_is_built_by_the_same_recipe(
    manifest: TemplateManifest,
) -> None:
    """Продолжение наследует `recipe_id`: иначе блоки в зонах без рецепта — смешанный слайд.

    Change `split-slide-carries-the-recipe` (RG19). Такой слайд не вписать по макету и
    не собрать по рецепту — см. `test_by_recipe_is_one_predicate::
    test_a_mixed_slide_is_not_by_recipe`. Фикс его больше не порождает.
    """
    by_recipe = slide(
        title(placeholder_idx=None).model_copy(update={"zone_id": "z1"}),
        bullets(*(f"пункт {i}" for i in range(1, 8)), placeholder_idx=None).model_copy(
            update={"zone_id": "z2"}
        ),
    ).model_copy(update={"recipe_id": "ex003"})
    assert by_recipe.by_recipe
    colony = deck(by_recipe)
    found = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))

    fixed, _ = FixApplier().apply(colony, found, manifest)

    first, second = fixed.slides
    assert (first.recipe_id, second.recipe_id) == ("ex003", "ex003")
    assert first.by_recipe and second.by_recipe


def test_continuation_of_an_ordinary_slide_has_no_recipe(manifest: TemplateManifest) -> None:
    """Норма к предыдущему: слайд по макету и продолжение получает по макету."""
    colony = deck(slide(title(), bullets(*(f"пункт {i}" for i in range(1, 8)))))
    found = list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest)))

    fixed, _ = FixApplier().apply(colony, found, manifest)

    continuation = fixed.slides[1]
    assert continuation.recipe_id is None
    assert not continuation.by_recipe


def test_slide_within_the_limit_is_not_split(manifest: TemplateManifest) -> None:
    colony = deck(slide(title(), bullets(*(f"пункт {i}" for i in range(1, 7)))))

    assert list(too_many_bullets(context_for("density.too_many_bullets", colony, manifest))) == []


def test_block_fixes_are_applied_before_the_split(manifest: TemplateManifest) -> None:
    """Иначе сокращение уехало бы на продолжение или потерялось вместе с прежними блоками."""
    items = [LONG_BULLET, *(f"пункт {i}" for i in range(2, 8))]
    colony = deck(slide(title(), bullets(*items)))
    found = [
        *bullet_too_long(context_for("density.bullet_too_long", colony, manifest)),
        *too_many_bullets(context_for("density.too_many_bullets", colony, manifest)),
    ]

    fixed, report = FixApplier().apply(colony, found, manifest)

    first = fixed.slides[0].block("b2")
    assert isinstance(first, BulletsBlock)
    assert first.items[0].text == "Выручка выросла на треть за счёт корпоративных клиентов"
    assert all(f.auto_fix_applied for f in report.findings)


# --- отказы и отчётность -----------------------------------------------------


def test_headline_rewrite_is_declined_with_a_reason(manifest: TemplateManifest) -> None:
    """Заголовок переписывает модель. У слоя фиксов её нет — и он это говорит вслух."""
    colony = deck(slide(title()))
    verdict = make_finding(
        check_id="content.headline_is_conclusion",
        slide_id="s01",
        reason="verdict",
        message="заголовок — тема, а не вывод",
    )
    assert verdict.auto_fix is AutoFix.REGENERATE_HEADLINE

    fixed, report = FixApplier().apply(colony, [verdict], manifest)

    assert fixed == colony
    assert report.findings[0].auto_fix_applied is False
    assert "модель" in skip_reason(report)


def test_every_selected_finding_comes_back_with_a_verdict(manifest: TemplateManifest) -> None:
    """Молчание про находку неотличимо от «починили»: пользователь выбрал — пусть видит исход."""
    colony = deck(overflowing())
    found = list(text_overflow(context_for("layout.text_overflow", colony, manifest)))
    missing = make_finding(
        check_id="layout.text_overflow",
        slide_id="s99",
        block_id="b1",
        reason="measured",
        message="слайда нет в колоде",
    )

    _, report = FixApplier().apply(colony, [*found, missing], manifest)

    assert len(report.findings) == 2
    assert all(("fix" in f.evidence) != ("fix_skipped" in f.evidence) for f in report.findings)
    assert report.summary.passed == 0


def test_missing_block_is_reported_not_swallowed(manifest: TemplateManifest) -> None:
    colony = deck(slide(title()))
    orphan = make_finding(
        check_id="layout.text_overflow",
        slide_id="s01",
        block_id="b404",
        reason="measured",
        message="блока нет",
    )

    _, report = FixApplier().apply(colony, [orphan], manifest)

    assert "block_id" in skip_reason(report)


def test_guide_that_would_push_the_block_off_the_page_is_refused(
    manifest: TemplateManifest,
) -> None:
    """Прогон 80e7af41ab54: починка сдвинула блок на 0,12 см вниз, и записать колоду стало нельзя.

    Правка, после которой файл не пишется, хуже ненайденной находки.
    """
    bottom = manifest.content_bbox.bottom
    # Направляющая в 0,1 см ниже блока — это внутри допуска (45720 EMU ≈ 0,13 см),
    # и блок, стоящий впритык к нижнему полю, после сдвига вылезет за него.
    guide = bottom - cm(1) + cm(0.1)
    aligned = manifest.model_copy(
        update={"grid": manifest.grid.model_copy(update={"guides_y_emu": [guide]})}
    )
    box = (3, (bottom - cm(1)) / 360000, 8, 1.0)
    colony = deck(slide(title(), bullets("раз", "два", box=box)))
    nudge = make_finding(
        check_id="layout.off_guides",
        slide_id="s01",
        block_id="b2",
        reason="off:y",
        message="почти на направляющей",
        evidence={"axis": "y"},
    )

    fixed, report = FixApplier().apply(colony, [nudge], aligned)

    moved = fixed.slides[0].block("b2")
    assert moved is not None and moved.bbox is not None
    assert aligned.content_bbox.contains(moved.bbox), "колода перестала быть записываемой"
    assert "за поля шаблона" in skip_reason(report)
