"""Fix Agent — LLM-assisted Terraform error remediation.

Triggered when ``terraform apply`` fails (Azure Policy denial, quota limit,
SKU unavailable in region, naming conflict, etc.).  Reads the last N lines
of error log plus the current .tf files, asks the LLM to produce a minimal
patch, and returns proposed file edits with diagnosis.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from .strategy import _build_client  # reuse the same Azure OpenAI client setup

logger = logging.getLogger(__name__)


class FileFix(BaseModel):
    filename: str = Field(description="Relative path of the file to modify, e.g. 'main.tf' or 'modules/networking/main.tf'")
    content:  str = Field(description="Full new content of the file (replaces previous entirely)")
    change_summary: str = Field(description="One-line Korean summary of what changed in this file")


class CommandSuggestion(BaseModel):
    cmd: str = Field(
        description=(
            "작업 디렉토리 셸에서 그대로 실행할 한 줄 명령. "
            "terraform / az / shell 코어유틸 어떤 바이너리도 가능, "
            "파이프(|), 리다이렉션(>), &&, $() 등 셸 메타도 OK."
        ),
    )
    purpose: str = Field(description="이 단계가 fix 플랜에서 왜 필요한지 (한국어, 한 줄)")


class FixOutput(BaseModel):
    diagnosis: str = Field(description="2~3문장 한국어 진단 — 무엇이 실패했고 왜 그런지")
    strategy: str = Field(
        default="patch_and_retry",
        description=(
            "이번 진단을 어떤 전제로 작성했는지:\n"
            " • 'patch_and_retry'    — 현재 부분 배포된 state 위에서 fixes/commands 를 "
            "                          적용하면 apply 가 통과한다고 판단한 경우 (대부분의 일반 케이스)\n"
            " • 'destroy_and_apply' — 현재 state 가 너무 꼬여 있거나 정책 거부가 누적된 "
            "                          여러 리소스 때문에 깨끗한 상태에서 다시 시작하는 게 빠르다고 "
            "                          판단한 경우.  이 경우 fixes 는 *destroy 후 깨끗한 상태에서 "
            "                          처음부터 apply 하는 것*을 전제로 작성됨."
        ),
    )
    fixes: List[FileFix] = Field(default_factory=list, description="apply 를 통과시키기 위해 적용할 코드 수정 (없으면 빈 배열)")
    commands: List[CommandSuggestion] = Field(
        default_factory=list,
        description=(
            "fixes 와 함께 apply 를 통과시키기 위해 **순서대로 실행할** 셸 명령 시퀀스. "
            "단순 추천이 아니라 실제 실행 단계 목록 — 첫 명령부터 마지막까지 차례로 "
            "실행하면 fix 가 완성되도록 구성. terraform state import / rm, "
            "az storage account purge, rm -rf .terraform, terraform init -upgrade 등."
        ),
    )
    user_action: str = Field(default="", description="셸로도 못 푸는 외부 작업 (예: 'Azure Portal에서 정책 예외 추가', 'Quota 증액 요청 티켓')")


_PATCH_STRATEGY_BLOCK = """\
**진단 모드 — patch_and_retry (사용자가 선택함):**
  ⚠ 사용자가 *현재 부분 배포된 리소스를 유지한 채* 코드를 패치해서 apply 가
     통과되도록 만들어 달라고 요청했습니다.  destroy 는 절대 가정하지 마세요.

  진단 원칙:
  • fixes/commands 는 **현재 state 위에서 그대로 실행됨** 을 전제로 작성
  • 이미 만들어진 리소스와의 충돌은 *그 리소스를 그대로 두고 회피*하는 방향
    예: 같은 이름이면 새 이름 / suffix 추가 / 구독 이미 가진 SKU 로 교체
  • terraform state 가 가진 리소스는 보존됨 — 새 리소스만 추가/교체로 진행
  • commands 는 state import, az resource show, RP register 같은
    "현재 state 와 외부 리소스 정합성 맞추기" 위주
  • **destroy / state rm / 전체 재생성** 류 명령은 금지 — 사용자가 명시적으로
    유지를 선택했음

  diagnosis 첫 줄에 "[패치 모드] " 접두사 붙이고 그 뒤 이유.
