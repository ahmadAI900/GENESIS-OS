"""
Genesis OS — Level 3.12
Windows / Daily Intelligence / Notes / Packages / Cleanup.

Regression tests for the newest universal capability wave:

    website shortcuts, YouTube playback, window management,
    weather, world clock, safe calculator, storage query,
    personal notes, winget package management (gated),
    recycle bin (gated + queryable).
"""

from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.execution_safety import ExecutionSafety


@pytest.fixture(scope="module")
def engine():
    return WorkflowDecisionEngine()


# =========================================================
# SAFETY CLASSIFICATION
# =========================================================


def test_new_capabilities_registered_and_allowed():
    for operation in (
        "window.minimize_all", "window.restore", "window.show_desktop",
        "web.weather", "time.world_clock", "math.evaluate",
        "hardware.storage", "notes.create", "notes.list",
        "package.search", "cleanup.recycle_bin_query",
    ):
        assert ExecutionSafety.check(operation).status == "supported"


def test_irreversible_or_system_changing_capabilities_are_gated():
    from genesis_os.capability_registry import CapabilityRegistry

    for operation in (
        "package.install",
        "package.uninstall",
        "cleanup.empty_recycle_bin",
    ):
        metadata = CapabilityRegistry.get(operation).metadata
        assert metadata.get("requires_confirmation") is True


# =========================================================
# WEBSITE SHORTCUTS + YOUTUBE PLAYBACK
# =========================================================


@pytest.mark.parametrize(
    "text,url",
    [
        ("open youtube", "https://www.youtube.com"),
        ("open github", "https://github.com"),
        ("visit whatsapp web", "https://web.whatsapp.com"),
        ("go to google maps", "https://maps.google.com"),
    ],
)
def test_site_shortcuts_route_to_open_url(engine, text, url):
    decision = engine.decide(text)

    assert decision["level"] == 3
    assert decision["intent"] == "browser.open_url"
    assert decision["parameters"]["url"] == url


@pytest.mark.parametrize(
    "text,query",
    [
        ("play despacito on youtube", "despacito"),
        ("play lofi beats on youtube", "lofi beats"),
    ],
)
def test_youtube_playback_routes_to_search(engine, text, query):
    decision = engine.decide(text)

    # Must be YouTube search — NOT a media-key toggle.
    assert decision["intent"] == "browser.search"
    assert decision["parameters"]["engine"] == "youtube"
    assert decision["parameters"]["query"] == query


def test_generic_media_keys_still_work(engine):
    decision = engine.decide("play music")

    assert decision["intent"] == "media.play_pause"


def test_unknown_sites_do_not_fake_navigation(engine):
    decision = engine.decide("open banana-land")

    # No such site alias -> must not become an OS navigation.
    assert not (
        decision["level"] == 3
        and decision["intent"] == "browser.open_url"
        and "banana" in str(decision.get("target"))
    )


# =========================================================
# WINDOW MANAGEMENT
# =========================================================


@pytest.mark.parametrize(
    "text,intent",
    [
        ("minimize all windows", "window.minimize_all"),
        ("show desktop", "window.show_desktop"),
        ("restore windows", "window.restore"),
    ],
)
def test_window_routing(engine, text, intent):
    decision = engine.decide(text)

    assert decision["level"] == 3
    assert decision["intent"] == intent


def test_minimize_all_dispatch(monkeypatch):
    from genesis_os.window_manager import WindowManager

    manager = WindowManager()
    dispatched = []

    class FakeShell:
        def MinimizeAll(self_inner):
            dispatched.append("MinimizeAll")

    monkeypatch.setattr(manager, "_shell", lambda: FakeShell())

    result = manager.minimize_all()

    assert result["success"] is True
    assert result["verified"] is False
    assert dispatched == ["MinimizeAll"]


# =========================================================
# DAILY INTELLIGENCE
# =========================================================


def test_weather_contract_with_live_service_offline_mocked():
    from genesis_os.daily_intelligence import DailyIntelligence

    fake_response = Mock(status_code=200, text="London: ⛅ +11°C")
    fake_requests = Mock()
    fake_requests.get.return_value = fake_response

    module = __import__("genesis_os.daily_intelligence", fromlist=["DailyIntelligence"])
    real_import = __import__

    daily = module.DailyIntelligence()

    import types, sys as _sys

    fake_module = types.SimpleNamespace(get=fake_requests.get)
    monkey = pytest.MonkeyPatch()
    monkey.setitem(_sys.modules, "requests", fake_module)

    try:
        result = daily.weather("London")
    finally:
        monkey.undo()

    assert result["success"] is True
    assert result["verified"] is True
    assert "+11" in result["message"] or "London" in result["message"]


def test_weather_honest_failure_on_bad_status():
    import types
    from genesis_os.daily_intelligence import DailyIntelligence

    daily = DailyIntelligence()
    fake_module = types.SimpleNamespace()
    import types as _types, sys as _sys

    def raise_404(*args, **kwargs):
        class R:
            status_code = 404
            text = ""
        return R()

    fake_module.get = raise_404
    monkey = pytest.MonkeyPatch()
    monkey.setitem(_sys.modules, "requests", fake_module)

    try:
        result = daily.weather("Nowhereville XYZ")
    finally:
        monkey.undo()

    assert result["success"] is False
    assert "HTTP 404" in result["error"]


def test_world_clock_known_cities():
    from genesis_os.daily_intelligence import DailyIntelligence

    daily = DailyIntelligence()

    tokyo = daily.world_clock("tokyo")
    assert tokyo["success"] is True
    assert tokyo["timezone"] == "Asia/Tokyo"

    new_york = daily.world_clock("new york")
    assert new_york["success"] is True
    assert new_york["timezone"] == "America/New_York"


