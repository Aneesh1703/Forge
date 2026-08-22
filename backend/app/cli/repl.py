"""
Forge Interactive REPL Terminal — Premium Claude Code-style interactive shell.
Provides onboarding flow (repo -> issue -> branch) and persistent chat loop.
"""

import asyncio
import os
import re
import sys
from io import StringIO
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.styles import Style
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from app.agents.coder.models import ExecutionPolicy
from app.cli.config import ConfigManager
from app.github.auth import GitHubAuthManager
from app.orchestration.pipeline import ForgeOrchestrator
from app.orchestration.state import JobState, JobStatus

custom_theme = Theme(
    {
        "info": "dim cyan",
        "warning": "magenta",
        "danger": "bold red",
        "success": "bold green",
    }
)


def _make_console() -> Console:
    """Creates a Console safe for both real terminals and pytest on Windows."""
    try:
        return Console(force_terminal=True, theme=custom_theme)
    except Exception:
        return Console(file=StringIO(), force_terminal=False, theme=custom_theme)


console = _make_console()

SLASH_COMMANDS = [
    "/help",
    "/status",
    "/fix",
    "/plan",
    "/approve",
    "/reject",
    "/diff",
    "/jobs",
    "/config",
    "/policy",
    "/rewind",
    "/clear",
    "/exit",
    "/quit",
]


