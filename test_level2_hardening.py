from agents.agent_registry import AgentRegistry
from agents.base_agent import BaseAgent


class A(BaseAgent):
    def __init__(self, value=True):
        super().__init__('A', 'test', ['x'])
        self.value = value
    def can_handle(self, task):
        return self.value and task == 'x'
    def run(self, task):
        return self.create_result(task, 'ok')


class Broken(BaseAgent):
    def __init__(self): super().__init__('Broken', 'test')
    def can_handle(self, task): raise RuntimeError('boom')
    def run(self, task): raise RuntimeError('boom')


def test_registry_only_returns_capable_agents():
    r = AgentRegistry(); r.register(A()); r.register(Broken())
    assert [a.name for a in r.find_capable_agents('x')] == ['A']
    assert r.find_capable_agents('not-x') == []


def test_base_agent_converts_execution_exception_to_safe_result():
    result = Broken().execute('anything')
    assert result['success'] is False
    assert result['agent'] == 'Broken'
    assert result['error'] == 'boom'
