import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "geoskills" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def test_plot_ree_reexports_shared_plot_contract() -> None:
    from geoskills_core.errors import PlottingError as CorePlottingError
    from geoskills_core.plotting import (
        FORMATS as CORE_FORMATS,
        GROUP_COLORS as CORE_GROUP_COLORS,
        MARKERS as CORE_MARKERS,
        configure_boxed_legend as core_configure_boxed_legend,
    )
    from plot_ree import (
        FORMATS,
        GROUP_COLORS,
        MARKERS,
        PlottingError,
        configure_boxed_legend,
    )

    assert PlottingError is CorePlottingError
    assert FORMATS is CORE_FORMATS
    assert GROUP_COLORS is CORE_GROUP_COLORS
    assert MARKERS is CORE_MARKERS
    assert configure_boxed_legend is core_configure_boxed_legend


def test_major_plot_modules_do_not_import_plot_ree() -> None:
    for filename in ("plot_geochem_common.py", "plot_harker.py", "plot_tas.py"):
        source = (SCRIPTS / filename).read_text(encoding="utf-8")
        assert "from plot_ree import" not in source
        assert "import plot_ree" not in source


def test_plot_modules_do_not_mutate_global_rcparams_at_import() -> None:
    for filename in (
        "plot_ree.py",
        "plot_spider.py",
        "plot_harker.py",
        "plot_tas.py",
    ):
        source = (SCRIPTS / filename).read_text(encoding="utf-8")
        assert "plt.rcParams[" not in source


def test_all_plotters_use_one_central_font_stack_without_local_overrides() -> None:
    from geoskills_core.plotting import (
        PUBLICATION_DOUBLE_COLUMN,
        SANS_SERIF_FONT_STACK,
        STYLE_PRESETS,
    )

    assert tuple(
        STYLE_PRESETS[PUBLICATION_DOUBLE_COLUMN]["font.sans-serif"]
    ) == SANS_SERIF_FONT_STACK
    assert SANS_SERIF_FONT_STACK[:2] == ("Arial", "Helvetica")
    for filename in (
        "plot_ree.py",
        "plot_spider.py",
        "plot_harker.py",
        "plot_tas.py",
        "plot_k2o_sio2.py",
    ):
        source = (SCRIPTS / filename).read_text(encoding="utf-8")
        assert '"font.sans-serif"' not in source
