"""
Phase 10F: Forge Master CLI Entry Point
Built with Typer & Rich, providing local-first developer commands.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from app.agents.coder.models import ExecutionPolicy
from app.cli.config import ConfigManager
from app.cli.ui import TerminalUI
from app.orchestration.pipeline import ForgeOrchestrator
from app.orchestration.state import JobState

app = typer.Typer(
    name="forge",
    help="Forge Engine — Autonomous Software Engineering Agent CLI",
)
config_app = typer.Typer(help="Manage API keys and local configuration")
app.add_typer(config_app, name="config")
console = Console()


@config_app.command("set-key")
def set_key(
    provider: Annotated[
        str,
        typer.Option(
            "--provider", "-p", help="LLM Provider name (deepseek, openai, anthropic, ollama)"
        ),
    ],
    key: Annotated[str, typer.Option("--key", "-k", help="API Key value")],
) -> None:
    """Saves an API key for a specified LLM provider in ~/.forge/config.json."""
    ConfigManager.set_key(provider, key)
    console.print(
        f"[bold green]✓ Successfully saved API key for provider '{provider}'[/bold green]"
    )


@config_app.command("list")
def list_keys() -> None:
    """Lists configured LLM provider keys (masked)."""
    keys = ConfigManager.list_keys()
    if not keys:
        console.print(
            "[yellow]No keys configured. Use 'forge config set-key' to add keys.[/yellow]"
        )
        return
    console.print("[bold cyan]Configured LLM Provider Keys:[/bold cyan]")
    for p, masked in keys.items():
        console.print(f"  - [bold]{p}[/bold]: {masked}")


@app.command("fix")
def fix(
    issue: Annotated[
        str, typer.Option("--issue", "-i", help="Natural language issue prompt or description")
    ],
    repo: Annotated[
        Path, typer.Option("--repo", "-r", help="Target repository directory path")
    ] = Path("."),
    target_file: Annotated[
        str | None,
        typer.Option("--target-file", "-f", help="Target file path relative to repo root"),
    ] = None,
    symbol: Annotated[
        str, typer.Option("--symbol", "-s", help="Target symbol name (function/class)")
    ] = "jsonify",
    policy: Annotated[
        str, typer.Option("--policy", help="Execution policy (MANUAL, SEMI_AUTONOMOUS, AUTONOMOUS)")
    ] = "SEMI_AUTONOMOUS",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview plan and target actions without writing files"),
    ] = False,
) -> None:
    """Runs the complete end-to-end Forge resolution pipeline on a repository."""
    TerminalUI.print_banner()

    exec_policy = ExecutionPolicy(policy.upper())
    repo_path = repo.resolve()

    # Auto-detect target file if not provided
    tf = target_file
    if not tf:
        candidates = [
            "src/flask/json/__init__.py",
            "src/flask/json/provider.py",
            "src/flask/app.py",
            "app.py",
        ]
        for c in candidates:
            if (repo_path / c).exists():
                tf = c
                break
        if not tf:
            py_files = list(repo_path.glob("**/*.py"))
            if py_files:
                tf = str(py_files[0].relative_to(repo_path))
            else:
                tf = "app.py"

    if dry_run:
        console.print("[bold yellow]=== DRY RUN MODE ACTIVE ===[/bold yellow]")
        console.print(f"Target Repository: [bold]{repo_path}[/bold]")
        console.print(f"Issue Prompt: [italic]{issue}[/italic]")
        console.print(f"Target File: [bold]{tf}[/bold]")
        console.print(f"Target Symbol: [bold]{symbol}[/bold]")
        console.print(f"Execution Policy: [bold]{exec_policy.value}[/bold]")
        console.print("\n[green]Dry run complete. No files or git branches were modified.[/green]")
        return

    orchestrator = ForgeOrchestrator(repo_root=repo_path)
    state = orchestrator.create_job(issue_prompt=issue, execution_policy=exec_policy)

    console.print(f"[bold cyan]Job Initialized:[/bold cyan] {state.job_id}")
    console.print(f"Target File: [bold]{tf}[/bold]")
    console.print(f"Status: [yellow]{state.status.value}[/yellow]")

    # Run pipeline asynchronously
    async def run_pipeline() -> JobState:
        return await orchestrator.execute_job(job_id=state.job_id)

    final_state = asyncio.run(run_pipeline())
    console.print(
        f"\n[bold green]Pipeline Execution Completed![/bold green] "
        f"Status: [bold]{final_state.status.value}[/bold]"
    )


@app.command("status")
def status(
    job_id: Annotated[str, typer.Option("--job-id", "-j", help="Job UUID")],
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Repository directory path")] = Path(
        "."
    ),
) -> None:
    """Queries and displays the current state of a Forge job."""
    repo_path = repo.resolve()
    state_file = repo_path / ".forge_jobs" / f"job_{job_id}.json"

    if not state_file.exists():
        console.print(f"[bold red]Error: Job state file not found at {state_file}[/bold red]")
        return

    state = JobState.load(state_file)
    console.print(f"[bold cyan]Job ID:[/bold cyan] {state.job_id}")
    console.print(f"[bold cyan]Status:[/bold cyan] [bold yellow]{state.status.value}[/bold yellow]")
    console.print(f"[bold cyan]Issue:[/bold cyan] {state.issue_prompt}")
    console.print(f"[bold cyan]Policy:[/bold cyan] {state.execution_policy.value}")


@app.command("resume")
def resume(
    job_id: Annotated[str, typer.Option("--job-id", "-j", help="Job UUID to resume")],
    repo: Annotated[
        Path, typer.Option("--repo", "-r", help="Target repository directory path")
    ] = Path("."),
    approve: Annotated[
        bool, typer.Option("--approve", "-a", help="Approve current pending gate")
    ] = True,
) -> None:
    """Resumes execution of a paused or awaiting Forge job from its stored state."""
    repo_path = repo.resolve()
    orchestrator = ForgeOrchestrator(repo_root=repo_path)
    state_file = orchestrator.get_state_path(job_id)

    if not state_file.exists():
        console.print(f"[bold red]Error: Job state file not found for job '{job_id}'[/bold red]")
        return

    initial_state = JobState.load(state_file)
    console.print(f"[bold cyan]Resuming Job:[/bold cyan] {job_id}")
    console.print(f"Current Status: [bold yellow]{initial_state.status.value}[/bold yellow]")

    async def run_resume() -> JobState:
        return await orchestrator.resume_job(
            job_id=job_id,
            gate_1_approved=approve,
            gate_2_approved=approve,
            gate_3_approved=approve,
        )

    resumed_state = asyncio.run(run_resume())
    console.print(
        f"\n[bold green]Resumed Job Execution Complete![/bold green] "
        f"New Status: [bold]{resumed_state.status.value}[/bold]"
    )


@app.command("shell")
def shell() -> None:
    """Launches the interactive Forge REPL terminal."""
    from app.cli.repl import run_repl

    run_repl()


if __name__ == "__main__":
    app()
