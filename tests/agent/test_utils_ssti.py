"""
Tests for CWE-1336 SSTI fix in mcpuniverse/agent/utils.py

Verifies that:
1. SandboxedEnvironment is used (SSTI payloads are blocked)
2. Normal template rendering still works correctly
"""

import importlib.util
import os
import sys
import tempfile
import pytest

# Direct-load utils.py to avoid heavy transitive deps from __init__.py
_spec = importlib.util.spec_from_file_location(
    "mcpuniverse.agent.utils",
    os.path.join(os.path.dirname(__file__), "../../mcpuniverse/agent/utils.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

render_prompt_template = _mod.render_prompt_template
build_system_prompt = _mod.build_system_prompt


# ── Normal functionality tests ──────────────────────────────────────────────


class TestRenderPromptTemplateNormal:
    """Verify that normal (non-malicious) templates render correctly."""

    def test_simple_variable_substitution(self):
        result = render_prompt_template("Hello, {{ NAME }}!", NAME="World")
        assert result == "Hello, World!"

    def test_multiple_variables(self):
        tpl = "{{ GREETING }}, {{ NAME }}! You are a {{ ROLE }}."
        result = render_prompt_template(tpl, GREETING="Hi", NAME="Alice", ROLE="helper")
        assert result == "Hi, Alice! You are a helper."

    def test_conditional_block(self):
        tpl = "{% if SHOW %}visible{% else %}hidden{% endif %}"
        assert render_prompt_template(tpl, SHOW=True) == "visible"
        assert render_prompt_template(tpl, SHOW=False) == "hidden"

    def test_for_loop(self):
        tpl = "{% for item in ITEMS %}{{ item }} {% endfor %}"
        result = render_prompt_template(tpl, ITEMS=["a", "b", "c"])
        assert result == "a b c"

    def test_trim_blocks_and_lstrip(self):
        """Verify trim_blocks and lstrip_blocks settings are preserved."""
        tpl = "line1\n{% if True %}\nline2\n{% endif %}\nline3"
        result = render_prompt_template(tpl)
        # With trim_blocks + lstrip_blocks, extraneous newlines from tags are removed
        assert "line2" in result
        assert "line1" in result

    def test_j2_file_template(self):
        """Verify .j2 file templates still load and render."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".j2", delete=False
        ) as f:
            f.write("Hello from file: {{ WHO }}")
            f.flush()
            tmppath = f.name
        try:
            result = render_prompt_template(tmppath, WHO="file_test")
            assert result == "Hello from file: file_test"
        finally:
            os.unlink(tmppath)

    def test_empty_template(self):
        result = render_prompt_template("")
        assert result == ""

    def test_no_variables(self):
        result = render_prompt_template("Just a plain string.")
        assert result == "Just a plain string."


class TestBuildSystemPromptNormal:
    """Verify that build_system_prompt renders correctly with normal inputs."""

    def test_basic_system_prompt(self):
        result = build_system_prompt(
            system_prompt_template="You are {{ ROLE }}.",
            ROLE="a helpful assistant",
        )
        assert result == "You are a helpful assistant."

    def test_system_prompt_with_tools_prompt(self):
        result = build_system_prompt(
            system_prompt_template="System: {{ INSTRUCTION }}\n{{ TOOLS_PROMPT }}",
            tool_prompt_template="Tools: {{ TOOLS_DESCRIPTION }}",
            tools=None,
            include_tool_description=True,
            INSTRUCTION="Be helpful",
        )
        # No tools provided, so TOOLS_PROMPT should be empty
        assert "Be helpful" in result

    def test_system_prompt_strips_whitespace(self):
        result = build_system_prompt(
            system_prompt_template="  Hello  ",
        )
        assert result == "Hello"


# ── Security tests (SSTI blocked) ──────────────────────────────────────────


# Dangerous SSTI payloads that chain dunder attributes to achieve RCE or info leak.
# SandboxedEnvironment blocks chaining through __mro__, __subclasses__, __globals__, etc.
# Note: simple `{{ ''.__class__ }}` alone is allowed by SandboxedEnvironment (it's benign),
# but chaining to __mro__/__subclasses__/__globals__ is blocked.
SSTI_PAYLOADS_BLOCKED = [
    # MRO traversal to __subclasses__
    "{{ ''.__class__.__mro__[1].__subclasses__() }}",
    # __globals__ access for os.popen
    "{{ config.__class__.__init__.__globals__['os'].popen('id').read() }}",
    # lipsum.__globals__ for os access
    "{{ lipsum.__globals__['os'].popen('echo pwned').read() }}",
    # __subclasses__ to open files
    "{{ ''.__class__.__mro__[2].__subclasses__()[40]('/etc/passwd').read() }}",
    # cycler.__init__.__globals__
    "{{ cycler.__init__.__globals__.os.popen('id').read() }}",
    # joiner.__init__.__globals__
    "{{ joiner.__init__.__globals__.os.popen('id').read() }}",
    # namespace.__init__.__globals__
    "{{ namespace.__init__.__globals__.os.popen('id').read() }}",
]


class TestRenderPromptTemplateSSTI:
    """Verify that SSTI payloads are blocked in render_prompt_template."""

    @pytest.mark.parametrize("payload", SSTI_PAYLOADS_BLOCKED)
    def test_ssti_payload_blocked(self, payload):
        """SandboxedEnvironment should raise SecurityError for dangerous attribute chaining."""
        with pytest.raises(Exception) as exc_info:
            render_prompt_template(payload)
        # Verify error is security-related, not a random error
        exc_type = type(exc_info.value).__name__
        exc_msg = str(exc_info.value).lower()
        assert any([
            "SecurityError" in exc_type,
            "security" in exc_msg,
            "unsafe" in exc_msg,
            "is not safely callable" in exc_msg,
            "access to attribute" in exc_msg,
            "UndefinedError" in exc_type,  # some payloads fail at lookup, also safe
        ]), f"Unexpected exception type {exc_type}: {exc_info.value}"


class TestBuildSystemPromptSSTI:
    """Verify that SSTI payloads are blocked in build_system_prompt."""

    def test_ssti_in_system_prompt_template(self):
        """Malicious system_prompt_template should be blocked."""
        with pytest.raises(Exception):
            build_system_prompt(
                system_prompt_template="{{ ''.__class__.__mro__[1].__subclasses__() }}",
            )

    def test_ssti_in_tool_prompt_template(self):
        """Malicious tool_prompt_template should be blocked when tools are provided."""
        # Create a minimal mock Tool object
        class MockTool:
            name = "test"
            description = "test tool"
            inputSchema = {"properties": {}}

        with pytest.raises(Exception):
            build_system_prompt(
                system_prompt_template="System: {{ TOOLS_PROMPT }}",
                tool_prompt_template="{{ ''.__class__.__mro__[1].__subclasses__() }}",
                tools={"test": [MockTool()]},
                include_tool_description=True,
            )


class TestSandboxedEnvironmentUsed:
    """Verify that the module actually uses SandboxedEnvironment, not Environment."""

    def test_import_is_sandboxed(self):
        """Check that the module imports SandboxedEnvironment."""
        source_path = os.path.join(
            os.path.dirname(__file__),
            "../../mcpuniverse/agent/utils.py",
        )
        with open(source_path, "r") as f:
            source = f.read()
        assert "from jinja2.sandbox import SandboxedEnvironment" in source
        # Make sure the old insecure import is gone
        assert "from jinja2 import Environment" not in source

    def test_no_bare_environment_instantiation(self):
        """Ensure no bare Environment() calls remain."""
        source_path = os.path.join(
            os.path.dirname(__file__),
            "../../mcpuniverse/agent/utils.py",
        )
        with open(source_path, "r") as f:
            source = f.read()
        # All Environment instantiations should be SandboxedEnvironment
        import re
        bare_envs = re.findall(r'(?<!\w)Environment\(', source)
        sandboxed_envs = re.findall(r'SandboxedEnvironment\(', source)
        assert len(bare_envs) == 0, f"Found bare Environment() calls: {bare_envs}"
        assert len(sandboxed_envs) >= 3, f"Expected at least 3 SandboxedEnvironment() calls, found {len(sandboxed_envs)}"
