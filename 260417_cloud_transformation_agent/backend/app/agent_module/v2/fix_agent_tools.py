"""Tool-calling Terraform fix agent.

The agent has direct access to:
  • the deploy working directory (read/write/edit .tf files)
  • a sandboxed terraform CLI (validate/fmt/plan/init only — no apply)

It runs an iterative tool-calling loop, taking actions one at a time, until
it either signals success via the ``done`` tool or exhausts the iteration
budget.  Every action is reported back to the deploy log so the user sees
the agent's reasoning step-by-step.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .strategy import _build_client

logger = logging.getLogger(__name__)


# ── Tool schemas (OpenAI function-calling shape) ──────────────────

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List all editable files in the working directory (.tf/.tfvars/.md/.json). "
                "Returns relative paths and sizes."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the full content of a specific file. "
                "Path is relative to the working directory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path, e.g. 'main.tf' or 'modules/networking/main.tf'",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Make a targeted edit to a file by replacing one occurrence of "
                "old_string with new_string.  old_string must match exactly once in "
                "the file (use enough surrounding context to make it unique). "
                "Preferred over write_file for small surgical changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":       {"type": "string"},
                    "old_string": {"type": "string", "description": "Exact text to find (must match exactly once)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Overwrite the entire content of a file (or create a new one). "
                "Use only when you need to replace most of the file or create a new file. "
                "For small edits, prefer edit_file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string"},
                    "content": {"type": "string", "description": "Full new content of the file"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_terraform",
            "description": (
                "Run a read-only terraform command in the working directory. "
                "Use this to verify your edits before signalling done. "
                "Allowed commands: init (with -backend=false), validate, fmt, plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["init", "validate", "fmt", "plan"],
                    },
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional additional flags",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_az",
            "description": (
                "Run a **read-only** Azure CLI command to inspect the live subscription. "
                "Useful for verifying VM SKU availability per region, current quota usage, "
                "subscription policies, existing resources, etc.  Write operations "
                "(create/delete/update/set/...) are blocked.\n\n"
                "Common useful queries:\n"
                "  az vm list-skus --location <region> --resource-type virtualMachines --output json\n"
                "  az vm list-usage --location <region> --output json\n"
                "  az network vnet list --output json\n"
                "  az account show\n"
                "  az policy assignment list --output json\n\n"
                "Auth: uses the deploy session's ARM_SUBSCRIPTION_ID automatically. "
                "Requires `az login` on the host (or DefaultAzureCredential)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Arguments after 'az'.  Example: ['vm', 'list-skus', '--location', 'koreacentral', '--resource-type', 'virtualMachines']",
                    },
                },
                "required": ["args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": (
                "Signal that you have finished editing.  After this, the system will run "
                "`terraform apply` automatically.  Only call this once you've verified "
                "with at least one `run_terraform validate` (or plan) call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "한국어 한두 문장으로 어떤 변경을 했고 왜 그런 변경이 필요한지 요약",
                    },
                },
                "required": ["summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "give_up",
            "description": (
                "Use only when you cannot fix the problem with code edits alone "
                "(e.g., needs Azure quota increase, requires manual subscription policy change). "
                "After this, the deploy transitions to apply_failed for manual user intervention."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason":      {"type": "string", "description": "한국어로 왜 자동 수정이 불가능한지"},
                    "user_action": {"type": "string", "description": "한국어로 사용자가 직접 해야 할 일"},
                },
                "required": ["reason", "user_action"],
            },
        },
    },
]


_SYSTEM_PROMPT = """\
당신은 자율적 Terraform 수정 에이전트입니다.  방금 ``terraform apply`` 가 실패했고,
당신의 임무는 도구를 사용해 워크 디렉토리의 코드를 직접 분석/수정하고 다시 apply 가
통과하도록 만드는 것입니다.

**도구:**
  • list_files       — 편집 가능한 파일 목록
  • read_file        — 파일 내용 읽기
  • edit_file        — 정밀 편집 (작은 변경에 우선)
  • write_file       — 파일 전체 덮어쓰기 (큰 변경)
  • run_terraform    — init/validate/fmt/plan 으로 수정 검증 (apply 는 허용 X)
  • run_az           — Azure CLI 로 라이브 정보 조회 (read-only):
                       리전별 VM SKU 가용성, 현재 quota, 정책, 리소스 등을 확인
  • done             — 수정 완료 신호 → 시스템이 apply 재실행
  • give_up          — 코드 수정으로 해결 불가능할 때만 (예: quota 부족)

