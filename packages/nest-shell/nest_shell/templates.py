# SPDX-License-Identifier: Apache-2.0
"""Agent template management for Nanda Town shell agents.

Templates are YAML files that define how a Tier 2 (LLM-backed) agent behaves.
Each template specifies the system prompt, provider, model, and behavior
parameters.

Example::

    registry = TemplateRegistry()
    template = registry.get_template("marketplace-buyer")
    template.to_yaml(Path("my-buyer.yaml"))
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class AgentTemplate(BaseModel):
    """Schema for an agent template loaded from YAML.

    Example::

        template = AgentTemplate(
            name="my-agent",
            system_prompt="You are a helpful agent.",
        )
    """

    name: str
    description: str = ""
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int = 256

    @classmethod
    def from_yaml(cls, path: str | Path) -> AgentTemplate:
        """Load an agent template from a YAML file.

        Example::

            template = AgentTemplate.from_yaml("templates/agents/marketplace-buyer.yaml")
        """
        with Path(path).open() as f:
            data: dict[str, object] = yaml.safe_load(f)  # type: ignore[assignment]
        return cls.model_validate(data)

    def to_yaml(self, path: str | Path) -> Path:
        """Save the template to a YAML file.

        Example::

            saved = template.to_yaml("my-template.yaml")
        """
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump()
        with out.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return out


def _builtin_templates_dir() -> Path:
    """Return the path to the built-in templates/agents directory.

    Searches relative to the nest_shell package and CWD.

    Example::

        d = _builtin_templates_dir()
    """
    # Relative to the nest_shell package: ../../templates/agents
    pkg_dir = Path(__file__).resolve().parent
    for ancestor in [
        pkg_dir.parent,
        pkg_dir.parent.parent,
        pkg_dir.parent.parent.parent,
    ]:
        candidate = ancestor / "templates" / "agents"
        if candidate.is_dir():
            return candidate

    # Fall back to CWD
    cwd_candidate = Path.cwd() / "templates" / "agents"
    if cwd_candidate.is_dir():
        return cwd_candidate

    return cwd_candidate


class TemplateRegistry:
    """Discovers built-in and user templates.

    Example::

        registry = TemplateRegistry()
        templates = registry.list_templates()
    """

    def __init__(self, user_dir: str | Path | None = None) -> None:
        self._user_dir = Path(user_dir) if user_dir else None
        self._builtin_dir = _builtin_templates_dir()

    def _search_dirs(self) -> list[Path]:
        """Return directories to search for templates, in priority order.

        Example::

            dirs = registry._search_dirs()
        """
        dirs: list[Path] = []
        if self._user_dir and self._user_dir.is_dir():
            dirs.append(self._user_dir)
        if self._builtin_dir.is_dir():
            dirs.append(self._builtin_dir)
        return dirs

    def list_templates(self) -> list[AgentTemplate]:
        """List all available templates (user overrides first, then built-in).

        Example::

            templates = registry.list_templates()
        """
        seen: set[str] = set()
        results: list[AgentTemplate] = []
        for d in self._search_dirs():
            for yaml_file in sorted(d.glob("*.yaml")):
                try:
                    tpl = AgentTemplate.from_yaml(yaml_file)
                except Exception:  # noqa: BLE001
                    continue
                if tpl.name not in seen:
                    seen.add(tpl.name)
                    results.append(tpl)
        return results

    def get_template(self, name: str) -> AgentTemplate:
        """Get a template by name.

        Raises ``KeyError`` if not found.

        Example::

            tpl = registry.get_template("marketplace-buyer")
        """
        for d in self._search_dirs():
            candidate = d / f"{name}.yaml"
            if candidate.exists():
                return AgentTemplate.from_yaml(candidate)
        msg = f"Template not found: {name!r}"
        raise KeyError(msg)

    def save_template(self, template: AgentTemplate) -> Path:
        """Save a template to the user directory.

        Example::

            path = registry.save_template(template)
        """
        target_dir = self._user_dir or (Path.cwd() / "templates" / "agents")
        target_dir.mkdir(parents=True, exist_ok=True)
        return template.to_yaml(target_dir / f"{template.name}.yaml")

    def duplicate_template(self, name: str, new_name: str) -> AgentTemplate:
        """Duplicate an existing template under a new name.

        Example::

            new_tpl = registry.duplicate_template("marketplace-buyer", "my-buyer")
        """
        original = self.get_template(name)
        copy = original.model_copy(update={"name": new_name})
        self.save_template(copy)
        return copy
