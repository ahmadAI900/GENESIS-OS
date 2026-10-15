"""Genesis OS — hardened common Level 2 agent contract."""
from __future__ import annotations
from time import perf_counter
from typing import Any


class BaseAgent:
    VERSION = "2.5.0"

    def __init__(self, name, description, capabilities=None):
        self.name = str(name)
        self.description = str(description)
        self.capabilities = list(capabilities or [])
        self.status = "idle"
        self.last_error = None
        self.last_duration_ms = 0.0

    def start(self):
        self.status = "working"

    def stop(self):
        self.status = "idle"

    def can_handle(self, task):
        raise NotImplementedError

    def create_result(self, task, response=None, success=True, metadata=None, error=None):
        data = {
            "agent": self.name,
            "task": task,
            "success": bool(success),
            "response": response,
            "metadata": dict(metadata or {}),
        }
        data["metadata"].setdefault("agent_version", self.VERSION)
        data["metadata"].setdefault("duration_ms", self.last_duration_ms)
        if error is not None:
            data["error"] = str(error)
        return data

    def run(self, task):
        raise NotImplementedError(f"{self.name} must implement run()")

    def execute(self, task, context=None):
        self.start()
        started = perf_counter()
        try:
            result = self.run(task, context) if context is not None else self.run(task)
            if not isinstance(result, dict):
                result = self.create_result(task, response=result, success=True)
            result.setdefault("agent", self.name)
            result.setdefault("task", task)
            result.setdefault("success", True)
            result.setdefault("metadata", {})
            self.last_error = None
            return result
        except Exception as exc:
            self.last_error = str(exc)
            return self.create_result(task, response=None, success=False, error=exc,
                                      metadata={"failure_stage": "execution"})
        finally:
            self.last_duration_ms = round((perf_counter() - started) * 1000, 3)
            self.status = "idle"

    def get_info(self):
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "status": self.status,
            "version": self.VERSION,
            "last_error": self.last_error,
            "last_duration_ms": self.last_duration_ms,
        }