**작업 흐름 (권장):**
  1. list_files 로 디렉토리 구조 파악
  2. 에러 메시지에 언급된 파일을 read_file 로 확인
  3. 필요하면 root main.tf 와 module 호출부도 읽어서 변수 흐름 추적
  4. edit_file (또는 write_file) 로 수정
  5. run_terraform validate (또는 plan) 으로 검증
  6. 검증 통과 시 done

**중요한 원칙:**
  1. 한 번에 한 가지 문제만 고치세요 (다중 추측성 수정 X).
  2. 변수 override 흐름을 추적하세요. module/variables.tf 의 default 만 고치고
     root 에서 override 하면 무용지물입니다.
     예: modules/compute/variables.tf 의 var.tags default 를 고쳤는데
         root main.tf 에서 module "compute" { tags = var.tags } 로 호출 →
         root variables.tf 의 var.tags 가 우선 → 모듈 default 변경은 무효
     → 이 경우 root variables.tf 를 고쳐야 함
  3. SKU 가용성, 명명 충돌, CIDR 충돌 등은 직접 결정해서 수정 (사용자에게 묻지 말 것).
     특히 **VM SKU 관련 에러** (NotAvailableForSubscription, SkuNotAvailable, OutOfCapacity)
     는 run_az 로 해당 리전의 실제 가용 SKU 를 조회한 뒤 fix 에 반영하세요:
       run_az(args=["vm", "list-skus", "--location", "koreacentral",
                    "--resource-type", "virtualMachines", "--output", "json",
                    "--query", "[?capabilities[?name=='vCPUs' && value=='2']].name | [0:20]"])
  4. **Quota 에러** (QuotaExceeded, OperationNotAllowed) 도 run_az 로 확인:
       run_az(args=["vm", "list-usage", "--location", "koreacentral", "--output", "json"])
     → currentValue / limit 비교해서 더 작은 SKU 로 교체 또는 리소스 수 줄이기
  5. 수정 후 반드시 run_terraform validate 로 문법 검증.  통과 후 done.
  6. give_up 은 정말 코드로 해결 불가능한 경우만:
     - 모든 VM SKU 가 quota 초과 (Azure Support 티켓 필요)
     - Subscription-level policy 변경 불가 (조직 정책)
     - 외부 시스템 의존 (Azure AD app, 도메인 등)

**금지:**
  • 사용자에게 "파일 내용을 보내주세요" 같은 요청 X — read_file 도구 사용
  • run_terraform apply / destroy 시도 X — apply 는 시스템이 자동 실행
  • 워크 디렉토리 밖 경로 접근 X — 도구가 자동 거부함
"""


# ── Tool execution sandbox ─────────────────────────────────────────

_ALLOWED_SUFFIXES = (".tf", ".tfvars", ".md", ".json")


def _safe_path(work: Path, rel: str) -> Optional[Path]:
    """Resolve ``rel`` inside ``work``, rejecting traversal / invalid suffixes."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    rel = rel.lstrip("./")
    if rel.startswith("terraform/"):
        rel = rel[len("terraform/"):]
    work_resolved = work.resolve()
    full = (work_resolved / rel).resolve()
    try:
        full.relative_to(work_resolved)
    except ValueError:
        return None
    if full.suffix and full.suffix not in _ALLOWED_SUFFIXES:
        return None
    return full


