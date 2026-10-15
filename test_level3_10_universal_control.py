"""
Genesis OS — Level 3.10
Universal Desktop Control.

Regression tests for genuine hardware/desktop capabilities:

    media transport keys, precise volume control, display
    brightness, hardware intelligence, clipboard, screen capture,
    workstation lock — plus AI intent resolution safety.
"""

import subprocess
from unittest.mock import Mock

import pytest

from agents.workflow_decision import WorkflowDecisionEngine
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.execution_safety import ExecutionSafety


# =========================================================
# ROUTING
# =========================================================


@pytest.mark.parametrize(
    "text,intent",
    [
        ("take a screenshot", "screen.capture"),
        ("screenshot", "screen.capture"),
        ("play music", "media.play_pause"),
        ("pause music", "media.play_pause"),
        ("next track", "media.next"),
        ("previous song", "media.previous"),
        ("volume up", "volume.up"),
        ("turn volume down", "volume.down"),
        ("mute", "volume.mute_toggle"),
        ("unmute", "volume.mute_toggle"),
        ("mute the volume", "volume.mute_toggle"),
        ("set volume to 40%", "volume.set"),
        ("volume max", "volume.set"),
        ("set brightness to 70%", "display.brightness_set"),
        ("brightness up", "display.brightness_set"),
        ("how much battery do i have", "hardware.battery"),
        ("battery status", "hardware.battery"),
        ("cpu usage", "hardware.stats"),
        ("copy hello world to clipboard", "clipboard.copy"),
        ("whats in the clipboard", "clipboard.paste"),
        ("lock my computer", "workstation.lock"),
    ],
)
def test_universal_control_routing(text, intent):
    decision = WorkflowDecisionEngine().decide(text)

    assert decision["level"] == 3
    assert decision["intent"] == intent


def test_conversational_questions_stay_out_of_hardware_routing():
    engine = WorkflowDecisionEngine()

    assert engine.decide("battery")["level"] == 3  # short direct command

    # Long conversational usage must NOT become an OS action.
    conversation = engine.decide(
        "the battery of ideas in this essay is weak"
    )
    assert conversation["intent"] != "hardware.battery"


# =========================================================
# SAFETY CLASSIFICATION
# =========================================================


@pytest.mark.parametrize(
    "operation",
    [
        "media.play_pause",
        "media.next",
        "volume.up",
        "volume.down",
        "volume.mute_toggle",
        "volume.set",
        "volume.get",
        "display.brightness_set",
        "display.brightness_get",
        "hardware.battery",
        "hardware.stats",
        "clipboard.copy",
        "clipboard.paste",
        "screen.capture",
    ],
)
def test_new_capabilities_are_registered_and_allowed(operation):
    assert ExecutionSafety.check(operation).status == "supported"


def test_workstation_lock_is_confirmation_gated():
    os_manager = Mock()
    executor = ActionExecutor(os_manager)

    plan = ActionPlan(operation="workstation.lock", target="workstation")
    result = executor.execute(plan)

    assert result.success is False
    assert result.status == "confirmation_required"
    os_manager.lock_workstation.assert_not_called()


# =========================================================
# MEDIA / VOLUME CONTROL
# =========================================================


def test_media_key_dispatch_maps_actions(monkeypatch):
    import genesis_os.media_control as mc

    pressed = []
    monkeypatch.setattr(mc, "_press_key", lambda vk: (pressed.append(vk), True)[1])

    controller = mc.MediaController()
    result = controller.send_media_key("play_pause")

    assert result["success"] is True
    assert len(pressed) == 1

    controller.send_media_key("next")
    controller.send_media_key("previous")
    controller.send_media_key("stop")

    assert len(pressed) == 4
    assert len(set(pressed)) == 4


def test_media_rejects_unknown_action():
    result = __import__(
        "genesis_os.media_control", fromlist=["MediaController"]
    ).MediaController().send_media_key("eject")

    assert result["success"] is False
    assert result["executed"] is False


def test_volume_set_parses_percent_strings():
    controller = __import__(
        "genesis_os.media_control", fromlist=["MediaController"]
    ).MediaController()

    controller._endpoint = Mock(side_effect=AssertionError("must reject first"))

    result = controller.set_volume(140)

    assert result["success"] is False
    assert result["executed"] is False


