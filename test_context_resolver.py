"""
Genesis OS — Level 3 Context Resolver Tests.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock

from genesis_os.context_resolver import ContextResolver, ResolvedReference, ResolutionFailure
from genesis_os.session_state import SessionState
from genesis_os.workflow_models import WorkflowState
from genesis_os.os_manager import OSManager


class MockOSManager:
    pass


def test_resolve_active_document():
    """Test resolving 'the file' to active document."""
    session = SessionState(MockOSManager())
    session.set_active_document("/home/user/document.txt")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the file")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value == "/home/user/document.txt"
    assert result.confidence > 0.8
    assert result.source == "session"


def test_resolve_current_folder():
    """Test resolving 'the folder' to current folder."""
    session = SessionState(MockOSManager())
    session.set_current_folder("/home/user/projects")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the folder")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value == "/home/user/projects"
    assert result.confidence > 0.8


def test_resolve_latest_file():
    """Test resolving 'the latest file' to most recent file."""
    session = SessionState(MockOSManager())
    session.add_recent_file("/home/user/old.txt")
    session.add_recent_file("/home/user/new.txt")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the latest file")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value == "/home/user/new.txt"
    assert result.metadata.get("index") == 0


def test_resolve_previous_file():
    """Test resolving 'the previous file' to second most recent."""
    session = SessionState(MockOSManager())
    session.add_recent_file("/home/user/first.txt")
    session.add_recent_file("/home/user/second.txt")
    session.add_recent_file("/home/user/third.txt")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the previous file")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value == "/home/user/second.txt"
    assert result.metadata.get("index") == 1


def test_resolve_browser():
    """Test resolving 'the browser'."""
    session = SessionState(MockOSManager())
    session.update_browser("chrome", url="https://example.com")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the browser")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value["browser_name"] == "chrome"
    assert result.resolved_value["current_url"] == "https://example.com"


def test_resolve_current_application():
    """Test resolving 'the application'."""
    session = SessionState(MockOSManager())
    session.update_application("chrome", process_id=1234, window_title="Google Chrome")

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the application")

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value["name"] == "chrome"
    assert result.resolved_value["process_id"] == 1234


def test_resolve_task_context_this():
    """Test resolving 'this' from task context."""
    session = SessionState(MockOSManager())
    workflow_state = WorkflowState(
        objective="test",
        context={"step:step-1": {"success": True, "target": "file.txt"}},
        completed_steps=["step-1"],
        current_step="step-1",
    )

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("this", workflow_state=workflow_state)

    assert isinstance(result, ResolvedReference)
    assert result.source == "task_context"
    assert result.resolved_value["target"] == "file.txt"


def test_resolve_last_task_result():
    """Test resolving 'the result' from workflow state."""
    session = SessionState(MockOSManager())
    workflow_state = WorkflowState(
        objective="test",
        context={
            "step:step-1": {"success": True, "operation": "file.create"},
            "step:step-2": {"success": True, "operation": "file.move"},
        },
        completed_steps=["step-1", "step-2"],
    )

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the result", workflow_state=workflow_state)

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value["operation"] == "file.move"


def test_resolve_first_result():
    """Test resolving 'the first result'."""
    session = SessionState(MockOSManager())
    workflow_state = WorkflowState(
        objective="test",
        context={
            "step:step-1": {"success": True, "operation": "file.create"},
            "step:step-2": {"success": True, "operation": "file.move"},
        },
        completed_steps=["step-1", "step-2"],
    )

    resolver = ContextResolver(session_state=session)
    result = resolver.resolve("the first result", workflow_state=workflow_state)

    assert isinstance(result, ResolvedReference)
    assert result.resolved_value["operation"] == "file.create"
    assert result.metadata.get("index") == 0


def test_resolve_failure_no_context():
    """Test resolution fails gracefully when no context."""
    resolver = ContextResolver()
    result = resolver.resolve("the file")

    assert isinstance(result, ResolutionFailure)
    assert "No active document" in result.reason
    assert len(result.suggestions) > 0


def test_resolve_unknown_reference():
    """Test unknown reference returns failure with suggestions."""
    resolver = ContextResolver()
    result = resolver.resolve("the unknown thing")

    assert isinstance(result, ResolutionFailure)
    assert "Could not resolve" in result.reason


def test_conversation_entity_recording():
    """Test recording and resolving conversation entities."""
    session = SessionState(MockOSManager())
    resolver = ContextResolver(session_state=session)

    # Record entity from conversation
    resolver.record_conversation_entity({
        "type": "file",
        "value": "/home/user/mentioned.txt",
        "mentioned_in": "user said 'look at mentioned.txt'",
    })

    # Note: compound resolver would need more context to match
    # This tests the recording mechanism works
    assert len(resolver._conversation_entities) == 1
    assert resolver._conversation_entities[0]["value"] == "/home/user/mentioned.txt"


def test_session_state_serialization():
    """Test session state can be serialized."""
    session = SessionState(MockOSManager())
    session.set_current_folder("/home/user")
    session.set_active_document("/home/user/test.txt")
    session.update_application("chrome", process_id=1234)
    session.add_recent_file("/home/user/old.txt")

    data = session.to_dict()

    assert data["current_folder"] == "/home/user"
    assert data["active_document"] == "/home/user/test.txt"
    assert "chrome" in data["applications"]
    assert len(data["recent_files"]) == 2  # active doc + explicit add


def test_session_state_clear():
    """Test session state clear."""
    session = SessionState(MockOSManager())
    session.set_current_folder("/home/user")
    session.set_active_document("/home/user/test.txt")

    session.clear()

    assert session.get_current_folder() is None
    assert session.get_active_document() is None
    assert len(session._applications) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])