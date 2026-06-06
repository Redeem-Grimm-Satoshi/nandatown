# SPDX-License-Identifier: Apache-2.0
"""Nanda Town shell: Tier 2 LLM-backed reference agent."""

__version__ = "0.1.0"

from nest_shell.agent import ShellAgent as ShellAgent
from nest_shell.agent import shell_marketplace_factory as shell_marketplace_factory
from nest_shell.factories import shell_auction_factory as shell_auction_factory
from nest_shell.factories import shell_consensus_factory as shell_consensus_factory
from nest_shell.factories import shell_reputation_factory as shell_reputation_factory
from nest_shell.factories import shell_supply_chain_factory as shell_supply_chain_factory
from nest_shell.factories import shell_voting_factory as shell_voting_factory
from nest_shell.llm import AnthropicBackend as AnthropicBackend
from nest_shell.llm import LiteLLMBackend as LiteLLMBackend
from nest_shell.llm import LLMBackend as LLMBackend
from nest_shell.llm import MockLLMBackend as MockLLMBackend
from nest_shell.llm import OpenAIBackend as OpenAIBackend
from nest_shell.templates import AgentTemplate as AgentTemplate
from nest_shell.templates import TemplateRegistry as TemplateRegistry
