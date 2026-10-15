from agents.base_agent import BaseAgent
from ai.ai_engine import AIEngine


class SecurityAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Security Agent",
            description=(
                "Analyzes software, code, systems, and workflows "
                "for security risks and recommends defensive improvements."
            ),
            capabilities=[
                "security_analysis",
                "vulnerability_detection",
                "security_auditing",
                "threat_analysis",
                "secure_coding",
                "risk_assessment",
                "security_recommendations"
            ]
        )

        self.ai = ai_engine or AIEngine()

    # ==========================================
    # CAPABILITY DETECTION
    # ==========================================

    def can_handle(self, task):

        keywords = [
            "security",
            "secure",
            "vulnerability",
            "vulnerabilities",
            "security audit",
            "security analysis",
            "threat",
            "risk",
            "attack",
            "exploit",
            "secure code",
            "security review",
    
            # General Security Terms
            "security",
            "secure",
            "vulnerability",
            "vulnerabilities",
            "security audit",
            "security analysis",
            "threat",
            "risk",
            "attack",
            "exploit",
            "secure code",
            "security review",
            "penetration",
            "pen test",
            "hardening",
            "remediation",
            "cve",

            # Common Vulnerabilities & Attack Vectors
            "injection",
            "sqli",
            "xss",
            "csrf",
            "ssrf",
            "rce",
            "buffer overflow",
            "deserialization",
            "privilege escalation",
            "zero-day",
            "malware",
            "backdoor",

            # Authentication & Authorization
            "auth",
            "authentication",
            "authorization",
            "permission",
            "access control",
            "jwt",
            "token",
            "rbac",
            "session hijacking",
            "oauth",

            # Cryptography & Data Protection
            "encryption",
            "decryption",
            "crypto",
            "hash",
            "hashing",
            "salt",
            "cipher",
            "tls",
            "ssl",
            "secret",
            "credential",
            "leak",

            # Defensive & Code Audit Terms
            "sanitize",
            "sanitization",
            "input validation",
            "owasp",
            "static analysis",
            "sast",
            "dast",
            "patch",
            "firewall"

        ]

        task_lower = task.lower()

        return any(
            keyword in task_lower
            for keyword in keywords
        )

    # ==========================================
    # SECURITY ANALYSIS
    # ==========================================

    def run(self, task, context=None):

        print(
            f"[Security Agent] Analyzing: {task}"
        )

        # --------------------------------------
        # SHARED CONTEXT
        # --------------------------------------

        context_information = ""

        if context:

            previous_results = context.get_results()

            if previous_results:

                context_information = f"""
Previous agent results are available in shared context.

Use them only when relevant to the security task.

Shared context:
{previous_results}
"""

        # --------------------------------------
        # LEVEL 2.5 — REAL PASSWORD ANALYSIS
        #
        # When a password strength check is requested, run the
        # DETERMINISTIC entropy/pattern tool first and give the
        # AI the real measurements.
        # --------------------------------------

        password_report = ""
        tool_metadata = {}

        try:
            from agents.agent_tools import password_strength
            import re as _re

            password_match = _re.search(
                r"password(?:\s+strength)?[:\s]+[\"']?(?P<pw>\S+)[\"']?",
                task,
                _re.IGNORECASE,
            )

            if (
                password_match
                and "strength" in task.lower()
                or (password_match and "check" in task.lower())
            ):
                analysis = password_strength(
                    password_match.group("pw")
                )

                if analysis.get("success"):
                    tool_metadata["password_analysis"] = {
                        key: value
                        for key, value in analysis.items()
                        if key != "operation"
                    }

                    password_report = (
                        "\nDETERMINISTIC PASSWORD MEASUREMENTS "
                        "(already computed — treat as ground "
                        "truth):\n"
                        f"- verdict: {analysis['verdict']} "
                        f"({analysis['score']}/100)\n"
                        f"- length: {analysis['length']}\n"
                        f"- charset entropy: "
                        f"{analysis['charset_entropy_bits']} bits\n"
                        + (
                            "- issues: "
                            + "; ".join(analysis["issues"])
                            + "\n"
                            if analysis["issues"]
                            else "- no structural issues detected\n"
                        )
                    )

        except Exception as tool_error:
            tool_metadata["tool_error"] = str(tool_error)

        # --------------------------------------
        # SECURITY PROMPT
        # --------------------------------------

        prompt = f"""
You are Genesis Security Agent.

Your job is to analyze software, code, systems,
architectures, workflows, and technical plans for
security risks.

User task:

{task}

{password_report}{context_information}

Perform a defensive security analysis.

Look for issues such as:

- Authentication weaknesses
- Authorization problems
- Input validation problems
- Injection vulnerabilities
- Unsafe file handling
- Sensitive information exposure
- Insecure API usage
- Weak secrets management
- Dependency risks
- Access-control problems
- Data protection problems
- Configuration weaknesses
- Common software security mistakes

For every important issue:

1. Identify the security concern.
2. Explain why it matters.
3. Estimate its severity when possible.
4. Explain the potential impact.
5. Recommend a defensive mitigation.

Rules:

- Do not invent vulnerabilities that are not supported
  by the information provided.
- Clearly distinguish confirmed issues from potential risks.
- Do not claim that a system is secure without sufficient
  evidence.
- Prefer defensive recommendations.
- If insufficient information is provided, explicitly
  state what additional information is required.
- Keep the analysis technically useful and clear.
"""

        print(
            "[Security Agent] Sending analysis to AI Engine..."
        )

        response = self.ai.generate_response(
            prompt
        )

        # --------------------------------------
        # RETURN STANDARD GENESIS RESULT
        # --------------------------------------

        return self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                "operation": "security_analysis",
                **tool_metadata,
            }
        )

    # ==========================================
    # UNIVERSAL AGENT INTERFACE
    # ==========================================

    def execute(self, task, context=None):

        self.start()

        try:

            result = self.run(
                task,
                context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()