"""

_DESTROY_STRATEGY_BLOCK = """\
**진단 모드 — destroy_and_apply (사용자가 선택함):**
  ⚠ 사용자가 *부분 배포된 리소스를 모두 destroy 한 뒤 깨끗한 상태에서 다시
     apply* 하는 전제로 진단해 달라고 요청했습니다.  현재 state 의 리소스는
     실행 직후 모두 삭제될 예정이라고 가정하세요.

  진단 원칙:
  • fixes 는 **destroy 후 첫 apply** 를 전제로 작성:
    → "이미 X 가 있어서 충돌" 같은 incremental 수정은 무의미 (어차피 destroy 됨)
    → caller(root) 의 변수 default, 모듈의 잘못된 인자, 정책 위반 태그/위치 등
      **새로 만들 때 처음부터 문제가 될 근본 원인** 을 고치세요
  • commands 는 *destroy 가 못 풀어주는 외부 정리* 만:
    → soft-delete 잔여 purge, RP 등록, RBAC 부여, 네임 충돌 정리 등
    → terraform state rm / import 류는 어차피 destroy 되니 불필요
  • caller-side 변수 override 흐름을 특히 신경 쓰세요 — root variables.tf 의
    var.tags / var.location 등 default 가 새 apply 의 기준이 됩니다.

  diagnosis 첫 줄에 "[destroy 모드] " 접두사 붙이고 그 뒤 이유.
"""


_SYSTEM_PROMPT = """\
당신은 **자율적 Terraform 수정 에이전트**입니다.  사용자에게 의존하지 않고
파일을 직접 수정해서 ``terraform apply`` 가 통과하도록 만드는 것이 목표입니다.

__STRATEGY_SECTION__

**기본 원칙 (매우 중요):**

  1. **사용자 액션을 기대하지 마세요.**  당신은 워킹 디렉토리의 모든 파일에
     쓰기 권한이 있으며, 시스템이 당신의 fixes 를 자동 적용하고 다시 apply 합니다.

     ❌ 잘못된 응답: user_action="Standard_DS1_v2 같은 SKU 로 바꿔주세요"
     ✓ 올바른 응답: fixes=[{{filename:"modules/compute/main.tf",
                          content:"... size = \\"Standard_DS1_v2\\" ..."}}]

     ❌ 잘못된 응답: user_action="modules/compute/main.tf 의 전체 내용을 보내주세요"
     ✓ 올바른 응답: 받은 파일 내용으로 fixes 작성 — 파일은 user_prompt 에 포함되어 있음

  2. **자체 판단으로 수정하세요.**  SKU 다운그레이드, 리전 호환 SKU 교체,
     CIDR 충돌 회피 등은 모두 직접 결정해서 fixes 에 반영합니다.
     - SKU not available: 같은 패밀리 동급 SKU 로 교체 (Standard_B2s → Standard_B2as_v2,
       Standard_DS2_v2 → Standard_DS2_v3 등)
     - Quota exceeded: 해당 리소스 수량 줄이기 또는 더 작은 SKU 로 변경
     - CIDR 충돌: 충돌하지 않는 새 CIDR 할당 (10.1.0.0/16 → 10.50.0.0/16)
     - Naming conflict: ${{var.name_suffix}} 또는 ${{random_string.suffix.result}} 추가
     - Policy denial (tag 누락): 필요한 tag 를 적절한 위치(보통 root variables.tf 의
       var.tags default)에 추가

  3. **user_action 은 정말 어쩔 수 없는 경우에만:**
     - Azure 구독 quota 증액 요청 (Azure Support 티켓 필요)
     - Azure AD app / 외부 시스템에서 사전 프로비저닝이 필요한 자격증명
     - Subscription-level policy 가 변경 불가 (조직 정책)
     **이외 모든 코드 수정 가능한 문제는 fixes 로 직접 해결하세요.**

