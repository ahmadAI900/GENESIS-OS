import importlib
import inspect
import os

from .base_agent import BaseAgent


class AgentDiscovery:
    """Enumerate and instantiate every concrete BaseAgent in a package.

    Loads every ``.py`` file in the package with ``importlib``, because the
    agents are discovered rather than registered: adding a new agent is
    adding a file, and no list has to be kept in step.
    """

    def __init__(self, package="agents"):
        self.package = package
        # Modules that failed to import, and agent classes that failed to
        # instantiate. Both are surfaced by ``GenesisOS.show_startup()``.
        #
        # Before this existed, a load failure printed one line to stdout and
        # the run continued with a silently reduced roster - and the startup
        # banner still said "Agent Discovery ... ONLINE". A capability that
        # disappears with no error anywhere is indistinguishable from a
        # capability that was never written.
        self.import_failures = []
        self.init_failures = []

    def discover(self, ai_engine=None):
        """Discover and instantiate every concrete BaseAgent
        subclass under ``self.package``.

        Pass a shared ``ai_engine`` (e.g. a single
        ``AIEngine()`` constructed at boot) so all agents
        share one AI client and one ``.env`` load. The
        parameter is optional; agents that take ``ai_engine``
        in their constructor fall back to creating their own
        when called without an argument.

        Every failure is recorded and printed. A module that
        cannot be imported is reported with the exception, not
        skipped; a class that cannot be constructed is reported
        by name. ``import_failures`` and ``init_failures`` hold
        ``(name, message)`` pairs for the startup banner.
        """
        discovered_agents = []

        package_path = os.path.dirname(__file__)

        for filename in os.listdir(package_path):
            if not filename.endswith(".py"):
                continue
            if filename.startswith("_"):
                continue
            if filename == "agent_discovery.py":
                continue

            module_name = filename[:-3]

            try:
                module = importlib.import_module(
                    f"{self.package}.{module_name}"
                )
            except Exception as error:
                self.import_failures.append(
                    (module_name, f"{type(error).__name__}: {error}")
                )
                print(
                    f"[Agent Discovery] ERROR loading "
                    f"{self.package}.{module_name}: "
                    f"{type(error).__name__}: {error}"
                )
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if not issubclass(obj, BaseAgent):
                    continue
                if obj is BaseAgent:
                    continue
                if obj.__module__ != module.__name__:
                    continue

                # Prefer the shared ai_engine when the constructor
                # accepts one. Older agents take no arguments and are
                # constructed directly; a constructor that rejects the
                # parameter is retried without it.
                agent = None
                error = None
                try:
                    signature = inspect.signature(obj.__init__)
                except (TypeError, ValueError):
                    signature = None

                if signature is not None and "ai_engine" in \
                        signature.parameters:
                    try:
                        agent = obj(ai_engine=ai_engine)
                    except Exception as first_error:
                        error = first_error
                        try:
                            agent = obj()
                        except Exception as second_error:
                            error = second_error
                            agent = None
                else:
                    try:
                        agent = obj()
                    except Exception as direct_error:
                        error = direct_error
                        agent = None

                if agent is None:
                    self.init_failures.append(
                        (obj.__name__,
                         f"{type(error).__name__}: {error}")
                    )
                    print(
                        f"[Agent Discovery] ERROR initialising "
                        f"{obj.__name__}: {type(error).__name__}: {error}"
                    )
                    continue

                discovered_agents.append(agent)
                print(
                    "[Agent Discovery] Found:",
                    agent.name
                )

        return discovered_agents
