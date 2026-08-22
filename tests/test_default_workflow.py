# LumaFlow v1.0 (2026-08-07)
# Vérifie le workflow par défaut (9 lignes déclarées dans l'ordre attendu, identifiants/libellés/
# presets vignette neutres présents) ainsi que le remplacement de la config par une alternative
# valide (ordre différent, nombre de lignes différent, config vide, identifiant réutilisé).

import json
import pathlib

from lumaflow.config.workflow import (
    DEFAULT_WORKFLOW_CONFIG_PATH,
    load_workflow_config,
    validate_workflow_config_dict,
    workflow_config_from_dict,
)

REPO_ROOT = pathlib.Path(__file__).parent.parent
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures" / "workflow_config"


# --- User Story 1: The Standard Journey Is Available Out of the Box ---
# (7 steps since constitution v1.5.0 / feature 046 -- Color Splash added after Film;
# 8 steps since 2026-07-25 -- Bleach Bypass added between Film and Color Splash;
# 9 steps since 2026-07-26 -- Monochrome added between Color Splash and Light;
# 10 steps since 2026-07-26 (later the same day) -- B&W added between Monochrome and Light;
# 9 steps since 2026-07-31 -- "finishing" removed (spec 045 abandoned, never implemented --
# no addon ever existed for it, only a Neutral placeholder; see constitution v1.6.0).)


def test_default_loads_to_exactly_9_rows_in_declared_order():
    # 9 rows since 2026-07-31 -- "finishing" removed (see module docstring above).
    config = load_workflow_config(DEFAULT_WORKFLOW_CONFIG_PATH)
    assert [row.identifier for row in config.rows] == [
        "geometry",
        "framing",
        "film",
        "bleach_bypass",
        "color_splash",
        "monochrome",
        "bw",
        "light",
        "vignette",
    ]


def test_default_rows_have_identifier_and_label_populated():
    config = load_workflow_config(DEFAULT_WORKFLOW_CONFIG_PATH)
    assert all(row.label for row in config.rows)


def test_default_rows_thumbnail_presets_first_is_neutral():
    config = load_workflow_config(DEFAULT_WORKFLOW_CONFIG_PATH)
    assert all(row.thumbnail_presets[0] == "neutral" for row in config.rows)


def test_default_row_identifiers_are_mutually_distinct():
    config = load_workflow_config(DEFAULT_WORKFLOW_CONFIG_PATH)
    assert len(set(row.identifier for row in config.rows)) == 9


def test_default_loads_through_f022_unmodified_validation():
    data = json.loads(DEFAULT_WORKFLOW_CONFIG_PATH.read_text(encoding="utf-8"))
    validate_workflow_config_dict(data)


# --- User Story 3: The Default Workflow Can Be Replaced by Another Valid Configuration ---


def test_alternate_config_loads_in_its_own_order_not_defaults():
    config = load_workflow_config(FIXTURES_ROOT / "alternate_default.json")
    assert [row.identifier for row in config.rows] == ["finishing", "light", "geometry"]


def test_alternate_config_with_different_row_count_loads_without_error():
    config = load_workflow_config(FIXTURES_ROOT / "alternate_default.json")
    assert len(config.rows) != 6


def test_zero_row_replacement_loads_successfully():
    config = workflow_config_from_dict({"rows": []})
    assert config.rows == ()


def test_reused_default_identifier_in_replacement_is_permitted():
    config = workflow_config_from_dict(
        {"rows": [{"identifier": "geometry", "category": "some_other_category"}]}
    )
    assert config.rows[0].identifier == "geometry"
    assert config.rows[0].category == "some_other_category"