**기술 원칙:**
  1. 한 번에 한 가지 문제만 고치세요.  여러 추측성 수정 X.
  2. 변경하지 않는 파일은 fixes 배열에 포함하지 마세요.
  3. 파일 전체 내용을 새로 작성하세요 (부분 패치 X — fixes[i].content 가 파일 전체).
  4. 같은 SKU 가용성 / Storage 인증 / Policy 등 여러 에러가 동시에 보이면, 에러 로그의
     **첫 번째** 문제만 고치세요.  재시도 후 남은 문제는 다음 사이클에서 진단합니다.
  5. 절대로 "파일 내용을 보내주세요" 같은 요청 X — 모든 파일은 이미 user_prompt 에 있음.

**가장 중요 — 변수 override 흐름 추적:**
값을 변경할 때, 그 값이 **실제로 어디서 결정되는지** 추적하세요.
모듈 내부 default 값을 바꿔도 caller(보통 root main.tf)에서 override 하면 무용지물입니다.

  예시 1 — 잘못된 수정:
    modules/networking/variables.tf 의 default tags 에 Environment 추가
    그러나 root main.tf:
      module "networking" {{
        tags = var.tags        # ← root 의 var.tags 가 우선됨
      }}
    → 실제로는 root variables.tf 의 var.tags default 를 고쳐야 함

  예시 2 — 올바른 수정:
    Storage Account 이름이 짧다는 에러 → modules/storage/main.tf 의 name 필드
    (caller 에서 안 넘어오는 값) → 모듈 안에서 직접 수정 OK

  체크 절차:
  1. 에러가 발생한 정확한 리소스/필드를 확인
  2. 그 필드가 var.X 형태로 모듈에서 받는다면 → caller(root) 추적
  3. caller 에서 실제 값을 어떤 변수로 전달하는지 확인
  4. 그 변수의 default 가 정의된 파일을 수정 (보통 root variables.tf)

**자주 보이는 패턴:**
  • Azure Policy denial (태그 누락):
    → root variables.tf 의 var.tags default 에 필수 태그 추가
    → (모듈의 default 가 아님 — root 가 caller 라서)
  • SKU not available in region:
    → 동급의 다른 SKU 로 교체 (예: Standard_B2s → Standard_B2as_v2)
    → 모듈 안의 하드코드 또는 mapping 결과 변경
  • Quota exceeded:
    → 리소스 수량 줄이거나 user_action 으로 quota 증액 안내
  • Naming conflict:
    → name 필드에 ${{var.name_suffix}} 또는 ${{random_string.suffix.result}} 추가
  • CIDR 충돌:
    → 충돌하지 않는 다른 CIDR 로 교체 (root variables.tf 또는 module main.tf)
  • Resource already exists / 같은 이름 충돌 / state drift:
    → fixes 만으로 안 풀리면 **commands** 로 진단/정리/복구 명령 제안

