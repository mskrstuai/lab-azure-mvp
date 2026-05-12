"""LLM-driven Terraform code generation via the write_file tool-call pattern.

Replaces the deterministic ``generators.py`` modules.  The LLM repeatedly
calls a single ``write_file(path, content)`` tool — one call per Terraform
file it wants in the plan's work dir.  When it stops calling, generation is
complete.  Backend partitions the collected files into root + sub-modules
and returns ``(root, modules, log_lines)`` for the existing pipeline.

This pattern avoids the structured-output schema constraints (every field
required, no defaults) and lets the LLM decide module structure dynamically.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .context import MigrationContext
from .schema import TerraformModule
from .strategy import StrategyOutput, _build_client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Tool definition (OpenAI function-calling format)
# ──────────────────────────────────────────────────────────────────

_TOOL_WRITE_FILE = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": (
            "Write a single Terraform (or README/markdown) file to the plan's "
            "Terraform work directory.  Call this once per file you want in "
            "the plan.  Path is relative to the Terraform root — use "
            '"main.tf" / "providers.tf" / "variables.tf" / "outputs.tf" for '
            'root files, and "modules/<module_name>/<file>" for sub-modules. '
            "Files are accumulated and written to disk only after you finish "
            "(i.e., when you stop calling tools)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path inside the terraform root.",
                },
                "content": {
                    "type": "string",
                    "description": "Full HCL / markdown content of the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
}

_TOOLS = [_TOOL_WRITE_FILE]


# ──────────────────────────────────────────────────────────────────
# System / user prompt
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
당신은 Azure terraform (azurerm provider) 코드를 작성하는 시니어 인프라
엔지니어입니다.  입력으로 받은 AWS 아키텍처 + Azure 매핑 + Azure Policy +
사용자 메모를 모두 검토한 뒤, ``write_file(path, content)`` 도구를 반복
호출해서 즉시 ``terraform init && terraform apply`` 가능한 multi-module
Terraform 코드를 작성합니다.

## 작성 원칙

1. **매핑은 ground truth.**  ``mappings[*].azure_resource_type`` 이 가리키는
   azurerm 리소스를 그대로 사용.  SKU/instance class 도 매핑이 결정한 값을
   따름.  새로 골라 바꾸지 마세요.

2. **모듈 분할은 자율.**  보통 networking / compute / database / storage
   네 모듈로 가지만, 입력 리소스에 맞게 자유롭게 조정.  각 모듈은
   ``modules/<name>/main.tf|variables.tf|outputs.tf``.

3. **Root 모듈**: ``providers.tf`` (azurerm provider 블록, 버전 ~> 4.0) +
   ``main.tf`` (resource_group + module 호출) + ``variables.tf`` (공통 변수)
   + ``outputs.tf``.  ``README.md`` 권장.

4. **정책 강제 반영.**  입력의 ``policy_modify`` / ``policy_deny`` 항목과
   각 정책에 매핑된 ``guidance: [...]`` (사용자가 사전 검토하고 저장한 자연어
   지침 배열), 그리고 입력의 최상위 ``general_guidance: [...]`` (모든 정책 /
   모든 plan 에 공통 적용되는 전역 지침) 을 모두 읽고 코드에 직접 반영하세요.
   • ``properties.allowSharedKeyAccess = false`` 정책 →
     ``shared_access_key_enabled = false`` 를 storage account 블록에 추가.
   • 정책 ``guidance`` 또는 ``general_guidance`` 에 cascading 효과 (provider
     블록의 storage_use_azuread 등) 가 적혀있으면 그것도 반영.
   • 같은 정책의 ``guidance`` 가 여러 줄이면 모두 종합적으로 고려.
   • ``general_guidance`` 는 정책 단위가 아닌 cross-cutting 규칙 — 모든
     리소스에 적용되는 명명 규칙, 태그 정책, 보안 기본값 등에 쓰입니다.

5. **azurerm attribute 이름은 정확히 snake_case.**  ARM property name
   (camelCase) 이 아님.  확실하지 않은 attribute 는 만들지 마세요.

6. **모듈 간 wiring**: 공통 값(location, resource_group_name, subscription_id,
   tags) 은 root variables 로 받고 각 모듈에 넘김.  의존성 (예: VM 이
   networking 의 subnet 사용) 은 ``module.networking.subnet_id_xxx`` 형태로
   참조.

7. **리소스 라벨**: HCL label 은 snake_case + 영숫자만 (예: AWS "data-prod"
   → resource "azurerm_storage_account" "data_prod").

8. **리소스 이름은 Azure 의 type-specific 제약을 반드시 만족**.  AWS 원본
   이름을 그대로 쓰면 길이 / 문자 제약을 위반하기 쉬움.  **각 리소스 타입의
   제약을 알고, sanitize + truncate + 짧은 random 접미사** 패턴으로 항상
   안전하게 생성하세요.

   **주요 제약 (terraform 코드를 짜기 전에 반드시 확인)**:

   | 리소스 타입                            | 길이      | 허용 문자                          | 유일성 |
   |---------------------------------------|-----------|------------------------------------|--------|
   | azurerm_storage_account               | **3–24**  | **lowercase + digits**             | global |
   | azurerm_key_vault                     | 3–24      | alphanumeric + `-`, 글자로 시작     | global |
   | azurerm_container_registry            | 5–50      | alphanumeric 만                    | global |
   | azurerm_mssql_server                  | 1–63      | lowercase alphanumeric + `-`        | global |
   | azurerm_cosmosdb_account              | 3–44      | lowercase alphanumeric + `-`        | global |
   | azurerm_postgresql_flexible_server    | 3–63      | lowercase alphanumeric + `-`        | global |
   | azurerm_function_app / app_service    | 2–60      | alphanumeric + `-`                 | global |
   | azurerm_linux_virtual_machine         | 1–64      | alphanumeric + `-_`                | RG-scope |
   | azurerm_windows_virtual_machine       | 1–15      | alphanumeric + `-`                 | RG-scope |
   | azurerm_virtual_network               | 1–80      | alphanumeric + `_.- `              | RG-scope |
   | azurerm_subnet                        | 1–80      | alphanumeric + `_.- `              | VNet-scope |
   | azurerm_network_security_group        | 1–80      | alphanumeric + `_.- `              | RG-scope |
   | azurerm_resource_group                | 1–90      | alphanumeric + `_().- `            | sub-scope |

   **권장 패턴 — 항상 random 접미사로 global uniqueness 확보**:

   ```hcl
   # providers.tf 에 random provider 추가 (~> 3.0)

   # 한 plan 의 모든 리소스가 공유할 short suffix
   resource "random_string" "suffix" {
     length  = 6
     upper   = false
     special = false
     numeric = true
   }

   # Storage Account — 24자 제약, lowercase + 숫자만
   #   원본 이름이 길면 sanitized prefix 를 잘라서 18자 + suffix 6자 = 24자.
   locals {
     sa_prefix = substr(
       replace(lower("<aws-bucket-name>"), "/[^a-z0-9]/", ""),  # 비허용 문자 제거
       0, 18,                                                    # 최대 18자 trim
     )
   }
   resource "azurerm_storage_account" "<label>" {
     name = "${local.sa_prefix}${random_string.suffix.result}"   # 최대 24자
     ...
   }

   # Key Vault — 24자, alphanumeric + `-`, 글자 시작
   resource "azurerm_key_vault" "<label>" {
     name = substr(
       "kv-${replace(lower("<base>"), "/[^a-z0-9-]/", "-")}-${random_string.suffix.result}",
       0, 24,
     )
     ...
   }
   ```

   **체크리스트**:
   • 각 이름이 해당 리소스의 길이/문자 제약 이내인지 확인.
   • Global-unique 리소스 (Storage, KeyVault, ACR, SQL, Cosmos, FunctionApp,
     Web App) 는 반드시 random suffix 포함.
   • 길이 초과 위험이 있으면 ``substr(...)`` 로 hard cap.
   • 비허용 문자 (대문자, ``-``, ``.``, ``_`` 등) 가 들어갈 가능성이 있는 source
     이름은 ``replace(lower(x), "/[^a-z0-9]/", "")`` 로 sanitize.

9. **Virtual Machine 의 인증은 Azure 키 페어로**.  AWS 의 .pem 키나 사용자
   입력 SSH 키를 그대로 사용하지 말고, terraform 안에서 키 페어를 새로
   생성해서 VM 에 연결하세요.  Linux VM 의 경우 권장 패턴:

   ```hcl
   # 키 페어 생성
   resource "tls_private_key" "<vm_label>_ssh" {
     algorithm = "RSA"
     rsa_bits  = 4096
   }

   # (선택) Azure 리소스로도 등록 — 콘솔에서 조회/재사용 가능
   resource "azurerm_ssh_public_key" "<vm_label>_ssh" {
     name                = "ssh-<vm_label>"
     resource_group_name = var.resource_group_name
     location            = var.location
     public_key          = tls_private_key.<vm_label>_ssh.public_key_openssh
     tags                = var.tags
   }

   # VM 이 그 키를 사용
   resource "azurerm_linux_virtual_machine" "<vm_label>" {
     ...
     admin_username = "azureuser"
     admin_ssh_key {
       username   = "azureuser"
       public_key = tls_private_key.<vm_label>_ssh.public_key_openssh
     }
     disable_password_authentication = true
     ...
   }

   # private key 는 sensitive output 으로 노출
   output "<vm_label>_private_key_pem" {
     value     = tls_private_key.<vm_label>_ssh.private_key_pem
     sensitive = true
   }
   ```

   • providers.tf 에 ``tls`` provider (~> 4.0) 도 함께 require.
   • Windows VM 의 경우 admin_password 를 random_password 로 생성하고 동일하게
     sensitive output 으로 노출.
   • 여러 VM 이 있으면 각각 별도 키 페어 생성 (한 키를 공유하지 말 것).

## 도구 사용 패턴

- 매 파일마다 ``write_file`` 한 번 호출.
- 한 호출에 여러 파일 넣지 말 것 — 1 호출 = 1 파일.
- 파일 경로:
    * root:        "main.tf", "providers.tf", "variables.tf", "outputs.tf", "README.md"
    * sub-module:  "modules/<name>/main.tf", "modules/<name>/variables.tf", ...
- 모든 파일 작성이 끝나면 도구 호출 없이 짧은 한국어 요약 메시지를 반환.

## 검증

작성된 코드는 다음 단계에서 ``terraform init && terraform validate`` 로
검증됩니다.  attribute 이름 / 블록 구조를 정확히 맞춰주세요.
"""


