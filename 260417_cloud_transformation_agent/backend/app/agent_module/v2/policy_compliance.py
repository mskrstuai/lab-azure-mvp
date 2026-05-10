"""Policy compliance pass — patch generated terraform to obey modify/append policies.

Inserted between deterministic generators and `terraform validate`.

Workflow:
    1. write current modules to a temp work dir
    2. ``terraform init -backend=false`` (locks the actual azurerm provider version)
    3. ``terraform providers schema -json`` (extracts every attribute the locked
       provider supports — the *ground truth* for ARM ↔ TF attribute mapping)
    4. send [generated tf files + filtered schema + policy operations] to the LLM
    5. LLM returns patched files; apply to module/root in place
    6. validator runs after this with the patched code

The LLM is instructed to use the schema as the *only* source for attribute
names — never invent fields.  ``terraform validate`` after this catches any
remaining hallucinations as a safety net.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .schema import TerraformModule
from .strategy import _build_client
from .validator import write_modules_to_disk

logger = logging.getLogger(__name__)


class PatchedFile(BaseModel):
    filename: str = Field(description="Full path relative to the work dir, e.g. 'main.tf' or 'modules/storage/main.tf'.")
    content:  str = Field(description="Full new content of the file (replaces previous entirely).")
    change_summary: str = Field(description="Korean one-line description of what changed.")


class PolicyPatchOutput(BaseModel):
    patches:     List[PatchedFile] = Field(default_factory=list)
    explanation: str = Field(default="", description="Korean summary of overall changes (or why nothing was patched).")


_SYSTEM_PROMPT = """\
당신은 Azure Policy 의 modify/append 효과를 Terraform HCL 코드에 정확히
반영하는 에이전트입니다.

입력:
  • 결정론적으로 생성된 terraform 코드 (root + modules/<name>/, providers.tf 포함)
  • 사용된 azurerm provider 의 실제 schema:
      - resources       : 리소스별 attribute 정의 (필드명 ground truth)
      - provider_block  : provider "azurerm" 블록의 attribute 정의
  • Azure Policy 의 modify / append 효과 operations 목록

작업:
  각 정책 operation 에 대해 — Azure ARM property path 를 azurerm provider 의
  올바른 terraform attribute 로 매핑하고 (schema 가 ground truth), 해당 리소스
  블록에 attribute 를 추가/수정한 patches 를 반환합니다.

원칙:
  1. **Schema 만이 진실** — 응답으로 받은 resources[*].attributes 와
     provider_block 의 키만이 유효한 attribute 이름입니다.  ARM 이름과 종종 다릅니다:
       allowSharedKeyAccess        → shared_access_key_enabled
       supportsHttpsTrafficOnly    → https_traffic_only_enabled
       allowBlobPublicAccess       → allow_nested_items_to_be_public
       minimumTlsVersion           → min_tls_version (값 형식: "TLS1_2")
       publicNetworkAccess         → public_network_access_enabled (boolean)
       disableLocalAuth            → local_auth_enabled (값 반전: 보통 false ↔ true)
     schema 에 없는 이름은 절대 만들지 말 것 — 그런 경우 explanation 에 사유 적고
     해당 operation 은 skip.

  2. **Type 매칭** — 정책 azure_type (Microsoft.Storage/storageAccounts) 이
     가리키는 azurerm 리소스 (azurerm_storage_account) 만 패치.  동일 파일 내
     다른 type 은 건드리지 않음.  여러 인스턴스가 있으면 모두 패치.

  3. **Cascading 의미를 함께 반영** — 일부 정책 변경은 *provider 블록* 또는
     *연관 데이터플레인 리소스* 에도 영향을 줍니다.  반드시 함께 패치:

     ✓ allowSharedKeyAccess = false (storage account):
       → providers.tf 의 provider "azurerm" 블록에 `storage_use_azuread = true` 추가
         (없으면 terraform 이 storage data plane 작업 시 shared key 사용 시도하다 실패)
       → azurerm_storage_container 등 data-plane 리소스가 있으면, 그 리소스의
         storage_account_name 대신 storage_account_id 사용 권장 (provider v4+).
       → README.md 가 root 에 있으면 "사용자/SP 에 'Storage Blob Data Contributor'
         RBAC 필요" 한 줄 추가.

     ✓ allowBlobPublicAccess = false (storage account):
       → azurerm_storage_container 의 container_access_type = "private" 강제
         (public/blob/container 값이면 patch 로 private 으로 교체).

     ✓ disableLocalAuth = true (Cosmos / EventHub / ServiceBus):
       → terraform 의 대응 attribute 로 local_auth_enabled = false (값 반전).
       → 해당 namespace/account 의 데이터플레인 접근에는 Azure AD 인증 필요 —
         README 한 줄 안내.

     ✓ publicNetworkAccess = "Disabled" (ML Workspaces 등):
       → public_network_access_enabled = false.
       → private endpoint 가 코드에 없으면 caveat 추가.

     ✓ identity.type = SystemAssigned 강제:
       → 해당 리소스 블록에 identity { type = "SystemAssigned" } 추가.
         이미 user-assigned 가 있으면 type = "SystemAssigned, UserAssigned".

  4. **이미 일치하면 변경 없음** — 정책 강제 값과 현재 값이 같으면 그 파일은 patches 제외.

  5. **블록 구조 유지** — 인덴트, 정렬, 줄바꿈 위치 그대로.  attribute 추가는
     비슷한 스타일로 새 줄로.

  6. **변경된 파일만 full content** 로 patches 에 포함.  변경 없으면 제외.

  7. change_summary 와 explanation 은 한국어 한 줄.