def _tool_list_files(work: Path) -> Dict[str, Any]:
    files = []
    for p in sorted(work.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix not in _ALLOWED_SUFFIXES:
            continue
        rel = p.relative_to(work)
        if rel.parts and rel.parts[0] in (".terraform",):
            continue
        files.append({"path": str(rel), "size": p.stat().st_size})
    return {"files": files, "count": len(files)}


def _tool_read_file(work: Path, path: str) -> Dict[str, Any]:
    full = _safe_path(work, path)
    if full is None:
        return {"error": f"Invalid or disallowed path: {path}"}
    if not full.is_file():
        return {"error": f"File not found: {path}"}
    content = full.read_text(encoding="utf-8")
    return {"path": str(full.relative_to(work)), "content": content, "size": len(content)}


def _tool_edit_file(work: Path, path: str, old_string: str, new_string: str) -> Dict[str, Any]:
    full = _safe_path(work, path)
    if full is None:
        return {"error": f"Invalid path: {path}"}
    if not full.is_file():
        return {"error": f"File not found: {path}"}
    content = full.read_text(encoding="utf-8")
    occurrences = content.count(old_string)
    if occurrences == 0:
        return {"error": "old_string not found — make it more specific or use read_file to verify content"}
    if occurrences > 1:
        return {"error": f"old_string matches {occurrences} times — include more surrounding context to make it unique"}
    new_content = content.replace(old_string, new_string)
    full.write_text(new_content, encoding="utf-8")
    return {
        "path": str(full.relative_to(work)),
        "edited": True,
        "delta_chars": len(new_string) - len(old_string),
    }


def _tool_write_file(work: Path, path: str, content: str) -> Dict[str, Any]:
    full = _safe_path(work, path)
    if full is None:
        return {"error": f"Invalid path: {path}"}
    full.parent.mkdir(parents=True, exist_ok=True)
    is_new = not full.exists()
    full.write_text(content, encoding="utf-8")
    return {"path": str(full.relative_to(work)), "written": True, "created": is_new, "size": len(content)}


# az CLI write verbs that are blocked.  We don't try to be exhaustive — just
# the obvious mutating verbs.  Read commands (list/show/get/...) pass through.
_AZ_BLOCKED = {
    "create", "delete", "update", "set", "deallocate", "restart",
    "start", "stop", "regenerate", "purge", "lock", "unlock",
    "add", "remove", "redeploy", "reimage", "redeploy-backup",
    "config", "import", "configure", "login", "logout",
}


def _validate_az_args(args: List[str]) -> Optional[str]:
    """Returns an error string if the command looks like a write op, else None."""
    if not args:
        return "args is empty"
    for tok in args:
        # Only check tokens that aren't flag values
        if tok.startswith("-"):
            break
        if tok in _AZ_BLOCKED:
            return f"Write operation '{tok}' not allowed — only read-only az commands"
    return None


def _tool_run_az(args: List[str]) -> Dict[str, Any]:
    err = _validate_az_args(args)
    if err:
        return {"error": err}
    cmd = ["az"] + list(args)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=120, check=False,
        )
        out = (proc.stdout or "")
        err_out = (proc.stderr or "")
        # Trim very long output (e.g., list-skus can be 100K+)
        if len(out) > 8000:
            out = out[:8000] + f"\n...[truncated, {len(out)} total chars; refine query with --query/--output to narrow down]"
        if len(err_out) > 1000:
            err_out = err_out[-1000:]
        return {
            "command":   " ".join(cmd),
            "exit_code": proc.returncode,
            "stdout":    out,
            "stderr":    err_out,
        }
    except subprocess.TimeoutExpired:
        return {"command": " ".join(cmd), "exit_code": -1, "stdout": "", "stderr": "timed out after 120s"}
    except FileNotFoundError:
        return {"error": "az CLI binary not found on host"}