def test_world_clock_unknown_city_is_honest():
    from genesis_os.daily_intelligence import DailyIntelligence

    result = DailyIntelligence().world_clock("banana town")

    assert result["success"] is False
    assert "timezone" in result["error"]


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("25 * 4 + 10", 110),
        ("(12+8)/4", 5),
        ("2 ** 10", 1024),
        ("7 // 2", 3),
    ],
)
def test_calculator_pure_arithmetic(expression, expected):
    from genesis_os.daily_intelligence import DailyIntelligence

    result = DailyIntelligence().calculate(expression)

    assert result["success"] is True
    assert result["result"] == expected


@pytest.mark.parametrize(
    "malicious",
    [
        "__import__('os').system('dir')",
        "().__class__",
        "open('C:/secrets')",
        "lambda: 1",
    ],
)
def test_calculator_rejects_everything_but_arithmetic(malicious):
    from genesis_os.daily_intelligence import DailyIntelligence

    result = DailyIntelligence().calculate(malicious)

    assert result["success"] is False
    assert result["executed"] is False


def test_storage_report_contract(tmp_path):
    from genesis_os.daily_intelligence import DailyIntelligence

    result = DailyIntelligence().storage()

    if result.get("available") is False:
        pytest.skip("psutil unavailable")

    assert result["success"] is True
    assert result["primary_total_gb"] > 0
    assert any(d["free_gb"] >= 0 for d in result["drives"])


# =========================================================
# NOTES
# =========================================================


def test_note_create_verifies_by_readback(tmp_path):
    from genesis_os.notes_manager import NotesManager

    manager = NotesManager(base_dir=tmp_path)

    result = manager.create_note("buy milk tomorrow")

    assert result["success"] is True
    assert result["verified"] is True

    files = list(tmp_path.glob("*.txt"))
    assert len(files) == 1
    assert "buy milk tomorrow" in files[0].read_text(encoding="utf-8")


def test_notes_list_newest_first(tmp_path):
    from genesis_os.notes_manager import NotesManager
    import os, time

    manager = NotesManager(base_dir=tmp_path)

    manager.create_note("first note")
    time.sleep(0.05)
    manager.create_note("second note")

    listing = manager.list_notes()

    assert listing["success"] is True
    assert listing["count"] == 2
    assert "second note" in listing["notes"][0]["preview"]


def test_empty_note_rejected_without_execution(tmp_path):
    from genesis_os.notes_manager import NotesManager

    result = NotesManager(base_dir=tmp_path).create_note("   ")

    assert result["success"] is False
    assert result["executed"] is False


# =========================================================
# PACKAGE MANAGEMENT — GATED
# =========================================================


def test_install_requires_confirmation_before_winget():
    os_manager = Mock()
    executor = ActionExecutor(os_manager)

    plan = ActionPlan(
        operation="package.install",
        target="spotify",
        parameters={"package": "spotify"},
        confidence=0.99,
    )

    result = executor.execute(plan)

    assert result.status == "confirmation_required"
    os_manager.package_install.assert_not_called()


def test_uninstall_requires_confirmation():
    os_manager = Mock()
    executor = ActionExecutor(os_manager)

    plan = ActionPlan(
        operation="package.uninstall",
        target="vlc",
        parameters={"package": "vlc"},
        confidence=0.99,
    )

    result = executor.execute(plan)

    assert result.status == "confirmation_required"
    os_manager.package_uninstall.assert_not_called()


def test_package_search_executes_read_only():
    os_manager = Mock()
    os_manager.package_search.return_value = {
        "success": True,
        "operation": "package.search",
        "results": ["Spotify Spotify.Spotify"],
        "result_count": 1,
        "executed": True,
        "verified": True,
        "message": "Spotify Spotify.Spotify",
    }

    plan = ActionPlan(
        operation="package.search",
        target="spotify",
        parameters={"query": "spotify"},
        confidence=0.95,
    )

    result = ActionExecutor(os_manager).execute(plan)

    assert result.success is True
    os_manager.package_search.assert_called_once_with("spotify", 5)


# =========================================================
# RECYCLE BIN — GATED + QUERYABLE
# =========================================================


def test_recycle_bin_query_executes():
    os_manager = Mock()
    os_manager.recycle_bin_stats.return_value = {
        "success": True,
        "operation": "cleanup.recycle_bin_query",
        "item_count": 3,
        "size_mb": 12.5,
        "executed": False,
        "verified": True,
        "message": "The Recycle Bin holds 3 item(s) (12.5 MB).",
    }

    plan = ActionPlan(
        operation="cleanup.recycle_bin_query",
        target="recycle bin",
        confidence=0.95,
    )

    result = ActionExecutor(os_manager).execute(plan)

    assert result.success is True
    os_manager.recycle_bin_stats.assert_called_once()


def test_empty_recycle_bin_requires_confirmation():
    os_manager = Mock()
    executor = ActionExecutor(os_manager)

    plan = ActionPlan(
        operation="cleanup.empty_recycle_bin",
        target="recycle bin",
        confidence=0.99,
    )

    result = executor.execute(plan)

    assert result.status == "confirmation_required"
    os_manager.empty_recycle_bin.assert_not_called()


# =========================================================
# ROUTING SAFETY — CONVERSATION MUST STAY CONVERSATION
# =========================================================


@pytest.mark.parametrize(
    "text",
    [
        "what is love",
        "tell me about paris history",
        "how do i install python libraries in my project",
    ],
)
def test_conversational_lookalikes_stay_out_of_os(engine, text):
    decision = engine.decide(text)

    # These must never silently trigger OS actions.
    if decision["level"] == 3:
        assert decision["confidence"] < 0.90  # not auto-promoted