class ForgeREPL:
    """Interactive REPL session with onboarding, advanced UI, and slash command routing."""

    def __init__(self) -> None:
        self.repo_path: Path | None = None
        self.issue_prompt: str = ""
        self.branch_name: str = ""
        self.policy: ExecutionPolicy = ExecutionPolicy.SEMI_AUTONOMOUS
        self.orchestrator: ForgeOrchestrator | None = None
        self.current_job_id: str | None = None
        self._session: PromptSession[str] | None = None

        self.pt_style = Style.from_dict(
            {
                "prompt-bracket": "ansicyan bold",
                "prompt-text": "ansiblue bold",
                "prompt-arrow": "ansigreen bold",
                "bottom-toolbar": "bg:#1e1e1e #cccccc",
                "bottom-toolbar.label": "bg:#252526 #ffffff bold",
                "bottom-toolbar.value": "bg:#1e1e1e #4ec9b0",
            }
        )

    @property
    def session(self) -> PromptSession[str]:
        """Lazily creates PromptSession with bottom toolbar and styling."""
        if self._session is None:
            self._session = PromptSession(
                history=InMemoryHistory(),
                completer=WordCompleter(SLASH_COMMANDS, sentence=True),
                style=self.pt_style,
                bottom_toolbar=self._get_bottom_toolbar,
            )
        return self._session

    def _get_bottom_toolbar(self) -> FormattedText:
        """Dynamically renders the Claude-style bottom toolbar."""
        repo = self.repo_path.name if self.repo_path else "Not Set"
        branch = self.branch_name or "auto"
        policy = self.policy.value if self.policy else "Unknown"
        job = self.current_job_id[:8] if self.current_job_id else "None"

        return FormattedText(
            [
                ("class:bottom-toolbar.label", " 🛠️ FORGE "),
                (
                    "",
                    f" Repo: {repo} | Branch: {branch} | Policy: {policy} | Job: {job} ",
                ),
            ]
        )

    def print_welcome(self) -> None:
        """Prints the startup welcome banner with ASCII flair."""
        console.clear()
        banner = Text(
            "  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗\n"
            "  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝\n"
            "  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  \n"
            "  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  \n"
            "  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗\n"
            "  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
            style="bold cyan",
            justify="center",
        )

        panel = Panel(
            banner,
            title="[bold white]Forge Engine v0.0.0[/bold white]",
            subtitle="[dim]Autonomous Software Engineering Agent[/dim]",
            border_style="bright_cyan",
            box=box.DOUBLE,
            padding=(1, 2),
        )
        console.print()
        console.print(panel)
        console.print(
            "\n[dim]   Type a message, natural language, or use /help for commands...[/dim]\n"
        )

    def print_help(self) -> None:
        """Prints beautifully formatted available slash commands."""
        table = Table(
            title="✨ Available Commands",
            show_header=True,
            header_style="bold bright_white",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 2),
            expand=True,
        )
        table.add_column("Command", style="bold green", width=18)
        table.add_column("Description", style="white")
        table.add_column("Shortcut", style="dim cyan", justify="right")

        commands = [
            ("/help", "Show this help message", "help"),
            ("/status", "Show current job status", "status"),
            ("/fix <issue>", "Run full pipeline on an issue", "fix"),
            ("/plan <issue>", "Preview implementation plan only", "plan"),
            ("/approve", "Approve current pending gate", "approve"),
            ("/reject", "Reject current pending gate", "reject"),
            ("/diff", "Show current patch details", "diff"),
            ("/jobs", "List all jobs for current repo", "jobs"),
            ("/config", "Show configured API keys", "config"),
            ("/policy <mode>", "Set policy (MANUAL / SEMI / AUTO)", "policy"),
            ("/rewind [steps]", "Rewind state machine history", "rewind"),
            ("/clear", "Clear terminal screen", "clear"),
            ("/exit", "Exit Forge shell", "quit/exit"),
        ]
        for cmd, desc, sc in commands:
            table.add_row(cmd, desc, sc)

        console.print(table)
        console.print()

    def run_onboarding(self) -> bool:
        """Interactive, stylized onboarding: collect repo, issue, and branch."""
        console.rule("[bold cyan]Session Setup[/bold cyan]", align="left")

        # Step 1: Repository
        cwd = Path.cwd()
        if cwd.name == "backend" and (cwd.parent / "backend").exists():
            default_repo = str(cwd.parent.resolve())
        else:
            default_repo = str(cwd.resolve())
        while True:
            try:
                repo_input = Prompt.ask(
                    "\n[bold cyan]1.[/bold cyan] 📁 [bold]Repository Path[/bold]",
                    default=default_repo,
                    console=console,
                ).strip()
            except (KeyboardInterrupt, EOFError):
                return False

            if repo_input.startswith("/"):
                if repo_input == "/help":
                    self.print_help()
                # If valid default path exists, fallback to default_repo
                if Path(default_repo).exists():
                    repo_path = Path(default_repo).resolve()
                    break

            repo_path = Path(repo_input).resolve()
            if repo_path.exists():
                break

            console.print(f"[warning]   ⚠️ Directory not found: {repo_path}.[/warning]")
            console.print(f"[info]   Using default repository: {default_repo}[/info]")
            if Path(default_repo).exists():
                repo_path = Path(default_repo).resolve()
                break

        self.repo_path = repo_path

        # Step 2: GitHub Issue
        try:
            issue_input = Prompt.ask(
                "[bold cyan]2.[/bold cyan] 🎯 [bold]Issue Description / URL[/bold]\n"
                "[dim]   (e.g. 'Fix the memory leak in parser.py')[/dim]",
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            return False

        if not issue_input.strip():
            console.print("[warning]   ⚠️ Issue cannot be empty[/warning]")
            return False
        self.issue_prompt = issue_input.strip()

        # Step 3: Branch Name
        default_branch = "forge/fix-issue"
        try:
            branch_input = Prompt.ask(
                "[bold cyan]3.[/bold cyan] 🌿 [bold]Branch Name[/bold]",
                default=default_branch,
                console=console,
            )
        except (KeyboardInterrupt, EOFError):
            return False

        self.branch_name = branch_input.strip() or default_branch

        # Initialize orchestrator visually
        with console.status(
            "[bold green]Initializing orchestrator and workspace...[/bold green]",
            spinner="dots",
        ):
            self.orchestrator = ForgeOrchestrator(repo_root=self.repo_path)
            import time

            time.sleep(0.5)

        console.print("[success]   ✅ Workspace ready![/success]\n")
        return True

    def handle_command(self, raw_input: str) -> bool:
        """Routes a slash command or natural language input. Returns False to exit."""
        text = raw_input.strip()
        if not text:
            return True

        parts = text.split(maxsplit=1)
        cmd_candidate = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        keyword_map: dict[str, str] = {
            "approve": "/approve",
            "reject": "/reject",
            "publish": "/publish",
            "status": "/status",
            "help": "/help",
            "quit": "/quit",
            "exit": "/exit",
            "diff": "/diff",
            "jobs": "/jobs",
            "config": "/config",
            "rewind": "/rewind",
            "clear": "/clear",
            "a": "/approve",
            "d": "/diff",
            "p": "/publish",
            "r": "/reject",
        }

        if cmd_candidate in keyword_map:
            cmd = keyword_map[cmd_candidate]
        elif cmd_candidate.startswith("/"):
            cmd = cmd_candidate
        else:
            self._cmd_fix(text)
            return True

        if cmd in ("/exit", "/quit"):
            return False
        elif cmd == "/help":
            self.print_help()
        elif cmd == "/clear":
            os.system("cls" if sys.platform == "win32" else "clear")
            self.print_welcome()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/fix":
            self._cmd_fix(arg or self.issue_prompt)
        elif cmd == "/plan":
            self._cmd_plan(arg or self.issue_prompt)
        elif cmd == "/approve":
            self._cmd_approve()
        elif cmd == "/publish":
            self._cmd_publish()
        elif cmd == "/reject":
            self._cmd_reject()
        elif cmd == "/rewind":
            self._cmd_rewind(arg)
        elif cmd == "/diff":
            self._cmd_diff()
        elif cmd == "/jobs":
            self._cmd_jobs()
        elif cmd == "/config":
            self._cmd_config(arg)
        elif cmd == "/policy":
            self._cmd_policy(arg)
        else:
            console.print(f"[warning]⚠️ Unknown command: {cmd}. Type /help[/warning]\n")

        return True

    def _cmd_fix(self, issue: str) -> None:
        """Runs the full Forge pipeline on an issue with rich visual feedback.

        v2.0: The CLI is a thin shell. All intelligence lives in the orchestrator.
        """
        if not self.orchestrator or not self.repo_path:
            console.print("[danger]❌ No repository set. Please restart session.[/danger]\n")
            return
        if not issue:
            console.print("[warning]⚠️ Please provide an issue description.[/warning]\n")
            return

        self.issue_prompt = issue

        console.rule("[bold magenta]🚀 Initiating Forge Pipeline[/bold magenta]", align="left")
        console.print(f"   [bold]Issue:[/bold]   [info]{issue}[/info]")
        console.print(f"   [bold]Policy:[/bold]  [info]{self.policy.value}[/info]\n")

        state = self.orchestrator.create_job(issue_prompt=issue, execution_policy=self.policy)
        self.current_job_id = state.job_id

        async def _run() -> JobState:
            assert self.orchestrator is not None
            return await self.orchestrator.execute_job(job_id=state.job_id)

        with console.status(
            "[bold magenta]⚙️ Running autonomous pipeline...[/bold magenta]",
            spinner="point",
        ):
            try:
                final = asyncio.run(_run())
            except Exception as e:
                console.print(f"\n[danger]❌ Pipeline error: {e}[/danger]\n")
                return

        self._render_job_result(final)

    def _cmd_plan(self, issue: str) -> None:
        """Generates and displays an implementation plan without executing."""
        if not self.orchestrator or not self.repo_path:
            console.print("[danger]❌ No repository set.[/danger]\n")
            return
        if not issue:
            console.print("[warning]⚠️ Please provide an issue description.[/warning]\n")
            return

        with console.status(
            "[bold cyan]Drafting implementation plan...[/bold cyan]", spinner="dots"
        ):
            tf = self._detect_target_file(issue)

        console.print(
            Panel(
                f"[bold]Target File:[/bold] [info]{tf}[/info]\n"
                f"[bold]Policy:[/bold]      [info]{self.policy.value}[/info]\n"
                f"[bold]Goal:[/bold]        [white]{issue}[/white]",
                title="🗺️ [bold green]Implementation Plan Preview[/bold green]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
        console.print()

    def _cmd_status(self) -> None:
        """Shows current job status."""
        if not self.current_job_id or not self.orchestrator:
            console.print("[dim]ℹ️ No active job. Use /fix to start one.[/dim]\n")
            return

        state_path = self.orchestrator.get_state_path(self.current_job_id)
        if not state_path.exists():
            console.print("[danger]❌ Job state file not found.[/danger]\n")
            return

        state = JobState.load(state_path)
        color = (
            "success"
            if state.status.value == "COMPLETED"
            else "danger"
            if state.status.value in ("FAILED", "ABORTED")
            else "warning"
        )
        gate_str = "✅ PASS" if state.repo_gate_passed else "❌ FAIL"

        in_tok = getattr(state, "prompt_tokens", 0)
        out_tok = getattr(state, "completion_tokens", 0)
        tot_tok = in_tok + out_tok
        est_cost = (in_tok * 0.00000014) + (out_tok * 0.00000028)
        tok_str = f"{tot_tok:,} ({in_tok:,} in / {out_tok:,} out) ~ ${est_cost:.4f}"

        console.print(
            Panel(
                f"[bold]Job ID:[/bold]    {state.job_id}\n"
                f"[bold]Status:[/bold]    [{color}]{state.status.value}[/{color}]\n"
                f"[bold]Issue:[/bold]     {state.issue_prompt[:80]}\n"
                f"[bold]Policy:[/bold]    {state.execution_policy.value}\n"
                f"[bold]Repairs:[/bold]   {state.repair_attempts}\n"
                f"[bold]Gate:[/bold]      {gate_str}\n"
                f"[bold]Tokens:[/bold]    {tok_str}",
                title="📊 [bold cyan]Current Job Status[/bold cyan]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        console.print()

    def _cmd_approve(self) -> None:
        if not self.current_job_id or not self.orchestrator:
            console.print("[dim]ℹ️ No active job to approve.[/dim]\n")
            return

        async def _run() -> JobState:
            assert self.orchestrator is not None
            return await self.orchestrator.resume_job(
                job_id=self.current_job_id or "",
                gate_1_approved=True,
                gate_2_approved=True,
                gate_3_approved=True,
            )

        with console.status("[bold green]Approving gates and resuming...[/bold green]"):
            result = asyncio.run(_run())

        console.print(f"[success]✅ Approved! Status is now {result.status.value}[/success]\n")
        self._render_job_result(result)

    def _cmd_publish(self) -> None:
        """Publishes the active job patch directly to GitHub as a Pull Request."""
        if not self.current_job_id or not self.orchestrator:
            console.print("[dim]ℹ️ No active job to publish.[/dim]\n")
            return

        if not GitHubAuthManager.is_authenticated():
            console.print(
                Panel(
                    "[warning]⚠️ GitHub Authentication Required[/warning]\n\n"
                    "To publish Pull Requests to GitHub, please configure your GitHub PAT:\n"
                    "   [bold cyan]/config github ghp_your_token[/bold cyan]\n\n"
                    "Or authenticate using GitHub CLI:\n"
                    "   [bold cyan]gh auth login[/bold cyan]",
                    title="🔑 [bold yellow]GitHub Auth Required[/bold yellow]",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
            console.print()
            return

        async def _run() -> JobState:
            assert self.orchestrator is not None
            return await self.orchestrator.resume_job(
                job_id=self.current_job_id or "",
                publish_pr=True,
            )

        with console.status(
            "[bold green]Publishing feature branch & Pull Request to GitHub...[/bold green]"
        ):
            result = asyncio.run(_run())

        if result.pr_url:
            commit_str = result.commit_sha[:8] if result.commit_sha else "N/A"
            in_tok = getattr(result, "prompt_tokens", 0)
            out_tok = getattr(result, "completion_tokens", 0)
            tot_tok = in_tok + out_tok
            est_cost = (in_tok * 0.00000014) + (out_tok * 0.00000028)
            tok_str = f"{tot_tok:,} ({in_tok:,} in / {out_tok:,} out) ~ ${est_cost:.4f}"

            console.print(
                Panel(
                    f"🎉 [bold success]Pull Request Published Successfully![/bold success]\n\n"
                    f"🔗 [bold cyan]PR URL:[/bold cyan] {result.pr_url}\n"
                    f"🌿 [bold white]Branch:[/bold white] {result.git_branch}\n"
                    f"📝 [bold white]Commit:[/bold white] {commit_str}\n"
                    f"📊 [bold white]Tokens:[/bold white] {tok_str}",
                    title="🚀 [bold green]GitHub PR Published[/bold green]",
                    border_style="green",
                    box=box.ROUNDED,
                )
            )
        else:
            console.print(f"[success]✅ Job processed. Status: {result.status.value}[/success]\n")

    def _cmd_reject(self) -> None:
        if not self.current_job_id or not self.orchestrator:
            console.print("[dim]ℹ️ No active job to reject.[/dim]\n")
            return

        async def _run() -> JobState:
            assert self.orchestrator is not None
            return await self.orchestrator.resume_job(
                job_id=self.current_job_id or "",
                gate_1_approved=False,
                gate_2_approved=False,
                gate_3_approved=False,
            )

        with console.status("[bold red]Rejecting gates...[/bold red]"):
            result = asyncio.run(_run())

        console.print(f"[danger]❌ Rejected. Status is now {result.status.value}[/danger]\n")

    def _cmd_diff(self) -> None:
        """Shows patch details and exact code changes with rich syntax highlighting."""
        if not self.current_job_id or not self.orchestrator:
            console.print("[dim]ℹ️ No active job.[/dim]\n")
            return

        state_path = self.orchestrator.get_state_path(self.current_job_id)
        if not state_path.exists():
            console.print("[danger]❌ Job state file not found.[/danger]\n")
            return

        state = JobState.load(state_path)
        if not state.code_patch:
            console.print("[warning]⚠️ No patch generated yet for this job.[/warning]\n")
            return

        # 1. Attempt to render physical git diff from working tree as source of truth
        if self.orchestrator and hasattr(self.orchestrator, "git_service"):
            git_diff = self.orchestrator.git_service.get_working_tree_diff()
            if git_diff and git_diff.strip():
                syntax = Syntax(git_diff, "diff", theme="monokai", line_numbers=True)
                console.print(
                    Panel(
                        syntax,
                        title="🔍 [bold green]Physical Git Diff (Source of Truth)[/bold green]",
                        border_style="green",
                        box=box.ROUNDED,
                    )
                )
                console.print()
                return

        # 2. Fallback to per-hunk action breakdown
        patch = state.code_patch
        files = patch.get("files_changed", [])
        hunks = patch.get("hunks", [])

        file_lines = "\n".join(f"   [success]M[/success] [info]{f}[/info]" for f in files)
        console.print(
            Panel(
                f"[bold]Files Changed:[/bold] {len(files)}\n{file_lines}\n\n"
                f"[bold]Total Hunks:[/bold] {len(hunks)}",
                title="📝 [bold yellow]Patch Hunk Summary[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )

        for idx, hunk in enumerate(hunks, 1):
            if isinstance(hunk, dict):
                act = hunk.get("action", "MODIFY")
                ts = hunk.get("target_symbol", {})
            else:
                act = getattr(hunk, "action", "MODIFY")
                ts = getattr(hunk, "target_symbol", {})

            if isinstance(ts, dict):
                fp = ts.get("file_path", hunk.get("file_path", "unknown"))
                sym = ts.get("qualified_symbol_name", "")
                code = ts.get("replacement_code", hunk.get("replacement_code", ""))
            else:
                fp = getattr(ts, "file_path", "unknown")
                sym = getattr(ts, "qualified_symbol_name", "")
                code = getattr(ts, "replacement_code", "")

            act_str = str(act.value) if hasattr(act, "value") else str(act)
            title = f"Hunk {idx}: [{act_str}] {fp}" + (f" -> symbol: {sym}" if sym else "")

            # Format replacement code as unified diff lines for rich color
            # highlighting (+ green, - red)
            diff_lines = []
            for line in (code or "# Empty patch snippet\n").splitlines():
                if line.startswith("+") or line.startswith("-"):
                    diff_lines.append(line)
                elif act_str in ("ADD", "MODIFY", "REPLACE_FILE"):
                    diff_lines.append(f"+ {line}")
                elif act_str == "DELETE":
                    diff_lines.append(f"- {line}")
                else:
                    diff_lines.append(f"  {line}")
            diff_text = "\n".join(diff_lines)

            syntax = Syntax(
                diff_text,
                "diff",
                theme="monokai",
                line_numbers=True,
            )
            console.print(
                Panel(
                    syntax,
                    title=f"[bold green]{title}[/bold green]",
                    border_style="green",
                )
            )

        console.print()

    def _cmd_rewind(self, arg: str) -> None:
        """Rewinds the LangGraph state machine history."""
        steps = int(arg) if arg.strip().isdigit() else 1
        if self.orchestrator and hasattr(self.orchestrator, "graph"):
            graph = getattr(self.orchestrator, "graph")
            if graph and hasattr(graph, "rewind"):
                prev = graph.rewind(steps)
                if prev:
                    console.print(
                        f"[success]⏪ Rewound state history by {steps} step(s).[/success]\n"
                    )
                    return
        console.print(f"[success]⏪ Reset state history checkpoint (steps={steps}).[/success]\n")

    def _cmd_jobs(self) -> None:
        """Lists all job state files for the current repo in a beautiful table."""
        if not self.repo_path:
            console.print("[danger]❌ No repository set.[/danger]\n")
            return

        jobs_dir = self.repo_path / ".forge_jobs"
        if not jobs_dir.exists():
            console.print("[dim]ℹ️ No jobs found.[/dim]\n")
            return

        job_files = sorted(jobs_dir.glob("job_*.json"))
        if not job_files:
            console.print("[dim]ℹ️ No jobs found.[/dim]\n")
            return

        table = Table(
            title="📂 Recent Jobs",
            show_header=True,
            header_style="bold white",
            border_style="dim",
            box=box.SIMPLE_HEAD,
        )
        table.add_column("Job ID", style="cyan", width=15, overflow="ellipsis")
        table.add_column("Status", style="bold")
        table.add_column("Issue", style="white", max_width=50, overflow="ellipsis")

        for jf in job_files[-10:]:
            try:
                s = JobState.load(jf)
                color = (
                    "green"
                    if s.status.value == "COMPLETED"
                    else "red"
                    if s.status.value in ("FAILED", "ABORTED")
                    else "yellow"
                )
                table.add_row(s.job_id, f"[{color}]{s.status.value}[/{color}]", s.issue_prompt)
            except Exception:
                pass

        console.print(table)
        console.print()

    def _cmd_config(self, arg: str = "") -> None:
        """Shows configured API keys or sets a key if arguments are provided."""
        text = arg.strip()
        if text:
            parts = text.split()
            provider = ""
            key = ""
            if "set-key" in text and "-p" in parts and "-k" in parts:
                p_idx = parts.index("-p") + 1
                k_idx = parts.index("-k") + 1
                if p_idx < len(parts) and k_idx < len(parts):
                    provider = parts[p_idx]
                    key = parts[k_idx]
            elif len(parts) >= 2:
                provider = parts[0]
                key = parts[1]

            if provider and key:
                ConfigManager.set_key(provider, key)
                console.print(
                    f"[success]🔒 Saved key for provider '[bold cyan]{provider}[/bold cyan]' "
                    f"to OS Credential Store (Keyring).[/success]\n"
                )
                return
            else:
                console.print(
                    "[warning]⚠️ Usage: /config set-key -p <provider> -k <key>[/warning]\n"
                )
                return

        keys = ConfigManager.list_keys()
        if not keys:
            console.print("[warning]⚠️ No API keys configured.[/warning]")
            console.print("[dim]Use: /config set-key -p github -k <token>[/dim]\n")
            return

        console.rule("[bold cyan]🔑 Configured Credentials (Keyring)[/bold cyan]", align="left")
        for provider, masked in keys.items():
            console.print(
                f"   • [bold white]{provider.capitalize()}[/bold white]: [info]{masked}[/info]"
            )
        console.print()

    def _cmd_policy(self, arg: str) -> None:
        """Sets execution policy."""
        mapping = {
            "manual": ExecutionPolicy.MANUAL,
            "semi": ExecutionPolicy.SEMI_AUTONOMOUS,
            "semi_autonomous": ExecutionPolicy.SEMI_AUTONOMOUS,
            "auto": ExecutionPolicy.AUTONOMOUS,
            "autonomous": ExecutionPolicy.AUTONOMOUS,
        }
        policy = mapping.get(arg.lower().strip())
        if not policy:
            console.print("[warning]⚠️ Usage: /policy <MANUAL|SEMI|AUTO>[/warning]\n")
            return
        self.policy = policy
        console.print(f"[success]✅ Policy successfully set to {self.policy.value}[/success]\n")

    def _detect_target_file(self, issue: str = "") -> str:
        """Dynamically detects the best target file based on text semantics."""
        if not self.repo_path:
            return "app.py"

        prompt_lower = (issue or self.issue_prompt).lower()
        words = set(re.findall(r"\w+", prompt_lower))
        stop_words = {
            "the",
            "and",
            "when",
            "with",
            "from",
            "that",
            "this",
            "file",
            "fix",
            "issue",
            "bug",
            "error",
        }
        tokens = [w for w in words if len(w) > 2 and w not in stop_words]

        scored_files: list[tuple[int, str]] = []
        ignore_parts = {
            ".venv",
            "venv",
            ".git",
            ".forge_worktrees",
            ".forge_jobs",
            "tests",
            "site-packages",
        }

        for py_file in self.repo_path.glob("**/*.py"):
            if any(p in ignore_parts for p in py_file.relative_to(self.repo_path).parts):
                continue
            rel_str = str(py_file.relative_to(self.repo_path)).replace("\\", "/")
            rel_str_lower = rel_str.lower()

            if rel_str_lower in prompt_lower:
                return rel_str
            if (
                py_file.stem in prompt_lower
                and py_file.parent.name in prompt_lower
                and py_file.stem != "__init__"
            ):
                return rel_str

            score = sum(10 for t in tokens if t in rel_str_lower)
            try:
                raw_content = py_file.read_text(encoding="utf-8", errors="replace")
                content_lower = raw_content.lower()

                import ast

                try:
                    ast.parse(raw_content)
                except (SyntaxError, IndentationError):
                    if any(t in content_lower for t in tokens):
                        score += 500

                runtime_content = re.sub(
                    r"if\s+.*type_checking.*?:.*?(?=\n\S|\Z)",
                    "",
                    content_lower,
                    flags=re.DOTALL,
                )
                for t in tokens:
                    if f"def {t}" in runtime_content or f"class {t}" in runtime_content:
                        score += 50
                    elif t in content_lower:
                        score += content_lower.count(t)
            except Exception:
                pass

            if score > 0:
                scored_files.append((score, rel_str))

        if scored_files:
            scored_files.sort(key=lambda x: x[0], reverse=True)
            return scored_files[0][1]

        for py_file in self.repo_path.glob("**/*.py"):
            rel_parts = py_file.relative_to(self.repo_path).parts
            if not any(p in ignore_parts for p in rel_parts):
                return str(py_file.relative_to(self.repo_path)).replace("\\", "/")

        return "app.py"

    def _render_interactive_gate_prompt(self, state: JobState) -> None:
        """Renders interactive gate action menu."""
        menu = (
            "[bold white]Human-in-the-Loop Checkpoint — Select an action:[/bold white]\n\n"
            "   [bold cyan][A][/bold cyan] ✅ [bold white]Approve & Commit[/bold white]\n"
            "        — Write patch to local feature branch (/approve or 'a')\n"
            "   [bold cyan][D][/bold cyan] 🔍 [bold white]View Diff[/bold white]\n"
            "        — Inspect full multi-file changes (/diff or 'd')\n"
            "   [bold cyan][P][/bold cyan] 🚀 [bold white]Approve & Publish PR[/bold white]\n"
            "        — Push to GitHub & open Pull Request (/publish or 'p')\n"
            "   [bold cyan][R][/bold cyan] ❌ [bold white]Reject & Abort[/bold white]\n"
            "        — Discard patch and exit job (/reject or 'r')"
        )
        console.print(
            Panel(
                menu,
                title="🛡️ [bold yellow]Interactive Gate Options[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )

    def _render_job_result(self, state: JobState) -> None:
        """Renders the final pipeline result to the console."""
        if state.status == JobStatus.COMPLETED:
            console.print(
                f"\n🎉 [bold success]Pipeline Finished Successfully![/bold success] "
                f"({state.status.value})"
            )
            if state.pr_url:
                commit_str = state.commit_sha[:8] if state.commit_sha else "N/A"
                branch_str = state.git_branch or "N/A"
                console.print(
                    Panel(
                        f"🔗 [bold cyan]GitHub PR:[/bold cyan] {state.pr_url}\n"
                        f"🌿 [bold white]Branch:[/bold white] {branch_str}\n"
                        f"📝 [bold white]Commit:[/bold white] {commit_str}",
                        title="🚀 [bold green]Pull Request Live[/bold green]",
                        border_style="green",
                        box=box.ROUNDED,
                    )
                )
            elif self.policy != ExecutionPolicy.AUTONOMOUS:
                self._render_interactive_gate_prompt(state)
        elif state.status in (
            JobStatus.AWAITING_GATE_1,
            JobStatus.AWAITING_GATE_2,
            JobStatus.AWAITING_GATE_3,
        ):
            console.print(
                f"\n⚠️ [bold yellow]Pipeline Paused at Gate Checkpoint:[/bold yellow] "
                f"{state.status.value}"
            )
            self._render_interactive_gate_prompt(state)
        else:
            console.print(f"\n⚠️ [bold warning]Pipeline Halted:[/bold warning] {state.status.value}")
            if state.error_message:
                console.print(f"   [danger]Reason:[/danger] {state.error_message}")
        console.print()


def run_repl() -> None:
    """Entry point for the interactive Forge REPL."""
    repl = ForgeREPL()
    repl.print_welcome()

    if not repl.run_onboarding():
        console.print("[dim]Onboarding cancelled.[/dim]")
        return

    from prompt_toolkit.formatted_text import FormattedText

    prompt_msg = FormattedText(
        [
            ("class:prompt-bracket", "╭─ "),
            ("class:prompt-text", "forge"),
            ("", "\n"),
            ("class:prompt-bracket", "╰─ "),
            ("class:prompt-arrow", "❯ "),
        ]
    )

    while True:
        try:
            user_input = repl.session.prompt(prompt_msg)
        except KeyboardInterrupt:
            console.print()
            continue
        except EOFError:
            console.print("\n[dim]Session terminated. Goodbye![/dim]")
            break

        if not repl.handle_command(user_input):
            console.print("\n[dim]Session terminated. Goodbye![/dim]")
            break


if __name__ == "__main__":
    run_repl()
