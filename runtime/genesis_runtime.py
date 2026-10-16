from genesis_os.failure_classifier import FailureClassifier, FailureCategory
from runtime.audit import ExecutionAudit
from runtime.models import TaskPhase


class GenesisRuntime:

    def __init__(
        self,
        brain,
        conversation,
        memory,
        ai_engine,
        agent_bridge,
        os_manager=None,
        audit=None,
        action_executor=None,
        workflow_engine=None,
    ):
        self.brain = brain
        self.conversation = conversation
        self.memory = memory
        self.ai_engine = ai_engine
        self.agent_bridge = agent_bridge
        self.os_manager = os_manager

        self.status = "online"

        # Phase 7 lifecycle components
        self._failure_classifier = FailureClassifier()
        self._audit = audit if audit is not None else ExecutionAudit()
        self._workflow_engine = workflow_engine
        self._recovery_engine = None
        self._last_classification_trace_id = None

        if os_manager is not None:
            try:
                from genesis_os.action_executor import ActionExecutor
                from genesis_os.workflow_engine import UniversalDesktopWorkflowEngine
                from genesis_os.recovery_engine import RecoveryEngine

                executor = action_executor or ActionExecutor(os_manager)
                if self._workflow_engine is None:
                    self._workflow_engine = UniversalDesktopWorkflowEngine(
                        action_executor=executor,
                        os_manager=os_manager,
                    )
                self._recovery_engine = RecoveryEngine(os_manager)
            except Exception:
                pass

    @staticmethod
    def _agent_result_is_successful(result):
        if not isinstance(result, dict):
            return False
        if result.get("success") is False or result.get("error"):
            return False
        status = str(result.get("status", "")).strip().lower()
        if status in {"failed", "failure", "error", "cancelled", "rejected"}:
            return False
        if "verified" in result and result.get("verified") is not True:
            return False
        return bool(
            result.get("success") is True
            or status in {"completed", "complete", "ok", "success", "done", "recovered"}
        )


    def get_status(self):

        return {
            "status": self.status,
            "level_1": {
                "brain": self.brain is not None,
                "conversation": self.conversation is not None,
                "memory": self.memory is not None,
                "ai_engine": self.ai_engine is not None,
            },
            "level_2": {
                "agent_bridge": self.agent_bridge is not None,
            }
        }

    # =========================================================
    # REQUEST CLASSIFICATION
    # =========================================================

    def classify(self, user_input):

        import uuid

        task_id = f"classify-{uuid.uuid4().hex[:12]}"
        self._audit.start_trace(task_id, user_input)
        try:
            decision = self.agent_bridge.classify_request(user_input)
        except Exception as exc:
            self._audit.record_phase(
                task_id,
                TaskPhase.FAILED,
                "classification_failed",
                {"error": str(exc)},
            )
            self._audit.complete_trace(
                task_id,
                success=False,
                result={"error": str(exc)},
            )
            raise
        self._audit.record_phase(
            task_id,
            TaskPhase.CLASSIFIED,
            "classification_complete",
            {
                "level": decision.get("level") if isinstance(decision, dict) else None,
                "mode": decision.get("mode") if isinstance(decision, dict) else None,
                "intent": decision.get("intent") if isinstance(decision, dict) else None,
            },
        )
        self._audit.complete_trace(
            task_id,
            success=True,
            result={"classification": decision},
        )
        self._last_classification_trace_id = task_id
        return decision

    def execute_audited(self, goal, operation, executor, plan):
        import uuid

        task_id = f"action-{uuid.uuid4().hex[:12]}"
        self._audit.start_trace(task_id, goal)
        self._audit.record_phase(
            task_id,
            TaskPhase.EXECUTING,
            "action_started",
            {"operation": operation, "plan": plan.to_dict()},
        )
        try:
            result = executor.execute(plan)
        except Exception as exc:
            self._audit.record_phase(
                task_id,
                TaskPhase.FAILED,
                "action_exception",
                {"operation": operation, "error": str(exc)},
            )
            self._audit.complete_trace(
                task_id,
                success=False,
                result={"operation": operation, "error": str(exc)},
            )
            raise
        result_data = result.to_dict() if hasattr(result, "to_dict") else result
        self._audit.record_observation(
            task_id,
            {"operation": operation, "result": result_data},
        )
        verified = bool(
            getattr(result, "verified", False)
            if not isinstance(result, dict)
            else result.get("verified", False)
        )
        trustworthy = bool(
            getattr(result, "trustworthy_success", False)
            if not isinstance(result, dict)
            else result.get("trustworthy_success", verified)
        )
        self._audit.record_verification(
            task_id,
            {
                "verified": trustworthy,
                "provider_verified": verified,
                "reason": (
                    result.get("verification_reason", "")
                    if isinstance(result, dict)
                    else getattr(result, "message", "")
                ),
            },
        )
        self._audit.complete_trace(
            task_id,
            success=trustworthy,
            result=result_data if isinstance(result_data, dict) else {"result": result_data},
        )
        return result

    def execute_mixed_audited(self, goal, executor):
        import uuid

        task_id = f"mixed-{uuid.uuid4().hex[:12]}"
        self._audit.start_trace(task_id, goal)
        self._audit.record_phase(
            task_id,
            TaskPhase.EXECUTING,
            "mixed_objective_started",
            {"objective": goal},
        )
        try:
            result = executor.execute(goal)
        except Exception as exc:
            self._audit.record_phase(
                task_id,
                TaskPhase.FAILED,
                "mixed_objective_exception",
                {"error": str(exc)},
            )
            self._audit.complete_trace(
                task_id,
                success=False,
                result={"error": str(exc)},
            )
            raise

        agent_results = list(getattr(result, "agent_results", []) or [])
        os_results = list(getattr(result, "os_results", []) or [])
        agent_outputs = {}
        for agent_result in agent_results:
            agent_name = agent_result.get("agent", "agent")
            output = None
            for key in (
                "response",
                "code",
                "content",
                "text",
                "findings",
                "analysis",
                "result",
            ):
                value = agent_result.get(key)
                if value not in (None, ""):
                    output = value
                    break
            if output not in (None, ""):
                agent_outputs[agent_name] = output
            self._audit.record_phase(
                task_id,
                TaskPhase.EXECUTING,
                "agent_output",
                {
                    "agent": agent_name,
                    "success": bool(agent_result.get("success")),
                    "output": output,
                },
            )

        for os_result in os_results:
            operation = os_result.get("operation")
            target = os_result.get("target")
            input_content = None
            if operation in {
                "file.create",
                "document.create_pdf",
                "gui.type_text",
                "gui.paste_text",
            }:
                input_content = agent_outputs.get("Coding Agent")
                if input_content is None:
                    input_content = next(
                        iter(agent_outputs.values()),
                        None,
                    )
            self._audit.record_phase(
                task_id,
                TaskPhase.EXECUTING,
                "os_action_started",
                {
                    "operation": operation,
                    "target": target,
                    "input_content": input_content,
                },
            )
            self._audit.record_observation(
                task_id,
                {
                    "operation": operation,
                    "target": target,
                    "result": os_result,
                },
            )
            self._audit.record_verification(
                task_id,
                {
                    "operation": operation,
                    "verified": bool(os_result.get("verified")),
                    "trustworthy_success": bool(
                        os_result.get("trustworthy_success")
                    ),
                },
            )

        success = bool(
            getattr(result, "success", False)
            and getattr(result, "final_verified", False)
        )
        self._audit.complete_trace(
            task_id,
            success=success,
            result={
                "agent_results": agent_results,
                "os_results": os_results,
                "metadata": getattr(result, "metadata", {}),
            },
        )
        return result


    def handle(self, user_input):

        print()
        print("=" * 60)
        print("[GENESIS] REQUEST RECEIVED")
        print("=" * 60)

        print(
            f"[GENESIS] User: {user_input}"
        )

        # -----------------------------------------------------
        # LEVEL 1 — MEMORY
        # -----------------------------------------------------

        print(
            "[LEVEL 1] Checking memory..."
        )

        memory_context = None

        try:

            if self.memory:

                memory_context = (
                    self.memory.get_relevent_memory(
                        user_input
                    )
                )

        except Exception as error:

            print(
                f"[LEVEL 1] Memory lookup unavailable: "
                f"{error}"
            )

        # -----------------------------------------------------
        # LEVEL 1 — BRAIN / ROUTING
        # -----------------------------------------------------

        print(
            "[LEVEL 1] Understanding request..."
        )

        classification = self.classify(
            user_input
        )

        print(
            "[LEVEL 1] Classification:",
            classification["type"]
        )

        # -----------------------------------------------------
        # LEVEL 1 — NORMAL CONVERSATION
        # -----------------------------------------------------

        if classification["type"] == "conversation":

            print(
                "[LEVEL 1] Handling through "
                "conversation pipeline..."
            )

            return self._handle_level_1(
                user_input,
                memory_context
            )

        # -----------------------------------------------------
        # LEVEL 2 — AGENT SYSTEM
        # -----------------------------------------------------

        print(
            "[LEVEL 2] Agentic task detected."
        )

        print(
            "[LEVEL 2] Selected:",
            classification["agent"]
        )

        result = self.agent_bridge.handle(
            user_input
        )

        # -----------------------------------------------------
        # LEVEL 2 → LEVEL 1
        # -----------------------------------------------------

        print(
            "[LEVEL 2] Agent execution completed."
        )

        print(
            "[LEVEL 1] Returning agent result "
            "through Genesis..."
        )

        final_response = self._synthesize(
            user_input,
            result,
            memory_context
        )

        # -----------------------------------------------------
        # MEMORY
        # -----------------------------------------------------

        self._store_if_important(
            user_input,
            final_response
        )

        return {
            "success": self._agent_result_is_successful(result),
            "pipeline": "LEVEL_1 → LEVEL_2 → LEVEL_1",
            "classification": classification,
            "response": final_response,
            "agent_result": result,
        }

    # =========================================================
    # LEVEL 1 CONVERSATION
    # =========================================================

    def _handle_level_1(
        self,
        user_input,
        memory_context
    ):

        # Item 8A: Level 1 conversation now goes through the real L1
        # brain -- Brain.process_request(text) -> str.
        #
        # It did not before. This method probed self.conversation for
        # .respond() and then for .chat(); ConversationEngine defines
        # NEITHER, so both hasattr() checks were false on every call and
        # every conversation-classified request silently returned the
        # placeholder {"message": "Level 1 conversation pipeline is
        # connected."} without ever asking the brain anything. Genesis
        # answered a greeting with a sentence about its own plumbing.
        #
        # memory_context is threaded through untouched so recall keeps
        # flowing into the caller exactly as before.
        response = self._level_1_brain_answer(
            user_input
        )

        return {
            "success": True,
            "pipeline": "LEVEL_1",
            "response": response,
            "memory": memory_context,
        }

    def _level_1_brain_answer(self, user_input):
        """Ask the wired L1 brain for a real answer.

        Returns the brain's answer as-is (a string). When no usable brain
        is present, returns an honest dict explaining why instead of a
        message claiming the pipeline is connected: a missing brain must
        not take the runtime down, and it must not be dressed up as a
        working conversation.
        """

        brain = self.brain

        if brain is None:
            return self._level_1_unavailable(
                "no brain is wired into this runtime"
            )

        process_request = getattr(
            brain,
            "process_request",
            None
        )

        if not callable(process_request):
            return self._level_1_unavailable(
                "the wired brain has no process_request()"
            )

        try:
            answer = process_request(user_input)

        except Exception as error:
            print(
                f"[Genesis] Level 1 brain failed: {error}"
            )
            return self._level_1_unavailable(
                f"the brain raised {type(error).__name__}"
            )

        self._record_level_1_turn(user_input, answer)

        return answer

    def _record_level_1_turn(self, user_input, answer):
        """Record the exchange on the conversation engine, if it can.

        Both recorders are optional and individually guarded. History is
        a convenience, not the answer: a conversation engine that cannot
        store the turn must not discard the reply the brain already
        produced.
        """

        conversation = self.conversation

        if conversation is None:
            return

        for method_name, payload in (
            ("add_user_message", user_input),
            ("add_assistant_message", answer),
        ):
            recorder = getattr(
                conversation,
                method_name,
                None
            )

            if not callable(recorder):
                continue

            try:
                recorder(payload)

            except Exception:
                # Deliberately swallowed: see the docstring. The answer
                # has already been produced and is returned regardless.
                pass

    @staticmethod
    def _level_1_unavailable(reason):
        """The degraded L1 answer.

        Kept as a dict so the shape matches what this method returned
        before Item 8A, which lets existing callers keep reading it
        without a type change on the failure path.
        """

        return {
            "message": (
                f"Level 1 conversation is unavailable: {reason}."
            ),
            "available": False,
            "reason": reason,
        }

    # =========================================================
    # LEVEL 2 RESULT → LEVEL 1 AI
    # =========================================================

    def _synthesize(
        self,
        original_task,
        agent_result,
        memory_context
    ):

        prompt = f"""
You are Genesis.

A Level 2 agent system has completed work for the user.

USER REQUEST:
{original_task}

AGENT RESULTS:
{agent_result}

RELEVANT MEMORY:
{memory_context}

Your job is to return the result as a clear,
natural Genesis response.

Do not mention internal implementation details
unless they are useful to the user.

Do not invent missing facts.

If an agent reports failure or insufficient evidence,
be transparent about it.
"""

        # Item 8B: synthesis now calls the real AI engine method,
        # AIEngine.generate_response(prompt) -> str.
        #
        # It did not before. This method probed self.ai_engine for
        # .generate(), then for .chat(); AIEngine defines NEITHER, so
        # both hasattr() checks were false and control fell straight
        # through to `return agent_result`. The raw agent payload was
        # handed to the user where a natural-language answer belonged,
        # with no synthesis and no error to show for it.
        generate_response = getattr(
            self.ai_engine,
            "generate_response",
            None
        )

        if callable(generate_response):

            try:
                return generate_response(prompt)

            except Exception as error:

                print(
                    f"[Genesis] Synthesis failed: {error}"
                )

        return agent_result

    # =========================================================
    # MEMORY
    # =========================================================

    def _store_if_important(
        self,
        user_input,
        response
    ):

        try:

            if not self.memory:
                return

            if hasattr(
                self.memory,
                "save_if_important"
            ):

                self.memory.save_if_important(
                    user_input
                )

        except Exception as error:

            print(
                f"[Memory] Storage skipped: {error}"
            )

    # =========================================================
    # PHASE 7 — FULL EXECUTION LIFECYCLE
    # =========================================================
    #
    # PRECONDITION  →  ACTION  →  OBSERVE  →  POSTCONDITION  →  VERIFY
    # Failure:       CLASSIFY  →  DIAGNOSE  →  RECOVER  →  OBSERVE  →  VERIFY
    # Invalid plan:  REPLAN
    #
    # This method implements the full spec lifecycle with audit
    # trail integration.  It does NOT replace handle(); it
    # extends it withPhase 7 guarantees.
    # =========================================================

    def execute_with_lifecycle(
        self,
        user_input,
        *,
        workflow_plan=None,
        max_replans: int = 2,
        max_recovery_attempts: int = 3,
    ):
        """
        Execute a user request through the full Phase 7 lifecycle.

        Returns a dict with:
            success: bool
            trace_id: str   (audit trace id)
            phases: list    (ordered phase transitions)
            result: dict    (final outcome)
            recovery: dict  (recovery details if any)
        """
        import uuid

        task_id = f"phase7-{uuid.uuid4().hex[:12]}"
        trace = self._audit.start_trace(task_id, user_input)
        phases_log = []
        completed_steps = []
        recovery_log = []

        def _record_phase(phase: TaskPhase, event: str, details: dict = None):
            self._audit.record_phase(task_id, phase, event, details or {})
            phases_log.append({"phase": phase.value, "event": event})

        # ── PHASE: UNDERSTAND ──────────────────────────────
        _record_phase(TaskPhase.UNDERSTANDING, "request_received", {"input": user_input})

        classification = None
        try:
            classification = self.classify(user_input)
            _record_phase(TaskPhase.CLASSIFIED, "classification_complete", {
                "type": classification.get("type"),
                "agent": classification.get("agent"),
            })
        except Exception as exc:
            _record_phase(TaskPhase.RECOVERING, "classification_failed", {"error": str(exc)})

            # CLASSIFY the failure and attempt RECOVER
            failure_info = self._classify_failure(str(exc), "")
            recovery_log.append({
                "attempt": 1,
                "category": failure_info.category.value,
                "error": str(exc),
                "diagnostic": failure_info.diagnostic,
            })

            if failure_info.retryable:
                _record_phase(TaskPhase.RECOVERING, "retrying_classification", {
                    "category": failure_info.category.value,
                })
                try:
                    classification = self.classify(user_input)
                    _record_phase(TaskPhase.CLASSIFIED, "classification_recovered", {
                        "type": classification.get("type"),
                    })
                except Exception as exc2:
                    _record_phase(TaskPhase.FAILED, "classification_failed_final", {"error": str(exc2)})
                    self._audit.complete_trace(task_id, success=False, result={"error": str(exc2)})
                    return {
                        "success": False,
                        "trace_id": task_id,
                        "phases": phases_log,
                        "result": {"error": f"Classification failed after recovery: {exc2}"},
                        "recovery": recovery_log,
                    }
            else:
                _record_phase(TaskPhase.FAILED, "classification_failed_non_retryable", {"error": str(exc)})
                self._audit.complete_trace(task_id, success=False, result={"error": str(exc)})
                return {
                    "success": False,
                    "trace_id": task_id,
                    "phases": phases_log,
                    "result": {"error": f"Classification failed: {exc}"},
                    "recovery": recovery_log,
                }

        # ── CONVERSATION SHORTCIRCUIT ──────────────────────
        if classification.get("type") == "conversation":
            _record_phase(TaskPhase.EXECUTING, "conversation_pipeline")
            result = self._handle_level_1(user_input, None)
            _record_phase(TaskPhase.COMPLETED, "conversation_complete")
            self._audit.complete_trace(task_id, success=True, result=result)
            return {
                "success": True,
                "trace_id": task_id,
                "phases": phases_log,
                "result": result,
                "recovery": {},
            }

        # ── PHASE: PLAN ────────────────────────────────────
        _record_phase(TaskPhase.PLANNING, "planning_workflow")

        if workflow_plan is None:
            # Delegate to agent bridge for planning
            try:
                agent_result = self.agent_bridge.handle(user_input)
                _record_phase(TaskPhase.EXECUTING, "agent_planning_complete")
            except Exception as exc:
                _record_phase(TaskPhase.REPLANNING, "agent_planning_failed", {"error": str(exc)})
                # Attempt replan
                classification2 = self._classify_failure(str(exc), "")
                if classification2.category == FailureCategory.UNKNOWN:
                    _record_phase(TaskPhase.FAILED, "planning_failed_no_recovery", {"error": str(exc)})
                    self._audit.complete_trace(task_id, success=False, result={"error": str(exc)})
                    return {
                        "success": False,
                        "trace_id": task_id,
                        "phases": phases_log,
                        "result": {"error": f"Planning failed: {exc}"},
                        "recovery": {},
                    }
                _record_phase(TaskPhase.RECOVERING, "retrying_planning", {
                    "category": classification2.category.value,
                })
                try:
                    agent_result = self.agent_bridge.handle(user_input)
                    _record_phase(TaskPhase.EXECUTING, "agent_planning_recovered")
                except Exception as exc2:
                    _record_phase(TaskPhase.FAILED, "planning_failed_final", {"error": str(exc2)})
                    self._audit.complete_trace(task_id, success=False, result={"error": str(exc2)})
                    return {
                        "success": False,
                        "trace_id": task_id,
                        "phases": phases_log,
                        "result": {"error": f"Planning failed after recovery: {exc2}"},
                        "recovery": recovery_log,
                    }

            if not self._agent_result_is_successful(agent_result):
                error = agent_result.get("error") if isinstance(agent_result, dict) else "Agent returned an unverifiable result."
                _record_phase(TaskPhase.FAILED, "agent_result_unverified", {"error": error})
                self._audit.record_verification(
                    task_id,
                    {"verified": False, "reason": error},
                )
                self._audit.complete_trace(
                    task_id,
                    success=False,
                    result={"error": error, "agent_result": agent_result},
                )
                return {
                    "success": False,
                    "trace_id": task_id,
                    "phases": phases_log,
                    "result": {"error": error, "agent_result": agent_result},
                    "recovery": recovery_log,
                }

            # Synthesize result through Level 1
            final_response = self._synthesize(user_input, agent_result, None)
            self._audit.record_verification(
                task_id,
                {
                    "verified": True,
                    "reason": "Agent returned a successful result without an error or negative verification signal.",
                },
            )
            _record_phase(TaskPhase.OBSERVING, "result_synthesized")
            _record_phase(TaskPhase.COMPLETED, "workflow_complete")

            self._audit.complete_trace(task_id, success=True, result={
                "response": final_response,
                "agent_result": agent_result,
            })

            return {
                "success": True,
                "trace_id": task_id,
                "phases": phases_log,
                "result": {
                    "response": final_response,
                    "agent_result": agent_result,
                },
                "recovery": recovery_log,
            }

        # ── PHASE: EXECUTE WORKFLOW PLAN ───────────────────
        _record_phase(TaskPhase.EXECUTING, "executing_workflow_plan", {
            "steps": len(workflow_plan.steps) if hasattr(workflow_plan, "steps") else 0,
        })

        if self._workflow_engine is None:
            _record_phase(TaskPhase.FAILED, "no_workflow_engine")
            self._audit.complete_trace(task_id, success=False, result={
                "error": "No workflow engine available",
            })
            return {
                "success": False,
                "trace_id": task_id,
                "phases": phases_log,
                "result": {"error": "Workflow engine not initialized. Provide os_manager."},
                "recovery": {},
            }

        # Execute through the workflow engine
        exec_result = None
        replan_count = 0
        current_plan = workflow_plan

        while replan_count <= max_replans:
            try:
                exec_result = self._workflow_engine.execute(current_plan)
                break  # Success or non-recoverable failure
            except Exception as exc:
                _record_phase(TaskPhase.RECOVERING, "workflow_execution_exception", {
                    "error": str(exc),
                    "replan_count": replan_count,
                })

                classification = self._classify_failure(str(exc), "")
                recovery_log.append({
                    "attempt": replan_count + 1,
                    "category": classification.category.value,
                    "error": str(exc),
                    "diagnostic": classification.diagnostic,
                })

                self._audit.record_recovery(task_id, {
                    "category": classification.category.value,
                    "error": str(exc),
                    "replan_count": replan_count,
                })

                if not classification.retryable or replan_count >= max_replans:
                    _record_phase(TaskPhase.FAILED, "recovery_exhausted", {
                        "category": classification.category.value,
                    })
                    self._audit.complete_trace(task_id, success=False, result={
                        "error": str(exc),
                        "classification": classification.to_dict(),
                    })
                    return {
                        "success": False,
                        "trace_id": task_id,
                        "phases": phases_log,
                        "result": {
                            "error": str(exc),
                            "classification": classification.to_dict(),
                        },
                        "recovery": recovery_log,
                    }

                replan_count += 1
                _record_phase(TaskPhase.REPLANNING, "attempting_replan", {
                    "category": classification.category.value,
                })

        # ── PHASE: OBSERVE & VERIFY ────────────────────────
        if exec_result is not None:
            if hasattr(exec_result, "trustworthy_success"):
                verified = exec_result.trustworthy_success
            elif isinstance(exec_result, dict):
                verified = exec_result.get("final_verified", False)
            else:
                verified = False

            if verified:
                _record_phase(TaskPhase.VERIFYING, "result_verified")
                _record_phase(TaskPhase.COMPLETED, "lifecycle_complete")
                self._audit.complete_trace(task_id, success=True, result={
                    "result": exec_result.to_dict() if hasattr(exec_result, "to_dict") else str(exec_result),
                })
                return {
                    "success": True,
                    "trace_id": task_id,
                    "phases": phases_log,
                    "result": exec_result.to_dict() if hasattr(exec_result, "to_dict") else str(exec_result),
                    "recovery": recovery_log,
                }
            else:
                _record_phase(TaskPhase.VERIFYING, "verification_failed")
                # Try recovery for verification failure
                classification = self._classify_failure(
                    "Verification failed",
                    workflow_plan.steps[0].plan.operation if hasattr(workflow_plan, "steps") and workflow_plan.steps else "",
                )

                if classification.retryable and replan_count < max_replans:
                    recovery_log.append({
                        "attempt": replan_count + 1,
                        "category": classification.category.value,
                        "error": "verification_failed",
                        "diagnostic": classification.diagnostic,
                    })
                    _record_phase(TaskPhase.RECOVERING, "verification_recovery", {
                        "category": classification.category.value,
                    })
                    replan_count += 1
                    # Continue loop for replan
                else:
                    _record_phase(TaskPhase.FAILED, "verification_failed_final")
                    self._audit.complete_trace(task_id, success=False, result={
                        "result": exec_result.to_dict() if hasattr(exec_result, "to_dict") else str(exec_result),
                    })
                    return {
                        "success": False,
                        "trace_id": task_id,
                        "phases": phases_log,
                        "result": exec_result.to_dict() if hasattr(exec_result, "to_dict") else str(exec_result),
                        "recovery": recovery_log,
                    }

        _record_phase(TaskPhase.FAILED, "lifecycle_incomplete_fallback")
        self._audit.complete_trace(task_id, success=False, result={})
        return {
            "success": False,
            "trace_id": task_id,
            "phases": phases_log,
            "result": {},
            "recovery": recovery_log,
            "error": "Workflow lifecycle ended without a verified result.",
        }

    def _classify_failure(
        self,
        error: str,
        operation: str,
        exception_type: str = "",
        execution_result=None,
    ):
        """Classify a failure using the FailureClassifier."""
        return self._failure_classifier.classify(
            error=error,
            operation=operation,
            exception_type=exception_type,
            execution_result=execution_result,
        )

    def get_audit_trail(self, task_id: str = None):
        """Retrieve audit entries, optionally filtered by task_id."""
        return self._audit.get_entries(task_id=task_id)

    def get_trace(self, task_id: str):
        """Retrieve the full TaskTrace for a completed lifecycle."""
        return self._audit.get_trace(task_id)