**commands 필드 — 순서가 있는 실행 플랜:**
  ⚠ commands 는 *추천 모음*이 아니라 **순서대로 실행할 fix 단계 목록**입니다.
     `fixes` (코드 수정) 와 `commands` (셸 명령 시퀀스) 를 합쳐 한 묶음의
     "이번 apply 를 통과시키기 위한 작업 플랜" 이 됩니다.

  실행 모델 (사용자 입장):
     1. UI 가 fixes 를 모두 디스크에 저장
     2. UI 가 commands[0], commands[1], ... 순서대로 셸에서 실행
     3. terraform apply 재실행 — 통과해야 함

  따라서 commands 는:
  • 첫 명령 → 마지막 명령을 차례로 돌리면 의도한 fix 상태가 완성되도록 설계
  • 각 명령은 그 다음 단계의 전제가 되는 결과를 만들 것 (이전 단계 출력 의존 OK)
  • 실패하면 안 되는 명령은 위험성 낮은 것부터 (예: list/show 후 purge)
  • 한 번 실행으로 끝낼 명령만 (idempotent 거나 purpose 에 "이미 정리됐으면 skip" 명시)
  • placeholder 가 있으면 안 됨 — 에러 로그에서 추론한 **실제 값**을 박아넣을 것
    (RG / storage account name / subscription id 등은 로그·tfvars 에서 추출)

  사용 케이스 (단계 시퀀스로 짜기):
  • **soft-delete 잔여 storage account**:
      1) az storage account list-deleted --location <loc> --query "[?name=='<n>']"
         (잔여 확인)
      2) az storage account purge --name <n> --resource-group <rg> --location <loc> --yes
         (영구 삭제)
      → 그 다음 apply 가 새로 생성 가능
  • **외부에 이미 만들어진 리소스 import**:
      1) terraform state list  (이미 import 된 건 아닌지 확인 가능)
      2) terraform import 'module.storage.azurerm_storage_account.this' \
         /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<n>
      → 그 다음 apply 가 update 모드로 진행
  • **state 에 남은 stale 리소스 제거**:
      1) terraform state rm 'module.compute.azurerm_linux_virtual_machine.web[0]'
      → 그 다음 apply 가 재생성
  • **provider 캐시 문제 / lock 파일 꼬임**:
      1) rm -rf .terraform .terraform.lock.hcl
      2) terraform init -upgrade
  • **RP 미등록**:
      1) az provider register --namespace Microsoft.Storage --wait
  • **권한 부여 누락**:
      1) az role assignment create --assignee <objId> --role Contributor --scope <scope>

  **fixes 와의 분담:**
  • HCL 코드로 표현 가능한 변경 → fixes 로 (SKU 교체, name suffix 추가, tags 추가 등)
  • state / 외부 리소스 / 캐시 / 권한 / 등록 → commands 로
  • 둘 다 필요한 케이스 (대부분의 실제 시나리오) → fixes + commands 모두 채울 것

  형식 규칙:
  • cmd: 한 줄, 그대로 셸 실행 가능 (파이프/리다이렉션 OK)
  • purpose: 이 단계가 *fix 시퀀스 안에서* 왜 필요한지 (단계 의도)
  • placeholder `<...>` 금지 — 에러 로그/tfvars 로 실제 값 추론해서 박아넣기
  • 셸로도 못 푸는 것 (Azure Portal 클릭, quota 증액 티켓 발급) 만 user_action

**출력:**
  FixOutput 스키마에 맞는 JSON.  마크다운 / 코드 펜스 없음.
  diagnosis / change_summary / user_action / commands.purpose 모두 **한국어**.
  commands.cmd 는 실행 가능한 영어 CLI 그대로.
  파일 내용은 그대로 HCL.

  diagnosis 에는 반드시 다음을 포함:
  • 에러가 발생한 정확한 리소스 (예: "modules/compute 의 azurerm_linux_virtual_machine.web_1")
  • 값이 결정되는 위치 (예: "root variables.tf 의 var.tags default")
  • 왜 그 위치를 수정해야 하는지 (예: "module 호출부에서 var.tags 로 override 되므로")
