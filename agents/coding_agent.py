from .base_agent import BaseAgent
from ai.ai_engine import AIEngine


class CodingAgent(BaseAgent):

    def __init__(self, ai_engine=None):

        super().__init__(
            name="Coding Agent",
            description="Helps users write, understand, debug, and improve code.",
            capabilities=[
                "coding",
                "code_generation",
                "debugging",
                "code_review",
                "refactoring",
                "documentation",
                "testing",
                "security_analysis",
                "bug",
                "error in code",
                "code"
            ]
        )

        self.ai = ai_engine or AIEngine()

    def can_handle(self, task):

        keywords = [
            # Programming
            "code",
            "coding",
            "program",
            "programming",
            "python",
            "javascript",
            "java",
            "c++",
            "software",

        # Development
            "software development",
            "developer",
            "development",
            "implementation",
            "algorithm",
            "function",
            "class",

            # Debugging
            "debug",
            "bug",
            "error",
            "fix",
            "traceback",

            # Code quality
            "review code",
            "code review",
            "refactor",
            "refactoring",
            "improve code",
            "code quality",

            # Testing
            "test code",
            "generate tests",
            "unit test",
            "testing",

            # Documentation
            "document code",
            "code documentation",
            "documentation",

        # Security
            "code security",
            "security analysis",
            "security vulnerability",
            "vulnerability",
            "coding",
            "debugging",
            "code_review",
            "code_generation",
            "refactoring",
            "documentation",
            "testing",
            "security_analysis"
        ]

        task = task.lower()

        return any(
            keyword in task
            for keyword in keywords
        )

    def run(self, task, context=None):

        print(
            f"[Coding Agent] Working on: {task}"
        )

        prompt = f"""
You are Genesis Coding Agent, a professional AI software engineering assistant.

USER REQUEST:
{task}

Your job is to solve the programming task systematically.

First determine:

1. TASK TYPE
   - Code generation
   - Code explanation
   - Debugging
   - Code review
   - Refactoring
   - Testing
   - Other

2. PROGRAMMING LANGUAGE

3. REQUIREMENTS

4. IMPORTANT EDGE CASES

Then produce the solution.

Your response MUST use this structure:

## Task Analysis

Explain what the user is asking for.

## Task Type

State the type of programming task.

## Language

State the programming language.

## Requirements

List the requirements you identified.

## Solution

Provide complete, clean, readable code.

## Explanation

Explain the important parts of the solution.

## Edge Cases

Identify possible problems and how they are handled.

## Test Cases

Provide useful test cases and expected results.

## How to Run

Explain how the user can run the code.

## Improvements

Suggest practical improvements that could be added later.

IMPORTANT RULES:

- Do not invent libraries or APIs.
- Prefer standard libraries when appropriate.
- Do not claim that you executed the code.
- Do not claim that you tested the code.
- Do not modify the user's files.
- Do not assume access to the user's computer.
- If requirements are ambiguous, make a reasonable assumption and clearly state it.
- Keep generated code readable and maintainable.
- Think like a professional software engineer, not just a code generator.
"""

        print(
            "[Coding Agent] Generating code..."
        )

        response = self.ai.generate_response(
            prompt
        )

        # ==========================================
        # LEVEL 2.5 — REAL ARTIFACTS
        #
        # Extract generated code, SAVE it as a real file and
        # syntax-verify Python output. The agent no longer
        # just talks about code.
        # ==========================================

        from agents.agent_tools import (
            AgentWorkspace,
            extract_code_blocks,
            choose_extension,
            syntax_check_python,
        )

        try:

            if not hasattr(self, "workspace"):
                self.workspace = AgentWorkspace()

            blocks = extract_code_blocks(response)

            artifact_line = None
            syntax_note = None

            if blocks:
                extension = choose_extension(
                    [lang for lang, _ in blocks],
                    task,
                )

                language_hint = (
                    [lang for lang, _ in blocks][0]
                    or extension.lstrip(".")
                )

                saved = self.workspace.save_text_artifact(
                    kind="Code",
                    base_name=task,
                    content=blocks[0][1],
                    extension=extension,
                )

                if saved.get("success"):
                    artifact_line = (
                        f"\n\n---\n💾 **Saved to:** `{saved['path']}`"
                    )

                    if extension == ".py":
                        check = syntax_check_python(blocks[0][1])

                        syntax_note = (
                            "Python syntax check: PASSED ✅"
                            if check["ok"]
                            else f"Python syntax check FAILED ❌ ({check['error']})"
                        )

                        artifact_line += (
                            f"\n🧪 {syntax_note}"
                        )

                    print(
                        "[Coding Agent] Code artifact saved:",
                        saved["path"],
                    )

            if artifact_line:
                response = response + artifact_line

            artifact_metadata = {
                "artifact_saved": bool(artifact_line),
                "artifact_syntax_ok": (
                    None
                    if syntax_note is None
                    else syntax_note.startswith("Python syntax check: PASSED")
                ),
            }

        except Exception as tool_error:

            artifact_metadata = {
                "artifact_saved": False,
                "tool_error": str(tool_error),
            }

        result = self.create_result(
            task=task,
            response=response,
            success=True,
            metadata={
                "operation": "analysis",
                **artifact_metadata,
            }
        )

        return result
    

    def debug(self, code, error):

        self.start()

        print("[Coding Agent] Debugging code...")
        print("[Coding Agent] Analyzing error...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional Python debugger.

The user provided this code:

{code}

The program produced this error:

{error}

Analyze the problem carefully.

Return the result using this structure:

## Error Analysis

Identify the error type and explain what it means.

## Root Cause

Explain the most likely cause of the error.

## Problematic Code

Show the specific part of the code responsible.

## Corrected Code

Provide the corrected complete code.

## Explanation of Fix

Explain exactly what was changed and why.

## Prevention

Explain how the developer can avoid this error in the future.

## Test Case

Provide a test that verifies the fix.

IMPORTANT:

- Do not claim that you executed the code.
- Do not claim that you tested the code.
- If the provided information is insufficient, clearly say what is missing.
- Do not invent a traceback that was not provided.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "error": error,
            "response": response
        }

        return result

    def review(self, code):

        self.start()

        print("[Coding Agent] Reviewing code...")
        print("[Coding Agent] Analyzing code quality...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional senior software engineer.

The user provided the following code:

{code}

Perform a professional code review.

Analyze the code for:

1. Correctness
2. Bugs
3. Security vulnerabilities
4. Performance problems
5. Maintainability
6. Readability
7. Architecture and design
8. Error handling
9. Testing
10. Possible improvements

Return the review using exactly this structure:

## Code Review Summary

Give a concise overview of the code and its overall quality.

## Quality Score

Give a score from 1 to 10.

Explain why you gave this score.

## Bugs

Identify actual bugs or logic problems.

If there are no obvious bugs, say:

No obvious bugs identified.

## Security

Identify security vulnerabilities or risks.

If there are no obvious security issues, say:

No obvious security issues identified.

## Performance

Identify inefficient operations or performance concerns.

If there are no significant performance problems, say:

No significant performance issues identified.

## Maintainability

Explain how easy the code is to maintain and extend.

## Readability

Evaluate:

- Naming
- Structure
- Formatting
- Clarity

## Architecture

Evaluate the overall design and separation of responsibilities.

## Error Handling

Identify missing or weak error handling.

## Testing

Recommend important test cases that should exist.

## Recommended Improvements

Organize recommendations as:

Priority 1 - Critical
Priority 2 - Important
Priority 3 - Nice to have

## Improved Version

Provide an improved version of the code if improvements are necessary.

IMPORTANT RULES:

- Do not invent bugs.
- Clearly distinguish bugs from optional improvements.
- Do not claim that you executed the code.
- Do not claim that you tested the code.
- Do not claim that the code is secure without sufficient evidence.
- Be precise.
- Think like a professional senior software engineer.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "response": response
        }

        return result

    def generate_tests(self, code):

        self.start()

        print("[Coding Agent] Generating tests...")
        print("[Coding Agent] Analyzing code for test cases...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional software testing engineer.

The user provided the following code:

{code}

Your task is to generate a comprehensive automated test suite for this code.

Analyze the code first and determine:

1. Functions
2. Inputs
3. Expected outputs
4. Normal behavior
5. Edge cases
6. Invalid inputs
7. Error conditions
8. Boundary conditions

Generate tests using pytest.

Return the result using EXACTLY this structure:

## Test Analysis

Explain what parts of the code should be tested.

## Testing Strategy

Explain the testing approach.

## Test Cases

List the important test cases and what each one verifies.

## Generated Tests

Provide a complete pytest test file.

The generated test code must:

- Import the required functions from the user's code when possible.
- Use pytest.
- Contain clear test function names.
- Test normal cases.
- Test edge cases.
- Test invalid inputs where appropriate.
- Test expected exceptions where appropriate.
- Avoid testing behavior that cannot be determined from the provided code.

## Edge Cases

List important edge cases that should be tested.

## Additional Recommendations

Suggest additional tests that would be useful in a real project.

IMPORTANT RULES:

- Do not claim that you executed the tests.
- Do not claim that the tests passed.
- Do not invent behavior that is not supported by the provided code.
- Do not invent external dependencies.
- If the code is incomplete, clearly explain what is missing.
- Make the tests practical and runnable.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "response": response
        }

        return result

    def refactor(self, code):

        self.start()

        print("[Coding Agent] Refactoring code...")
        print("[Coding Agent] Analyzing code structure...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional senior software engineer.

The user provided the following code:

{code}

Your task is to refactor this code professionally.

The goal is to improve the code while preserving its intended behavior.

Analyze the code for:

1. Poor naming
2. Duplicate code
3. Unnecessary complexity
4. Poor structure
5. Missing type hints where useful
6. Missing documentation where useful
7. Poor error handling
8. Code smells
9. Maintainability problems
10. Readability problems

Return the result using EXACTLY this structure:

## Refactoring Summary

Briefly explain what is wrong with the original code.

## Code Quality Problems

List the specific problems found.

If no significant problems are found, say:

No significant code quality problems identified.

## Refactoring Strategy

Explain how the code should be improved.

## Refactored Code

Provide the complete improved code.

## Changes Made

Explain the important changes made to the code.

## Behavior Preservation

Explain whether the intended behavior was preserved.

Do not invent functionality that was not present in the original code.

## Additional Recommendations

Suggest further improvements that could be useful in a production project.

IMPORTANT RULES:

- Preserve the original intended behavior.
- Do not remove functionality without explaining why.
- Do not invent external dependencies.
- Do not claim that you executed the code.
- Do not claim that you tested the code.
- Do not claim that the refactored code is bug-free.
- Do not make unnecessary changes simply for style.
- If the code is incomplete, clearly explain what is missing.
- Prefer simple, readable, maintainable Python.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "response": response
        }

        return result

    def document(self, code):

        self.start()

        print("[Coding Agent] Documenting code...")
        print("[Coding Agent] Analyzing code structure...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional senior software engineer and technical documentation specialist.

The user provided the following code:

{code}

Your task is to analyze the code and create professional documentation for it.

The documentation must accurately describe the existing code.

Do NOT change the intended behavior of the code.

Analyze:

1. Module purpose
2. Functions
3. Classes
4. Parameters
5. Return values
6. Exceptions
7. Important logic
8. Dependencies
9. Usage
10. Potential documentation gaps

Return the result using EXACTLY this structure:

## Documentation Summary

Explain what the code does and what its main purpose is.

## Module Documentation

Provide a professional module-level description.

## Functions

For every function, provide:

- Function name
- Purpose
- Parameters
- Parameter types when they can be determined
- Return value
- Return type when it can be determined
- Exceptions when applicable
- Important behavior

## Classes

For every class, provide:

- Class purpose
- Important attributes
- Methods
- Method responsibilities

If there are no classes, say:

No classes identified.

## Dependencies

List the modules and libraries used by the code.

If there are no external dependencies, say:

No external dependencies identified.

## Documented Code

Provide the complete original code with professional docstrings added.

IMPORTANT:

- Preserve the original logic.
- Do not refactor the code.
- Do not rename functions or variables.
- Do not add functionality.
- Do not remove functionality.
- Do not invent parameters.
- Do not invent return values.
- Do not claim that you executed the code.
- Do not claim that you tested the code.
- Clearly state when something cannot be determined from the provided code.

## Usage Example

Provide a simple example showing how the documented code can be used.

Only use behavior supported by the provided code.

## Documentation Recommendations

Identify any documentation that should be added in a larger production project.

"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "response": response
        }

        return result

    def security_scan(self, code):

        self.start()

        print("[Coding Agent] Running security analysis...")
        print("[Coding Agent] Scanning for vulnerabilities...")

        prompt = f"""
You are Genesis Coding Agent acting as a professional defensive security code reviewer.

The user provided the following code:

{code}

Perform a defensive security analysis of this code.

Identify security vulnerabilities, unsafe programming practices, and potential attack surfaces.

Analyze for:

1. Hardcoded secrets
2. API keys and passwords
3. SQL injection
4. Command injection
5. Path traversal
6. Unsafe file operations
7. eval() and exec()
8. Unsafe deserialization
9. Weak authentication
10. Weak authorization
11. Sensitive information exposure
12. Insecure cryptography
13. Missing input validation
14. Unsafe network operations
15. Dangerous dependencies when they are visible from the code

Return the result using EXACTLY this structure:

## Security Summary

Give a concise overview of the security condition of the code.

## Security Score

Give a security score from 1 to 10.

Explain the score.

## Vulnerabilities

For every vulnerability found, provide:

- Vulnerability
- Severity
- Location
- Why it is dangerous
- Recommended fix

Use these severity levels:

CRITICAL
HIGH
MEDIUM
LOW
INFO

If no obvious vulnerabilities are found, say:

No obvious security vulnerabilities identified from the provided code.

## Hardcoded Secrets

Check specifically for:

- passwords
- API keys
- tokens
- private keys
- credentials

Do not reproduce real-looking secrets unnecessarily.

## Input Security

Explain whether user-controlled input is safely handled.

## Authentication and Authorization

Evaluate authentication and authorization logic if present.

If authentication or authorization is not present, say so.

## File and System Security

Check for unsafe:

- file access
- path handling
- shell commands
- process execution

## Database Security

Check for unsafe SQL construction or database interaction.

If no database interaction exists, say:

No database interaction identified.

## Recommended Fixes

Give prioritized recommendations:

Priority 1 - Critical
Priority 2 - High
Priority 3 - Medium
Priority 4 - Low

## Safer Code

Provide an improved version of the vulnerable code when practical.

IMPORTANT RULES:

- This is defensive security analysis.
- Do not provide instructions for attacking real systems.
- Do not invent vulnerabilities.
- Do not claim that you executed the code.
- Do not claim that you performed penetration testing.
- Do not claim that the code is completely secure.
- Only analyze the code provided.
- Clearly distinguish confirmed issues from potential risks.
- Do not expose secrets unnecessarily.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        result = {
            "code": code,
            "response": response
        }

        return result

    def explain(self, task, research=None):
        self.start()

        print("[Coding Agent] Analyzing research...")
    
        if research:
            prompt = f"""
You are Genesis Coding Agent.

The user asked:
{task}

Research from the Research Agent:
{research}

Analyze the research from a software-development perspective.

Explain:
1. How AI can improve software development
2. Practical applications
3. Benefits for developers
4. Risks and limitations
5. How Genesis OS could use these ideas
6. Recommended implementation steps

Do not claim that you executed or tested anything.
"""
        else:
            prompt = f"""
You are Genesis Coding Agent.

Analyze this task:

{task}

Provide a professional software-development analysis.
"""

        response = self.ai.generate_response(prompt)

        self.stop()

        return {
            "task": task,
            "response": response
        }

    def execute(self, task, context=None):

        self.start()

        try:

            previous_context = ""

            if context and context.has_results():

                latest = context.get_latest_result()

                if latest:

                    previous_context = f"""
Previous Agent:
{latest["agent"]}

Previous Agent Result:
{latest["result"]}
"""

            result = self.run(
                task,
                previous_context
            )

            if context:

                context.add_result(
                    self.name,
                    result
                )

            return result

        finally:

            self.stop()