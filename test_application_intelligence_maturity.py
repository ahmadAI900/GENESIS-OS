from agents.workflow_decision import WorkflowDecisionEngine


def engine():
    return WorkflowDecisionEngine()


# =========================================================
# OPEN — NATURAL LANGUAGE
# =========================================================

def test_open_chrome():
    decision = engine().decide("open chrome")

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "chrome"


def test_launch_google_chrome():
    decision = engine().decide(
        "please launch google chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "chrome"


def test_start_vscode():
    decision = engine().decide(
        "start vscode for me"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "vscode"


# =========================================================
# CLOSE
# =========================================================

def test_close_chrome():
    decision = engine().decide(
        "close chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.close"
    assert decision["application"] == "chrome"


def test_quit_vscode():
    decision = engine().decide(
        "please quit vscode"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.close"
    assert decision["application"] == "vscode"


# =========================================================
# INSPECTION
# =========================================================

def test_inspect_chrome():
    decision = engine().decide(
        "inspect chrome"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_check_chrome_status():
    decision = engine().decide(
        "check chrome status"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


# =========================================================
# NATURAL STATUS QUESTIONS
# =========================================================

def test_is_chrome_running():
    decision = engine().decide(
        "is chrome running?"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_is_chrome_open():
    decision = engine().decide(
        "is google chrome open?"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_reverse_chrome_running():
    decision = engine().decide(
        "chrome is running"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "chrome"


def test_reverse_vscode_open():
    decision = engine().decide(
        "vscode is open"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.inspect"
    assert decision["application"] == "vscode"


# =========================================================
# FALSE POSITIVE PROTECTION
# =========================================================

def test_chrome_information_is_not_os():
    decision = engine().decide(
        "what is google chrome?"
    )

    assert decision["level"] != 3


def test_chrome_statement_is_not_os():
    decision = engine().decide(
        "chrome is a web browser"
    )

    assert decision["level"] != 3


def test_check_grammar_is_not_os():
    decision = engine().decide(
        "check my grammar"
    )

    assert decision["level"] != 3


def test_check_code_is_not_os():
    decision = engine().decide(
        "check this code"
    )

    assert decision["level"] != 3


def test_run_python_is_not_os():
    decision = engine().decide(
        "run this Python code"
    )

    assert decision["level"] != 3


def test_start_writing_is_not_os():
    decision = engine().decide(
        "start writing my essay"
    )

    assert decision["level"] != 3


def test_open_topic_is_not_os():
    decision = engine().decide(
        "open the discussion about climate change"
    )

    assert decision["level"] != 3


# =========================================================
# SETTINGS
# =========================================================

def test_open_display_settings():
    decision = engine().decide(
        "open display settings"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "system.open_settings"
    assert decision["target"] == "display"


def test_open_settings():
    decision = engine().decide(
        "open settings"
    )

    assert decision["level"] == 3
    assert decision["intent"] == "application.open"
    assert decision["application"] == "settings"


# =========================================================
# SYSTEM SAFETY
# =========================================================

def test_shutdown_is_not_application_close():
    decision = engine().decide(
        "shut down the computer"
    )

    assert decision["level"] != 3


def test_shutdown_windows_is_not_application_close():
    decision = engine().decide(
        "shutdown windows"
    )

    assert decision["level"] != 3


# =========================================================
# UNKNOWN APPLICATION
# =========================================================

def test_unknown_application_does_not_get_guessed():
    decision = engine().decide(
        "open someunknownapplication"
    )

    assert decision["level"] != 3