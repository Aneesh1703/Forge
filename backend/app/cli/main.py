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
from app.github.auth import GitHubAuthManager
from app.orchestration.pipeline import ForgeOrchestrator
from app.orchestration.state import JobState, JobStatus

app = typer.Typer(
    name="forge",
    help="Forge Engine — Autonomous Software Engineering Agent CLI",
)
config_app = typer.Typer(help="Manage API keys and local configuration")
app.add_typer(config_app, name="config")
console = Console()

# How users invoke this CLI until it is packaged as a `forge` command (roadmap D3).
CLI = "uv run python -m app.cli.main"


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
            f"[yellow]No keys configured. Use '{CLI} config set-key' to add keys.[/yellow]"
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
    policy: Annotated[
        str, typer.Option("--policy", help="Execution policy (MANUAL, SEMI_AUTONOMOUS, AUTONOMOUS)")
    ] = "SEMI_AUTONOMOUS",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Stop at the plan (Gate 1); no code is written"),
    ] = False,
) -> None:
    """Runs the complete end-to-end Forge resolution pipeline on a repository."""
    TerminalUI.print_banner()

    exec_policy = ExecutionPolicy(policy.upper())
    repo_path = repo.resolve()

    orchestrator = ForgeOrchestrator(repo_root=repo_path)
    state = orchestrator.create_job(issue_prompt=issue, execution_policy=exec_policy)

    console.print(f"[bold cyan]Job Initialized:[/bold cyan] {state.job_id}")
    if dry_run:
        console.print(
            "[bold yellow]Dry run: stopping at the plan; no code is written.[/bold yellow]"
        )
    console.print(f"Status: [yellow]{state.status.value}[/yellow]")

    # Run pipeline asynchronously
    async def run_pipeline() -> JobState:
        return await orchestrator.execute_job(job_id=state.job_id, plan_only=dry_run)

    final_state = asyncio.run(run_pipeline())
    console.print(
        f"\n[bold green]Pipeline Execution Completed![/bold green] "
        f"Status: [bold]{final_state.status.value}[/bold]"
    )
    if final_state.status == JobStatus.AWAITING_GATE_1:
        _print_gate_1(orchestrator, final_state)
    elif final_state.error_message:
        console.print(f"[bold red]Error:[/bold red] {final_state.error_message}")


def _print_gate_1(orchestrator: ForgeOrchestrator, state: JobState) -> None:
    """Shows the plan awaiting approval and how to decide on it."""
    if state.implementation_plan:
        plan_path = orchestrator.get_artifact_dir(state.job_id) / "plan.md"
        console.print(
            TerminalUI.plan_panel(
                state.implementation_plan, plan_path if plan_path.exists() else None
            )
        )
    console.print(
        f"Approve with [bold]{CLI} resume -j {state.job_id} -r {state.repository_path} "
        "--approve[/bold], or reject with --reject."
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
        bool,
        typer.Option("--approve", "-a", help="Approve the pending gate (commits locally)"),
    ] = False,
    publish: Annotated[
        bool,
        typer.Option("--publish", help="Approve, commit, push and open a PR"),
    ] = False,
    reject: Annotated[
        bool, typer.Option("--reject", help="Reject the current pending gate")
    ] = False,
) -> None:
    """Resumes a paused Forge job. Gates move only with --approve, --publish or --reject."""
    if sum((approve, publish, reject)) > 1:
        console.print(
            "[bold red]Error: pass only one of --approve, --publish or --reject.[/bold red]"
        )
        raise typer.Exit(code=2)
    repo_path = repo.resolve()
    orchestrator = ForgeOrchestrator(repo_root=repo_path)
    state_file = orchestrator.get_state_path(job_id)

    if not state_file.exists():
        console.print(f"[bold red]Error: Job state file not found for job '{job_id}'[/bold red]")
        return

    initial_state = JobState.load(state_file)
    console.print(f"[bold cyan]Resuming Job:[/bold cyan] {job_id}")
    console.print(f"Current Status: [bold yellow]{initial_state.status.value}[/bold yellow]")
    for reason in initial_state.gate_2_reasons:
        console.print(f"   [yellow]• {reason}[/yellow]")

    if not (approve or publish or reject):
        if initial_state.status == JobStatus.AWAITING_GATE_1:
            _print_gate_1(orchestrator, initial_state)
        console.print("No gate decision given; pass --approve, --publish or --reject.")
        return

    if publish:
        if initial_state.status == JobStatus.AWAITING_GATE_1:
            console.print(
                "[bold red]Error: nothing to publish yet — approve the plan first "
                "with --approve.[/bold red]"
            )
            raise typer.Exit(code=2)
        if not GitHubAuthManager.is_authenticated():
            console.print(
                "[bold red]Error: GitHub authentication required to publish. "
                f"Run `gh auth login` or `{CLI} config set-key -p github -k <token>`.[/bold red]"
            )
            raise typer.Exit(code=1)

    decision = not reject

    async def run_resume() -> JobState:
        return await orchestrator.resume_job(
            job_id=job_id,
            gate_1_approved=decision,
            gate_2_approved=decision,
            gate_3_approved=decision,
            publish_pr=publish,
        )

    resumed_state = asyncio.run(run_resume())
    console.print(f"\nNew Status: [bold]{resumed_state.status.value}[/bold]")
    if resumed_state.commit_sha:
        console.print(f"Commit: {resumed_state.commit_sha[:8]} on {resumed_state.git_branch}")
    if resumed_state.pr_url:
        console.print(f"[bold green]Pull request:[/bold green] {resumed_state.pr_url}")
    if resumed_state.error_message:
        console.print(f"[bold red]Error:[/bold red] {resumed_state.error_message}")
    if publish and not resumed_state.pr_url:
        raise typer.Exit(code=1)


@app.command("shell")
def shell() -> None:
    """Launches the interactive Forge REPL terminal."""
    from app.cli.repl import run_repl

    run_repl()


if __name__ == "__main__":
    app()
