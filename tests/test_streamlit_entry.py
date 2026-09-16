from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp_orchestrator import ui

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
STREAMLIT_CONFIG_PATH = PROJECT_ROOT / ".streamlit" / "config.toml"


def test_entry_point_exists_at_the_documented_root_path() -> None:
    assert APP_PATH.is_file()


def test_project_reserves_a_local_private_streamlit_server() -> None:
    config_text = STREAMLIT_CONFIG_PATH.read_text(encoding="utf-8")

    assert "[server]" in config_text
    assert 'address = "localhost"' in config_text
    assert "port = 8502" in config_text
    assert "[browser]" in config_text
    assert "gatherUsageStats = false" in config_text


def test_page_configuration_uses_the_locked_ui_shell(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def capture_page_config(**kwargs: object) -> None:
        observed.update(kwargs)

    monkeypatch.setattr(ui.st, "set_page_config", capture_page_config)

    ui.configure_page()

    assert observed == {
        "page_title": "Enterprise RFP Response Orchestrator",
        "page_icon": "📄",
        "layout": "wide",
        "initial_sidebar_state": "expanded",
    }


def test_streamlit_entry_point_renders_without_an_exception() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception


def test_streamlit_shell_shows_the_expected_heading_and_subtitle() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert [title.value for title in app.title] == [ui.APP_TITLE]
    assert app.caption[0].value == ui.APP_SUBTITLE