# ──────────────────────────────────────────────────────────────────
# Input trimming
# ──────────────────────────────────────────────────────────────────

def _trim_arch(arch: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "account_id":     arch.get("account_id"),
        "region":         arch.get("region"),
        "resource_group": arch.get("resource_group"),
    }
    vpcs = []
    for v in (arch.get("networking") or []):
        vpcs.append({
            "id":   v.get("id"),
            "cidr": v.get("cidr"),
            "name": v.get("name") or v.get("id"),
            "subnets": [
                {"id": s.get("id"), "name": s.get("name") or s.get("id"),
                 "cidr": s.get("cidr"), "az": s.get("availability_zone"),
                 "public": s.get("is_public")}
                for s in (v.get("subnets") or [])
            ],
            "security_groups": [
                {"id": sg.get("id"), "name": sg.get("name") or sg.get("id"),
                 "ingress": (sg.get("ingress") or [])[:20],
                 "egress":  (sg.get("egress")  or [])[:20]}
                for sg in (v.get("security_groups") or [])
            ],
        })
    out["vpcs"] = vpcs
    for key in ("ec2", "rds", "s3", "lambda", "elb"):
        items = arch.get(key) or []
        out[key] = [{k: v for k, v in r.items() if k != "raw"} for r in items[:50]]
    return out