"""


def _file_priority(filename: str, error_log_lower: str) -> int:
    """Lower number = higher priority (gets included before others when truncating)."""
    name_lower = filename.lower()
    # 0: file path or basename appears in the error log
    parts = name_lower.replace("\\", "/").split("/")
    base = parts[-1]
    if name_lower in error_log_lower or base in error_log_lower:
        return 0
    # 1: any path component appears in the error log (e.g. 'compute', 'storage')
    for part in parts:
        if part and part in error_log_lower:
            return 1
    # 2: root-level files (no '/')
    if "/" not in filename:
        return 2
    # 3: anything else (other module files)
    return 3


VALID_STRATEGIES = {"patch_and_retry", "destroy_and_apply"}


def fix_terraform_error(
    *,
    error_log:  str,
    files:      Dict[str, str],
    llm_deployment: str,
    azure_openai_endpoint: str,
    strategy:   str = "patch_and_retry",
    max_log_chars: int = 8000,
    max_files_chars: int = 200000,   # gpt-5.4 supports ~256k context — send everything
) -> FixOutput:
    """Ask the LLM to diagnose a terraform apply failure and produce a patch.

    The caller picks the ``strategy`` (the user's choice in the UI):
      • patch_and_retry  — keep existing resources, patch incrementally
      • destroy_and_apply — assume destroy first, fixes for clean re-apply

    All .tf files are sent.  Truncation only kicks in for very large workloads
    (>200K chars ≈ >50K tokens of HCL).  When truncation IS needed, files
    referenced by the error log are kept first.
    """
    if strategy not in VALID_STRATEGIES:
        strategy = "patch_and_retry"
    client = _build_client(llm_deployment, azure_openai_endpoint)

    strategy_block = (
        _DESTROY_STRATEGY_BLOCK if strategy == "destroy_and_apply" else _PATCH_STRATEGY_BLOCK
    )
    system_prompt = _SYSTEM_PROMPT.replace("__STRATEGY_SECTION__", strategy_block)

    log_tail = error_log[-max_log_chars:] if len(error_log) > max_log_chars else error_log
    error_lower = log_tail.lower()

    # Sort so error-relevant files come first (less likely to be truncated)
    sorted_files = sorted(files.items(), key=lambda kv: (_file_priority(kv[0], error_lower), kv[0]))

    file_blob_parts: List[str] = []
    used = 0
    truncated_files: List[str] = []
    for fname, content in sorted_files:
        chunk = f"\n--- {fname} ---\n{content}\n"
        if used + len(chunk) > max_files_chars:
            file_blob_parts.append(f"\n--- {fname} ---\n(파일 크기 초과 — 생략됨, {len(content)} chars)\n")
            truncated_files.append(fname)
            used += 50
        else:
            file_blob_parts.append(chunk)
            used += len(chunk)
    files_blob = "".join(file_blob_parts)

    if truncated_files:
        logger.warning(
            "Fix agent: %d/%d files truncated due to size (total chars=%d)",
            len(truncated_files), len(sorted_files), used,
        )

    user_prompt = (
        f"## terraform apply 에러 로그 (최근 출력)\n```\n{log_tail}\n```\n\n"
        f"## 현재 .tf 파일들 ({len(files)}개, 약 {used:,} chars 전송됨)\n"
        f"위 파일 목록은 **워킹 디렉토리의 전체 .tf/.tfvars/.md 파일**입니다. "
        f"개별 파일 내용을 추가로 요청하지 말고, 위 내용만으로 fixes 배열을 만드세요.\n"
        f"{files_blob}\n\n"
        f"위 정보로 다음을 작성하세요 — fixes + commands 가 합쳐서 **이번 apply 를 통과시키는 단일 작업 플랜** 이 되어야 합니다:\n"
        f"  • diagnosis — 무엇이 왜 실패했는지 (한국어 2~3문장)\n"
        f"  • fixes    — HCL 코드 수정으로 해결되는 부분 (전체 파일 내용)\n"
        f"  • commands — fixes 적용 후 **순서대로 실행**할 셸 명령 시퀀스.\n"
        f"               state import / rm, az purge / register, 캐시 정리 등.\n"
        f"               시스템이 이 배열을 첫 인덱스부터 차례로 셸에서 실제 실행합니다.\n"
        f"               placeholder `<...>` 쓰지 말고 에러 로그·tfvars 에서 실제 값을 박아넣으세요.\n"
        f"  • user_action — 셸로도 못 푸는 것 (Azure Portal 클릭, quota 티켓 등) 만\n\n"
        f"**원칙:** fixes 만으로 풀리는 케이스면 commands 는 비워도 OK. 외부 상태(soft-delete, "
        f"기존 리소스, RP 미등록, state drift)가 원인이면 fixes 가 비더라도 commands 로 정리 단계를 작성하세요. "
        f"대부분 실제 케이스는 둘 다 필요합니다.  '파일 내용을 보내주세요' 같은 요청 X."
    )

    try:
        completion = client.beta.chat.completions.parse(
            model=llm_deployment,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            response_format=FixOutput,
        )
        msg = completion.choices[0].message
        if getattr(msg, "refusal", None):
            raise RuntimeError(msg.refusal)
        if msg.parsed is None:
            raise RuntimeError("Fix agent returned no parsed output")
        # Always echo the user-chosen strategy back (override anything the LLM said)
        result = msg.parsed
        result.strategy = strategy
        return result
    except Exception as e:
        logger.exception("Fix agent failed: %s", e)
        return FixOutput(
            diagnosis=f"Fix agent 호출 실패: {e}",
            strategy=strategy,
            fixes=[],
            user_action="자동 수정을 적용할 수 없습니다. 로그를 보고 수동으로 수정하세요.",
        )
