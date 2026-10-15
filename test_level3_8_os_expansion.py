from unittest.mock import Mock
from genesis_os.action_executor import ActionExecutor
from genesis_os.action_plan import ActionPlan
from genesis_os.capability_registry import CapabilityRegistry
from genesis_os.execution_safety import ExecutionSafety


def test_csv_is_spreadsheet():
    from genesis_os.file_intelligence.file_registry import FileTypeRegistry
    assert FileTypeRegistry().resolve('.csv').name == 'spreadsheet'


def test_file_delete_requires_confirmation():
    result = ActionExecutor(Mock()).execute(ActionPlan(
        operation='file.delete', target='important.txt', confidence=0.99,
    ))
    assert result.success is False
    assert result.status == 'confirmation_required'
    assert result.executed is False
    assert result.error is not None


def test_file_delete_with_grant_reaches_manager():
    """file.delete is Tier 1 (irreversible_or_outward).

    It used to reach the manager on ``parameters={'confirmed': True}``.
    That channel is forgeable -- it travelled inside ``parameters``,
    which is model-controlled JSON -- so the executor now requires an
    AuthorizationGrant, which cannot be minted without a real,
    argument-hash-bound, single-use approval. This test drives the
    grant path directly at the executor, bypassing the adapter gate so
    the executor's own check is what is under test.
    """
    from genesis_os.action_plan import attach_authorization
    from genesis_os.approval_store import ApprovalStore
    from genesis_os.authorization_grant import issue_authorization_grant

    os_manager = Mock()
    os_manager.delete_file.return_value = {
        'success': True, 'operation': 'file.delete',
            'executed': True, 'verified': True,
            'file_exists': False,
            'message': 'deleted',
    }
    token = ApprovalStore.issue_token(
        "file.delete", {"path": "important.txt"}
    )
    ApprovalStore.get_default().approve(token.rsplit(":", 1)[1])
    grant = issue_authorization_grant(
        operation="file.delete",
        arguments={"path": "important.txt"},
        token=token,
    )
    plan = attach_authorization(
        ActionPlan(
            operation='file.delete', target='important.txt',
            confidence=0.99, parameters={'path': 'important.txt'},
        ),
        grant,
        arguments={"path": "important.txt"},
    )
    result = ActionExecutor(os_manager).execute(plan)
    assert result.success is True
    assert result.status == 'verified'
    os_manager.delete_file.assert_called_once()


def test_file_delete_without_a_grant_is_blocked():
    """The counterpart: a Tier 1 plan with NO grant never reaches the
    manager, and ``confirmed: True`` alone does not help."""
    os_manager = Mock()
    result = ActionExecutor(os_manager).execute(ActionPlan(
        operation='file.delete', target='important.txt', confidence=0.99,
        parameters={'path': 'important.txt', 'confirmed': True},
    ))
    assert result.success is False
    assert result.status == 'confirmation_required'
    os_manager.delete_file.assert_not_called()


def test_file_read_is_registered_and_safe():
    decision = ExecutionSafety.check('file.read')
    assert decision.allowed is True
    assert decision.status == 'supported'


def test_system_shutdown_remains_denied():
    decision = ExecutionSafety.check('system.shutdown')
    assert decision.allowed is False
    assert decision.status == 'denied'


def test_capability_registry_has_desktop_surface():
    operations = set(CapabilityRegistry.operations())
    assert 'file.inspect' in operations
    assert 'folder.inspect' in operations
    assert 'browser.search' in operations
    assert 'network.connect_wifi' in operations
    assert 'spreadsheet.sort' in operations
    assert 'document.create_docx' in operations


def test_desktop_workflow_stops_at_confirmation():
    from genesis_os.desktop_workflow import DesktopWorkflowExecutor
    os_manager = Mock()
    os_manager.inspect_application.return_value = {
        "success": True, "operation": "application.inspect",
        "application": "chrome", "message": "ok",
        "executed": False, "verified": True,
        "running": True,
    }
    workflow = DesktopWorkflowExecutor(ActionExecutor(os_manager))
    result = workflow.execute([
        ActionPlan(operation='application.inspect', target='chrome'),
        ActionPlan(operation='file.delete', target='important.txt'),
    ])
    assert result['success'] is False
    assert result['status'] == 'confirmation_required'
    assert len(result['steps']) == 2
    os_manager.inspect_application.assert_called_once_with('chrome')


def test_application_list_is_registered_and_read_only():
    decision = ExecutionSafety.check("application.list")
    assert decision.allowed is True
    assert decision.status == "supported"


def test_process_intelligence_is_registered_and_safe():
    assert ExecutionSafety.check("process.list").allowed is True
    assert ExecutionSafety.check("process.inspect").allowed is True


def test_process_kill_remains_denied():
    decision = ExecutionSafety.check("process.kill")
    assert decision.allowed is False
    assert decision.status == "denied"


def test_application_list_dispatches_without_target_execution():
    os_manager = Mock()
    os_manager.list_applications.return_value = {
        "success": True,
        "operation": "application.list",
        "applications": [],
        "count": 0,
        "executed": False,
        "verified": True,
    }
    result = ActionExecutor(os_manager).execute(ActionPlan(
        operation="application.list", target="computer", confidence=0.99,
    ))
    assert result.success is True
    assert result.status == "verified"
    os_manager.list_applications.assert_called_once_with()


def test_process_inspect_dispatches_to_read_only_manager():
    os_manager = Mock()
    os_manager.inspect_process.return_value = {
        "success": True,
        "operation": "process.inspect",
        "name": "chrome.exe",
        "running": False,
        "pids": [],
        "count": 0,
        "executed": False,
        "verified": True,
    }
    result = ActionExecutor(os_manager).execute(ActionPlan(
        operation="process.inspect", target="chrome.exe", confidence=0.99,
    ))
    assert result.success is True
    assert result.status == "verified"
    os_manager.inspect_process.assert_called_once_with("chrome.exe")


def test_process_list_dispatches_without_mutation():
    os_manager = Mock()
    os_manager.list_processes.return_value = {
        "success": True,
        "operation": "process.list",
        "processes": [],
        "count": 0,
        "executed": False,
        "verified": True,
    }
    result = ActionExecutor(os_manager).execute(ActionPlan(
        operation="process.list", target="computer", confidence=0.99,
    ))
    assert result.success is True
    assert result.status == "verified"
    os_manager.list_processes.assert_called_once_with(None, limit=500)