def _tool_run_terraform(work: Path, command: str, extra_args: Optional[List[str]] = None) -> Dict[str, Any]:
    if command not in ("init", "validate", "fmt", "plan"):
        return {"error": f"Command not allowed: {command}"}
    cmd: List[str] = ["terraform", command, "-no-color"]
    if command == "init":
        cmd += ["-backend=false", "-input=false", "-upgrade=false"]
    elif command == "plan":
        cmd += ["-input=false"]
    if extra_args:
        cmd += list(extra_args)
    try:
        proc = subprocess.run(
            cmd, cwd=str(work),
            capture_output=True, text=True,
            timeout=180, check=False,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Trim very long output
        if len(out) > 4000:
            out = "...[truncated]...\n" + out[-4000:]
        return {
            "command":   " ".join(cmd),
            "exit_code": proc.returncode,
            "output":    out,
        }
    except subprocess.TimeoutExpired:
        return {"command": " ".join(cmd), "exit_code": -1, "output": "timed out after 180s"}
    except FileNotFoundError:
        return {"error": "terraform binary not found"}


# ── Main loop ──────────────────────────────────────────────────────

def _msg_to_dict(msg: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


def run_fix_agent(
    *,
    work_dir:               Path,
    error_log:              str,
    llm_deployment:         str,
    azure_openai_endpoint:  str,
    on_action:              Optional[Callable[[Dict[str, Any]], None]] = None,
    max_iterations:         int = 25,
    max_log_chars:          int = 8000,
) -> Dict[str, Any]:
    """Run the tool-calling fix loop.

    Args:
        work_dir: Sandboxed deploy working directory.
        error_log: Last N lines of terraform output (the actual error).
        on_action: Optional callback invoked after each tool call so the caller
                   can stream progress to the user.  Receives a dict with
                   {action, args, result_preview}.

    Returns:
        ``{"outcome": "done" | "give_up" | "exhausted" | "error",
           "summary": str, "user_action": str | None,
           "actions": [...], "iterations": int}``
    """
    client = _build_client(llm_deployment, azure_openai_endpoint)

    work = work_dir.resolve()
    error_tail = error_log[-max_log_chars:] if len(error_log) > max_log_chars else error_log

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Working directory: {work}\n\n"
                f"## terraform apply 에러 로그\n```\n{error_tail}\n```\n\n"
                f"위 에러를 분석하고, 도구를 사용해 코드를 수정하세요.  먼저 list_files 와 read_file 로 "
                f"관련 파일들을 확인하고, edit_file 또는 write_file 로 수정한 뒤, "
                f"run_terraform validate 로 검증하고 done 을 호출하세요."
            ),
        },
    ]

    actions: List[Dict[str, Any]] = []
    outcome = "exhausted"
    summary = ""
    user_action: Optional[str] = None
    iterations = 0

    # GPT-5/o-series uses max_completion_tokens, others use max_tokens
    token_kwargs: Dict[str, Any] = {}
    token_cap = int(os.getenv("FIX_AGENT_MAX_TOKENS", "4000"))
    dep_lower = (llm_deployment or "").lower()
    if any(tag in dep_lower for tag in ("gpt-5", "o1", "o3")):
        token_kwargs["max_completion_tokens"] = token_cap
    else:
        token_kwargs["max_tokens"] = token_cap

    for iter_idx in range(max_iterations):
        iterations = iter_idx + 1
        try:
            resp = client.chat.completions.create(
                model=llm_deployment,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                **token_kwargs,
            )
        except Exception as e:
            logger.exception("LLM call failed at iteration %d", iter_idx)
            outcome = "error"
            summary = f"LLM 호출 실패: {e}"
            break

        msg = resp.choices[0].message
        messages.append(_msg_to_dict(msg))

        if not msg.tool_calls:
            # Agent stopped without calling done/give_up — treat as exhausted with content
            summary = (msg.content or "").strip() or "에이전트가 도구를 호출하지 않고 종료했습니다"
            break

        terminal = False
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "done":
                summary = args.get("summary") or "(요약 없음)"
                outcome = "done"
                actions.append({"tool": "done", "args": args, "result": "→ apply 재실행"})
                if on_action:
                    on_action({"tool": "done", "args": args, "result_preview": "→ apply 재실행"})
                terminal = True
                break

            if name == "give_up":
                summary = args.get("reason") or "코드 수정 불가"
                user_action = args.get("user_action") or ""
                outcome = "give_up"
                actions.append({"tool": "give_up", "args": args, "result": "→ 사용자 개입 필요"})
                if on_action:
                    on_action({"tool": "give_up", "args": args, "result_preview": "→ 사용자 개입 필요"})
                terminal = True
                break

            # Execute the action tool
            if name == "list_files":
                result = _tool_list_files(work)
            elif name == "read_file":
                result = _tool_read_file(work, args.get("path", ""))
            elif name == "edit_file":
                result = _tool_edit_file(
                    work,
                    args.get("path", ""),
                    args.get("old_string", ""),
                    args.get("new_string", ""),
                )
            elif name == "write_file":
                result = _tool_write_file(work, args.get("path", ""), args.get("content", ""))
            elif name == "run_terraform":
                result = _tool_run_terraform(
                    work,
                    args.get("command", ""),
                    args.get("extra_args"),
                )
            elif name == "run_az":
                result = _tool_run_az(args.get("args") or [])
            else:
                result = {"error": f"Unknown tool: {name}"}

            # Build a compact preview for the deploy log
            preview = ""
            if name == "list_files":
                preview = f"{result.get('count', 0)} files"
            elif name == "read_file":
                size = result.get("size") or 0
                preview = f"{result.get('path','?')}  ({size} bytes)" + (f"  ERROR: {result.get('error')}" if result.get("error") else "")
            elif name == "edit_file":
                if result.get("error"):
                    preview = f"ERROR: {result['error']}"
                else:
                    preview = f"{result.get('path','?')}  Δ {result.get('delta_chars', 0)} chars"
            elif name == "write_file":
                if result.get("error"):
                    preview = f"ERROR: {result['error']}"
                else:
                    preview = f"{result.get('path','?')}  ({'created' if result.get('created') else 'updated'}, {result.get('size', 0)} bytes)"
            elif name == "run_terraform":
                if "error" in result:
                    preview = f"ERROR: {result['error']}"
                else:
                    preview = f"rc={result.get('exit_code')}"
            elif name == "run_az":
                if "error" in result:
                    preview = f"ERROR: {result['error']}"
                else:
                    out_len = len(result.get("stdout", ""))
                    preview = f"rc={result.get('exit_code')}  ({out_len} bytes)"

            actions.append({"tool": name, "args": args, "result_preview": preview})
            if on_action:
                on_action({"tool": name, "args": args, "result_preview": preview})

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      json.dumps(result, default=str)[:8000],
            })

        if terminal:
            break

    return {
        "outcome":     outcome,
        "summary":     summary,
        "user_action": user_action,
        "actions":     actions,
        "iterations":  iterations,
    }
