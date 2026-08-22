"""
Phase 10F: Rich Terminal UI Component Helpers
Provides spinners, progress panels, syntax highlighted diffs, and interactive prompts.
"""

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

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
    def print_plan(cls, plan_data: dict[str, Any]) -> None:
        table = Table(title="[bold green]Generated Implementation Plan[/bold green]")
        table.add_column("Property", style="cyan")
        table.add_column("Details", style="white")

        table.add_row("Summary", str(plan_data.get("summary", "")))
        table.add_row("Allowed Files", ", ".join(plan_data.get("allowed_files", [])))

        console.print(table)

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