출력:
  PolicyPatchOutput 스키마 — 마크다운 / 코드 펜스 없음, 순수 JSON.
"""


_RESOURCE_RE = re.compile(r'resource\s+"(azurerm_[a-z0-9_]+)"\s+"', re.MULTILINE)


def _collect_used_resource_types(modules: List[TerraformModule], root: TerraformModule) -> List[str]:
    """Scan all .tf files for `resource "azurerm_xxx" "yyy"` declarations."""
    types = set()
    for m in [root] + list(modules or []):
        for content in (m.files or {}).values():
            if not isinstance(content, str):
                continue
            for match in _RESOURCE_RE.finditer(content):
                types.add(match.group(1))
    return sorted(types)


def _flatten_to_files(root: TerraformModule, modules: List[TerraformModule]) -> Dict[str, str]:
    """Build {filename → content} matching disk layout (modules/<name>/<file>)."""
    out: Dict[str, str] = {}
    for fn, ct in (root.files or {}).items():
        out[fn] = ct
    for m in modules or []:
        if m.name == "root":
            continue
        for fn, ct in (m.files or {}).items():
            out[f"modules/{m.name}/{fn}"] = ct
    return out


def _filter_schema(full_schema: Dict[str, Any], used_types: List[str]) -> Dict[str, Any]:
    """Keep just the slim attribute info for:
      • the resource_schemas blocks for resources we actually use
      • the provider's own configuration block (so the LLM can patch
        provider-level settings like ``storage_use_azuread`` that some
        policy implications require)
    """
    out: Dict[str, Any] = {}
    for provider, body in (full_schema.get("provider_schemas") or {}).items():
        rs = body.get("resource_schemas") or {}
        kept = {name: block for name, block in rs.items() if name in used_types}
        provider_block = body.get("provider") or {}

        slim_resources: Dict[str, Any] = {}
        for rname, rblock in kept.items():
            block = rblock.get("block") or {}
            attrs = block.get("attributes") or {}
            slim_attrs = {
                aname: {
                    "type": adef.get("type"),
                    "description": (adef.get("description") or "")[:200],
                    "computed": adef.get("computed"),
                    "optional": adef.get("optional"),
                    "required": adef.get("required"),
                }
                for aname, adef in attrs.items()
            }
            slim_resources[rname] = {
                "attributes":    slim_attrs,
                "nested_blocks": list((block.get("block_types") or {}).keys()),
            }

        slim_provider: Dict[str, Any] = {}
        pblock = provider_block.get("block") or {}
        for aname, adef in (pblock.get("attributes") or {}).items():
            slim_provider[aname] = {
                "type":        adef.get("type"),
                "description": (adef.get("description") or "")[:200],
                "optional":    adef.get("optional"),
            }

        if slim_resources or slim_provider:
            out[provider] = {
                "resources":          slim_resources,
                "provider_block":     slim_provider,
                "provider_block_blocks": list((pblock.get("block_types") or {}).keys()),
            }
    return out


def _apply_patches_to_modules(
    patches: List[PatchedFile],
    root: TerraformModule,
    modules: List[TerraformModule],
) -> int:
    """Write each patch back into the corresponding module.files dict."""
    n = 0
    for p in patches:
        rel = p.filename.lstrip("./")
        # modules/<name>/<rest>
        if rel.startswith("modules/"):
            parts = rel.split("/", 2)
            if len(parts) < 3:
                logger.warning("policy_compliance: malformed module path %r", p.filename)
                continue
            mod_name, sub_path = parts[1], parts[2]
            for m in modules:
                if m.name == mod_name:
                    m.files = dict(m.files or {})
                    m.files[sub_path] = p.content
                    n += 1
                    break
        else:
            root.files = dict(root.files or {})
            root.files[rel] = p.content
            n += 1
    return n


def apply_policy_compliance(
    *,
    root_module: TerraformModule,
    modules: List[TerraformModule],
    field_operations: List[Dict[str, Any]],
    llm_deployment: str,
    azure_openai_endpoint: str,
) -> Tuple[Optional[PolicyPatchOutput], List[str]]:
    """Run the LLM pass to bake policy modify/append operations into the code.

    Returns ``(output_or_None, log_lines)``.  Returns None+log on any
    early-exit (no terraform binary, no relevant ops, init/schema failure)
    so the caller can decide whether to log+continue.
    """
    log: List[str] = []
    if not field_operations:
        return None, ["적용할 modify/append 정책 없음"]

    if shutil.which("terraform") is None:
        return None, ["terraform 바이너리 없음 — schema 기반 patch 생략"]

    used_types = _collect_used_resource_types(modules, root_module)
    if not used_types:
        return None, ["azurerm_* 리소스가 코드에 없음 — patch 불필요"]

    # ── 1+2. Write to temp dir + init + schema ────────────────
    import tempfile
    with tempfile.TemporaryDirectory(prefix="tf-policy-") as td:
        work = Path(td)
        try:
            write_modules_to_disk(work, root_module, modules)
        except Exception as e:
            return None, [f"파일 쓰기 실패: {e}"]

        init_proc = subprocess.run(
            ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
            cwd=str(work), capture_output=True, text=True, timeout=300, check=False,
        )
        if init_proc.returncode != 0:
            log.append(f"terraform init 실패 (rc={init_proc.returncode}) — schema 추출 못함, patch 생략")
            log.append(((init_proc.stderr or init_proc.stdout) or "")[-400:])
            return None, log

        schema_proc = subprocess.run(
            ["terraform", "providers", "schema", "-json"],
            cwd=str(work), capture_output=True, text=True, timeout=120, check=False,
        )
        if schema_proc.returncode != 0 or not schema_proc.stdout:
            return None, [f"providers schema 추출 실패 (rc={schema_proc.returncode})"]

        try:
            full_schema = json.loads(schema_proc.stdout)
        except json.JSONDecodeError as e:
            return None, [f"schema JSON 파싱 실패: {e}"]

    # ── 3. Filter schema to relevant resources only ──────────
    relevant_schema = _filter_schema(full_schema, used_types)
    if not relevant_schema:
        return None, [f"schema 에서 사용 리소스 ({used_types[:5]}…) 못 찾음 — provider 미스매치?"]

    files_map = _flatten_to_files(root_module, modules)

    # Cap relevant schema serialization to keep the prompt sane.  Slim form
    # is usually 10–60KB across 5–10 resources.  If it ever blows up,
    # truncate per-resource attribute lists rather than dropping resources.
    schema_blob = json.dumps(relevant_schema, ensure_ascii=False, default=str)
    if len(schema_blob) > 90000:
        log.append(f"schema 너무 큼 ({len(schema_blob):,} chars) — 핵심 attribute 만 유지")
        # Drop description fields to shrink
        for prov in relevant_schema.values():
            for r in prov.values():
                for a in r.get("attributes", {}).values():
                    a.pop("description", None)
        schema_blob = json.dumps(relevant_schema, ensure_ascii=False, default=str)

    user_prompt = (
        f"## 사용된 azurerm 리소스 type ({len(used_types)}개)\n"
        f"{json.dumps(used_types, ensure_ascii=False)}\n\n"
        f"## azurerm provider resource_schemas (관련 type 만, ground truth)\n"
        f"```json\n{schema_blob}\n```\n\n"
        f"## 적용할 정책 modify/append operations ({len(field_operations)}건)\n"
        f"```json\n{json.dumps(field_operations, ensure_ascii=False, default=str)}\n```\n\n"
        f"## 현재 terraform 파일들 ({len(files_map)}개)\n"
        f"```json\n{json.dumps(files_map, ensure_ascii=False)}\n```\n\n"
        f"위 schema 를 ground truth 로 ARM field → terraform attribute 매핑을 결정하고, "
        f"필요한 파일만 patches 에 full content 로 반환하세요."
    )

    # ── 4. LLM call ─────────────────────────────────────────
    client = _build_client(llm_deployment, azure_openai_endpoint)
    try:
        completion = client.beta.chat.completions.parse(
            model=llm_deployment,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            response_format=PolicyPatchOutput,
        )
    except Exception as e:
        log.append(f"Policy compliance LLM 호출 실패: {e}")
        return None, log

    msg = completion.choices[0].message
    if getattr(msg, "refusal", None):
        log.append(f"LLM 거부: {msg.refusal}")
        return None, log
    out = msg.parsed
    if out is None:
        log.append("LLM 응답 파싱 실패")
        return None, log

    log.append(
        f"used_types={len(used_types)} ops={len(field_operations)} → "
        f"patches={len(out.patches)} ({out.explanation[:120]})"
    )
    for p in out.patches:
        log.append(f"  · {p.filename}: {p.change_summary}")
    return out, log
