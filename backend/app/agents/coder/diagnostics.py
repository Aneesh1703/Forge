"""
Phase 9D: Traceback Parser & Diagnosis Engine
Extracts stack frames, exception types, and root cause diagnosis from test outputs.
"""

import re
from dataclasses import dataclass, field


@dataclass
class TracebackFrame:
    """Represents a single frame in an exception traceback stack."""

    file_path: str
    line_number: int
    function_name: str = ""
    code_line: str = ""


@dataclass
class FailureDiagnosis:
    """Structured diagnosis extracted from raw test failure outputs."""

    error_type: str = "UnknownError"
    error_message: str = ""
    failing_file: str | None = None
    failing_line: int | None = None
    frames: list[TracebackFrame] = field(default_factory=list)
    root_cause_summary: str = ""


class TracebackParser:
    """Parses raw pytest stdout/stderr tracebacks into structured FailureDiagnosis."""

    FRAME_PATTERN = re.compile(
        r'File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>\w+))?'
    )
    ERROR_PATTERN = re.compile(
        r"^(?P<error_type>[A-Za-z_][A-Za-z0-9_]*Error|[A-Za-z_][A-Za-z0-9_]*Exception):\s*(?P<msg>.*)$",
        re.MULTILINE,
    )
    FAIL_LINE_PATTERN = re.compile(
        r"^(?P<file>[^\s:]+):(?P<line>\d+):\s*(?P<error_type>\w+)", re.MULTILINE
    )

    @classmethod
    def parse(cls, traceback_str: str) -> FailureDiagnosis:
        """Parses raw traceback string into a FailureDiagnosis object."""
        if not traceback_str or not traceback_str.strip():
            return FailureDiagnosis(root_cause_summary="No traceback captured.")

        frames: list[TracebackFrame] = []
        failing_file: str | None = None
        failing_line: int | None = None
        error_type = "TestFailure"
        error_message = ""

        # Extract frames
        lines = traceback_str.splitlines()
        for i, line in enumerate(lines):
            match = cls.FRAME_PATTERN.search(line)
            if match:
                f_file = match.group("file")
                f_line = int(match.group("line"))
                f_func = match.group("func") or ""
                c_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                frame = TracebackFrame(
                    file_path=f_file,
                    line_number=f_line,
                    function_name=f_func,
                    code_line=c_line,
                )
                frames.append(frame)
                failing_file = f_file
                failing_line = f_line

        # Extract error type & message
        err_match = cls.ERROR_PATTERN.search(traceback_str)
        if err_match:
            error_type = err_match.group("error_type")
            error_message = err_match.group("msg").strip()
        else:
            fail_match = cls.FAIL_LINE_PATTERN.search(traceback_str)
            if fail_match:
                if not failing_file:
                    failing_file = fail_match.group("file")
                    failing_line = int(fail_match.group("line"))
                error_type = fail_match.group("error_type")

        if not error_message:
            # Fallback to last non-empty line
            non_empty = [line_item.strip() for line_item in lines if line_item.strip()]
            error_message = non_empty[-1] if non_empty else "Unknown test failure"

        root_cause = (
            f"[{error_type}] in {failing_file or 'unknown'}:{failing_line or '?'}: {error_message}"
        )

        return FailureDiagnosis(
            error_type=error_type,
            error_message=error_message,
            failing_file=failing_file,
            failing_line=failing_line,
            frames=frames,
            root_cause_summary=root_cause,
        )