def _trim_mappings(mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for m in mappings:
        if not m:
            continue
        out.append({
            "aws_key":             m.get("aws_key") or m.get("arn"),
            "aws_name":            m.get("aws_name"),
            "aws_type":            m.get("aws_type"),
            "azure_service":       m.get("azure_service"),
            "azure_resource_type": m.get("azure_resource_type"),
            "azure_sku":           m.get("azure_sku_suggestion") or m.get("azure_sku"),
            "azure_region":        m.get("azure_region"),
            "notes":               m.get("notes"),
        })
    return out


def _annotate_policies_with_guidance(
    field_ops: List[Dict[str, Any]],
    deny_rules: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Attach per-policy guidance entries (from the policy_guidance store) to
    each MODIFY / DENY entry under ``guidance: [text, ...]``.  Missing
    guidance just leaves the field absent — the LLM still sees the raw policy
    JSON in either case."""
    try:
        from . import policy_guidance as svc
    except Exception:
        return field_ops, deny_rules

    pid_set: List[str] = []
    for op in field_ops:
        pid = op.get("policy_definition_id")
        if pid:
            pid_set.append(pid)
    for d in deny_rules:
        pid = d.get("policy_definition_id")
        if pid:
            pid_set.append(pid)
    payload = svc.build_guidance_payload(pid_set)

    out_modify: List[Dict[str, Any]] = []
    for op in field_ops:
        item = dict(op)
        pid = op.get("policy_definition_id") or ""
        bucket = payload.get(pid)
        if bucket and bucket.get("entries"):
            item["guidance"] = bucket["entries"]
        out_modify.append(item)
    out_deny: List[Dict[str, Any]] = []
    for d in deny_rules:
        item = dict(d)
        pid = d.get("policy_definition_id") or ""
        bucket = payload.get(pid)
        if bucket and bucket.get("entries"):
            item["guidance"] = bucket["entries"]
        out_deny.append(item)
    return out_modify, out_deny


# ──────────────────────────────────────────────────────────────────
# Public entrypoint
# ──────────────────────────────────────────────────────────────────

def generate_terraform_code(
    ctx: MigrationContext,
    *,
    strategy: Optional[StrategyOutput] = None,
    llm_deployment: str,
    azure_openai_endpoint: str,
    max_iters: int = 30,
) -> Tuple[TerraformModule, List[TerraformModule], List[str]]:
    """Run the tool-calling LLM agent and return ``(root, modules, log)``.

    Raises on hard failure so the pipeline can decide whether to fall back.
    Collects every ``write_file`` call into an in-memory dict, then partitions
    paths into root / modules/<name>/.
    """
    log: List[str] = []

    pc = ctx.policy_constraints or {}
    field_ops  = pc.get("field_operations") or []
    deny_rules = pc.get("manual_review")    or []
    modify_annotated, deny_annotated = _annotate_policies_with_guidance(field_ops, deny_rules)

    # Top-level general guidance entries — apply to every policy / every plan.
    try:
        from . import policy_guidance as guidance_svc
        general_entries = guidance_svc.general_entry_texts()
    except Exception:
        general_entries = []

    payload = {
        "aws_architecture":  _trim_arch(ctx.architecture or {}),
        "azure_mappings":    _trim_mappings(ctx.mappings or []),
        "azure_region":      ctx.target_region,
        "migration_goals":   ctx.goals or "",
        "strategy_summary":  (strategy.summary if strategy else "") or "",
        "strategy_waves":    [{"order": w.order, "name": w.name, "description": w.description}
                              for w in (strategy.waves if strategy else [])],
        # Each policy carries a ``guidance: [text, ...]`` field (when entries
        # exist in the policy_guidance store) — these are the user-curated /
        # AI-drafted code-generation hints they reviewed before plan run.
        "policy_modify":     modify_annotated,
        "policy_deny":       deny_annotated,
        # General (non-policy-specific) guidance — injected as cross-cutting
        # rules in every codegen.  Examples: "모든 리소스에 tags = var.tags".
        "general_guidance":  general_entries,
        "required_tags":     pc.get("required_tags") or [],
        "tag_defaults":      pc.get("tag_defaults") or {},
        "allowed_locations": pc.get("allowed_locations") or [],
    }
    user_prompt = (
        "다음 입력으로 azurerm terraform 코드를 작성하세요.  ``write_file`` 도구를 "
        "사용해서 파일 단위로 한 번씩 호출하세요.  모든 파일 작성이 끝나면 짧은 "
        "한국어 요약 메시지로 마무리.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)}\n```"
    )

    client = _build_client(llm_deployment, azure_openai_endpoint)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": user_prompt},
    ]

    written: Dict[str, str] = {}    # path → content (last-write-wins)
    final_message = ""

    for it in range(max_iters):
        try:
            completion = client.chat.completions.create(
                model=llm_deployment,
                messages=messages,
                tools=_TOOLS,
                tool_choice="auto",
            )
        except Exception as e:
            log.append(f"LLM 호출 실패 (iter={it}): {e}")
            raise

        choice = completion.choices[0]
        msg = choice.message
        # Append assistant turn (whether or not tool_calls present)
        messages.append({
            "role":       "assistant",
            "content":    msg.content or "",
            "tool_calls": [
                {
                    "id":       tc.id,
                    "type":     "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (msg.tool_calls or [])
            ] if msg.tool_calls else None,
        })
        # Strip the tool_calls key when None so OpenAI doesn't complain
        if not msg.tool_calls:
            messages[-1].pop("tool_calls", None)

        if not msg.tool_calls:
            final_message = msg.content or ""
            log.append(f"iter={it}: LLM 종료 (도구 호출 없음) — {final_message[:120]}")
            break

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if fn_name == "write_file":
                path    = (args.get("path") or "").strip().lstrip("./")
                content = args.get("content") or ""
                if not path:
                    tool_result = "error: empty path"
                else:
                    written[path] = content
                    tool_result = f"ok: wrote {path} ({len(content)} bytes)"
                log.append(f"iter={it}: write_file({path!r}) — {len(content)} bytes")
            else:
                tool_result = f"unknown tool: {fn_name}"
                log.append(f"iter={it}: ⚠ unknown tool call {fn_name!r}")

            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      tool_result,
            })
    else:
        log.append(f"⚠ max_iters={max_iters} 도달 — 그동안 작성된 파일로 진행")

    if not written:
        log.append(f"⚠ LLM 이 write_file 을 한 번도 호출하지 않음.  final_message={final_message[:200]!r}")
        raise RuntimeError("LLM이 terraform 파일을 한 개도 작성하지 않았습니다.")

    # Partition into root + sub-modules
    root_files: Dict[str, str] = {}
    module_files: Dict[str, Dict[str, str]] = {}
    for path, content in written.items():
        if path.startswith("modules/"):
            parts = path.split("/", 2)
            if len(parts) >= 3:
                module_files.setdefault(parts[1], {})[parts[2]] = content
            else:
                # Malformed — treat as root
                root_files[path] = content
        else:
            root_files[path] = content

    root = TerraformModule(name="root", files=root_files, inputs=[], outputs=[])
    modules: List[TerraformModule] = []
    for name, files in module_files.items():
        modules.append(TerraformModule(name=name, files=files, inputs=[], outputs=[]))

    log.append(
        f"LLM codegen 완료 → root({len(root.files)} files) + {len(modules)} modules — "
        f"{final_message[:120]}"
    )
    return root, modules, log