def test_volume_set_verifies_by_readback(monkeypatch):
    from genesis_os.media_control import MediaController

    controller = MediaController()

    state = {"percent": 20}

    def fake_endpoint():
        class FakeInterface:
            def GetMasterVolumeLevelScalar(self_inner):
                return state["percent"] / 100.0

            def GetMute(self_inner):
                return False

            def SetMasterVolumeLevelScalar(self_inner, value, ctx):
                state["percent"] = int(round(value * 100))

        return FakeInterface(), None

    monkeypatch.setattr(controller, "_endpoint", fake_endpoint)

    result = controller.set_volume("45%")

    assert result["success"] is True
    assert result["executed"] is True
    assert result["verified"] is True
    assert result["after"] == 45


def test_volume_mute_reports_already_in_desired_state(monkeypatch):
    from genesis_os.media_control import MediaController

    controller = MediaController()

    monkeypatch.setattr(
        controller,
        "get_volume",
        lambda: {"success": True, "volume_percent": 50, "muted": True},
    )

    result = controller.toggle_mute(mute=True)

    assert result["success"] is True
    assert result.get("already_in_desired_state") is True


# =========================================================
# DISPLAY CONTROL
# =========================================================


class _FakeSBC:
    def __init__(self):
        self.levels = [30]

    def get_brightness(self):
        return list(self.levels)

    def set_brightness(self, value):
        self.levels = [int(value)]


def test_brightness_set_verifies_by_readback(monkeypatch):
    from genesis_os.display_control import DisplayController

    controller = DisplayController()
    fake = _FakeSBC()

    monkeypatch.setattr(controller, "_sbc", fake)
    monkeypatch.setattr(controller, "available", True)

    result = controller.set_brightness(70)

    assert result["success"] is True
    assert result["verified"] is True
    assert fake.levels[0] == 70


def test_brightness_step_direction(monkeypatch):
    from genesis_os.display_control import DisplayController

    controller = DisplayController()
    fake = _FakeSBC()
    fake.levels = [50]

    monkeypatch.setattr(controller, "_sbc", fake)
    monkeypatch.setattr(controller, "available", True)

    result = controller.set_brightness(None, direction="down")

    assert result["success"] is True
    assert fake.levels[0] == 40


def test_brightness_rejects_out_of_range_without_execution(monkeypatch):
    from genesis_os.display_control import DisplayController

    controller = DisplayController()
    fake = _FakeSBC()

    monkeypatch.setattr(controller, "_sbc", fake)
    monkeypatch.setattr(controller, "available", True)

    result = controller.set_brightness(150)

    assert result["success"] is False
    assert result["executed"] is False
    assert fake.levels[0] == 30


# =========================================================
# HARDWARE INTELLIGENCE
# =========================================================


def test_battery_report_contract():
    from genesis_os.hardware_intelligence import HardwareIntelligence

    result = HardwareIntelligence().battery()

    # On real machines psutil exists; the contract must hold
    # regardless of whether a battery is physically present.
    if result.get("available") is False:
        pytest.skip("psutil unavailable")

    assert result["success"] is True
    assert result["verified"] is True
    assert (
        result.get("battery_present") is False
        or 0 <= result["battery_percent"] <= 100
    )


def test_system_stats_contract():
    from genesis_os.hardware_intelligence import HardwareIntelligence

    result = HardwareIntelligence().system_stats()

    if result.get("available") is False:
        pytest.skip("psutil unavailable")

    assert result["success"] is True
    assert 0 <= result["cpu_percent"] <= 100
    assert 0 <= result["memory_percent"] <= 100


# =========================================================
# CLIPBOARD
# =========================================================


def test_clipboard_copy_verifies_by_readback(tmp_path):
    from genesis_os.clipboard_manager import ClipboardManager

    manager = ClipboardManager()

    if not manager.available:
        pytest.skip("pyperclip unavailable")

    text = f"Genesis AIOS test {tmp_path.name}"

    result = manager.copy(text)

    assert result["success"] is True
    assert result["verified"] is True

    # The clipboard now really holds our text.
    import pyperclip
    assert pyperclip.paste() == text


def test_clipboard_copy_rejects_empty_text():
    from genesis_os.clipboard_manager import ClipboardManager

    manager = ClipboardManager()
    result = manager.copy("   ")

    assert result["success"] is False
    assert result["executed"] is False


# =========================================================
# SCREEN CAPTURE — REAL EXECUTION
# =========================================================


def test_screenshot_captures_real_verified_image(tmp_path):
    from genesis_os.capture_manager import CaptureManager

    manager = CaptureManager()

    if not manager.available:
        pytest.skip("Pillow unavailable")

    target = tmp_path / "shot.png"
    result = manager.screenshot(str(target))

    assert result["success"] is True
    assert result["verified"] is True
    assert target.exists()
    assert target.stat().st_size >= CaptureManager.MIN_VALID_PNG_BYTES
    assert result["dimensions"][0] > 0


