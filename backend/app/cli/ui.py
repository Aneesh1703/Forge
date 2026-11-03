"""
Phase 10F: Rich Terminal UI Component Helpers
Provides spinners, progress panels, syntax highlighted diffs, and interactive prompts.
"""

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

from app.agents.plan_models import ImplementationPlan

console = Console()


class TerminalUI:
    """Rich terminal output formatter for Forge CLI."""

    @classmethod
    def print_banner(cls) -> None:
        console.print(
            Panel.fit(
                "[bold cyan]Forge Engine[/bold cyan] — "
                "[italic]Autonomous Software Engineering Agent[/italic]\n"
                "[dim]Local-First Pipeline & Safety Gate Architecture[/dim]",
                border_style="cyan",
            )
        )

    @classmethod
    def plan_panel(cls, plan_data: dict[str, Any], plan_path: Path | None = None) -> Panel:
        """The stored plan rendered for Gate 1 review; callers print it on their console."""
        plan = ImplementationPlan.from_dict(plan_data)
        subtitle = f"[dim]{plan_path}[/dim]" if plan_path else None
        return Panel(
            Markdown(plan.to_markdown()),
            title="🗺️ [bold green]Gate 1 — Implementation Plan[/bold green]",
            subtitle=subtitle,
            border_style="green",
        )

    @classmethod
    def print_diff_stats(cls, files_count: int, lines_added: int) -> None:
        msg = (
            f"[bold green]+{lines_added} lines added[/bold green] across "
            f"[bold yellow]{files_count} files[/bold yellow]"
        )
        console.print(
            Panel(
                msg,
                title="[bold]Patch Diff Statistics[/bold]",
                border_style="green",
            )
        )

    @classmethod
    def prompt_gate(cls, gate_name: str, description: str) -> bool:
        console.print(f"\n[bold yellow]=== {gate_name} ===[/bold yellow]")
        console.print(f"[white]{description}[/white]\n")
        return Confirm.ask(f"[bold cyan]Do you approve {gate_name}?[/bold cyan]")