# =========================================================
# AI INTENT RESOLUTION SAFETY
# =========================================================


def test_llm_resolver_rejects_unknown_operation():
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    candidate = LLMIntentResolver(ai_engine=Mock())._validated_candidate(
        "do the thing",
        {"operation": "totally.fake_op", "target": "x"},
    )

    assert candidate is None


@pytest.mark.parametrize(
    "denied_operation",
    ["system.shutdown", "shell.execute", "process.kill"],
)
def test_llm_resolver_never_proposes_denied_operations(denied_operation):
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    candidate = LLMIntentResolver(ai_engine=Mock())._validated_candidate(
        "destroy everything",
        {"operation": denied_operation, "target": "computer"},
    )

    assert candidate is None


def test_llm_candidate_confidence_stays_below_auto_execution():
    from genesis_os.llm_intent_resolver import LLMIntentResolver
    from genesis_os.action_executor import ActionExecutor

    candidate = LLMIntentResolver(ai_engine=Mock())._validated_candidate(
        "make the sound quiet",
        {"operation": "volume.down", "target": "volume"},
    )

    assert candidate is not None
    assert candidate["confidence"] < ActionExecutor.MINIMUM_CONFIDENCE


def test_llm_json_extraction_from_noisy_answer():
    noisy = 'Sure! Here is the JSON:\n```json\n{"operation": "volume.up", "target": "volume", "parameters": {}}\n```\nHope that helps!'

    parsed = __import__(
        "genesis_os.llm_intent_resolver", fromlist=["LLMIntentResolver"]
    ).LLMIntentResolver._extract_json(noisy)

    assert parsed["operation"] == "volume.up"


def test_looks_actionable_gate():
    from genesis_os.llm_intent_resolver import LLMIntentResolver

    assert LLMIntentResolver.looks_actionable("make my screen dimmer") is True
    assert LLMIntentResolver.looks_actionable("hello there friend") is False


@pytest.mark.parametrize(
    "conversational_text",
    [
        # The live-reproduced false positive. The AI intent
        # layer must NEVER be invoked for this input; it
        # contains "make" only in mid-clause conversational
        # position, not in imperative position.
        "hii now i make you able to control my computer",
        # Plain greetings.
        "hello there friend",
        "hi how are you doing today",
        # Subject + verb constructions — verb in object
        # position, not imperative position.
        "you make me happy",
        "i think we should set up a meeting",
        # Question phrasings that mention OS-shaped words
        # without requesting an action. "Can you" is a
        # polite prefix only when followed by an action verb;
        # "can you do something for me" uses "do" which is
        # not in the imperative verb list.
        "can you do something for me",
        # Casual statement about an action-shaped concept
        # (set up a meeting) but in non-imperative form.
        "she set the table before we arrived",
        # Open-ended question about what the system can do.
        "what can you do for me",
    ],
)
def test_conversational_inputs_do_not_look_actionable(
    conversational_text,
):
    """
    Regression: plain conversational inputs must not pass
    the AI intent gate, even when they contain action-shaped
    verbs ("make", "set", "open") in non-imperative position.

    These inputs previously reached the LLM intent resolver
    and produced false-positive capability proposals
    (e.g. "hii now i make you able to control my computer"
    produced "I understood that as: run
    'cleanup.recycle_bin_query'").
    """

    from genesis_os.llm_intent_resolver import LLMIntentResolver

    assert (
        LLMIntentResolver.looks_actionable(
            conversational_text
        )
        is False
    )


@pytest.mark.parametrize(
    "actionable_text",
    [
        # Original true positive from the existing test.
        "make my screen dimmer",
        # Common imperative forms from the live demos.
        "open notepad",
        "please open notepad",
        "can you open chrome",
        "set volume to 40",
        "i want to mute the volume",
        "let me capture the screen",
        "take a screenshot",
        "lock my computer",
        # Greeting + imperative, the natural colloquial
        # form users actually type.
        "hey, open notepad",
    ],
)
def test_actionable_inputs_still_look_actionable(
    actionable_text,
):
    """
    Regression: tightening the gate must NOT over-correct
    into rejecting genuine imperative requests.

    Each input here is a real, known-good actionable phrase
    that the LLM intent layer is supposed to be able to
    resolve to a capability proposal.
    """

    from genesis_os.llm_intent_resolver import LLMIntentResolver

    assert (
        LLMIntentResolver.looks_actionable(
            actionable_text
        )
        is True
    )
