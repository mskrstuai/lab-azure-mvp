"""Phase 2: Resource assessment — Green / Yellow / Red classification.

Rule-based (no LLM) so it is fast and deterministic.

Green  🟢 — Fully automated with Terraform.  No data to migrate.
Yellow 🟡 — Terraform for infra + migration script/guide for data.
Red    🔴 — Guide document only.  Auto-migration not practical.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── Assessment catalogue ──────────────────────────────────────────
#
# Each entry maps a resource _type (or prefix) to:
#   category   : green | yellow | red
#   azure_tf   : primary azurerm_* resource type
#   azure_svc  : human-readable Azure service name
#   approach   : one-line migration method
#   data_note  : (optional) data-migration note shown in Yellow/Red items

_RULES: List[Dict[str, str]] = [
    # ── Networking ── (always Green — pure config, no data)
    {"match": "ec2/vpc",              "category": "green",  "azure_tf": "azurerm_virtual_network",            "azure_svc": "Virtual Network",              "approach": "Terraform 자동 생성"},
    {"match": "ec2/subnet",           "category": "green",  "azure_tf": "azurerm_subnet",                     "azure_svc": "Subnet",                       "approach": "Terraform 자동 생성"},
    {"match": "ec2/security-group",   "category": "green",  "azure_tf": "azurerm_network_security_group",     "azure_svc": "NSG",                          "approach": "Inbound/Outbound 규칙 변환"},
    {"match": "ec2/internet-gateway", "category": "green",  "azure_tf": "(VNet에 포함)",                      "azure_svc": "Virtual Network",              "approach": "Terraform 자동 처리"},
    {"match": "ec2/nat-gateway",      "category": "green",  "azure_tf": "azurerm_nat_gateway",                "azure_svc": "NAT Gateway",                  "approach": "Terraform 자동 생성"},
    {"match": "ec2/route-table",      "category": "green",  "azure_tf": "azurerm_route_table",                "azure_svc": "Route Table",                  "approach": "Terraform 자동 생성"},

    # ── Compute ──
    {"match": "ec2",                  "category": "green",  "azure_tf": "azurerm_linux_virtual_machine",      "azure_svc": "Virtual Machine",              "approach": "Terraform 자동 생성 (AMI → 동급 이미지 선택)"},
    {"match": "autoscaling",          "category": "green",  "azure_tf": "azurerm_linux_virtual_machine_scale_set", "azure_svc": "VMSS",                 "approach": "Terraform 자동 생성"},
    {"match": "ecs",                  "category": "yellow", "azure_tf": "azurerm_container_app",              "azure_svc": "Container App",                "approach": "Terraform + 컨테이너 이미지 이전",      "data_note": "ECR → Azure Container Registry 이미지 push 필요"},
    {"match": "eks/cluster",          "category": "red",    "azure_tf": "azurerm_kubernetes_cluster",         "azure_svc": "AKS",                          "approach": "가이드 문서 생성",                      "data_note": "AWS-specific 어노테이션(ALB Ingress, ExternalDNS 등) 수정 필요"},
    {"match": "lambda",               "category": "yellow", "azure_tf": "azurerm_linux_function_app",         "azure_svc": "Function App",                 "approach": "Terraform + 코드 리뷰",                 "data_note": "AWS SDK → Azure SDK 교체, 트리거 방식 변경 확인"},

    # ── Database ── (Yellow: infra auto + data migration script)
    {"match": "rds",                  "category": "yellow", "azure_tf": "azurerm_postgresql_flexible_server", "azure_svc": "Azure Database for PostgreSQL","approach": "Terraform + pg_dump / pg_restore",       "data_note": "유지보수 창 필요. 스크립트 자동 생성."},
    {"match": "dynamodb",             "category": "red",    "azure_tf": "azurerm_cosmosdb_account",           "azure_svc": "Cosmos DB",                    "approach": "가이드 문서 생성",                      "data_note": "스키마 재설계 필요. DynamoDB → Cosmos DB 마이그레이션 가이드 제공."},

    # ── Storage ──
    {"match": "s3",                   "category": "yellow", "azure_tf": "azurerm_storage_account",            "azure_svc": "Blob Storage",                 "approach": "Terraform + AzCopy sync",               "data_note": "azcopy sync 명령어 자동 생성"},
    {"match": "efs",                  "category": "yellow", "azure_tf": "azurerm_storage_share",              "azure_svc": "Azure Files",                  "approach": "Terraform + rsync/AzCopy",              "data_note": "파일 동기화 스크립트 생성"},

    # ── Cache ──
    {"match": "elasticache",          "category": "yellow", "azure_tf": "azurerm_redis_cache",                "azure_svc": "Azure Cache for Redis",        "approach": "Terraform + RDB 스냅샷 이전",           "data_note": "Redis BGSAVE → RDB 파일 → Azure Redis restore"},

    # ── Load Balancer ──
    {"match": "elasticloadbalancing", "category": "green",  "azure_tf": "azurerm_application_gateway",        "azure_svc": "Application Gateway",          "approach": "Terraform 자동 생성 (리스너/규칙 변환)"},
    {"match": "elb",                  "category": "green",  "azure_tf": "azurerm_application_gateway",        "azure_svc": "Application Gateway",          "approach": "Terraform 자동 생성"},

    # ── Messaging ──
    {"match": "sqs",                  "category": "yellow", "azure_tf": "azurerm_servicebus_queue",           "azure_svc": "Service Bus Queue",            "approach": "Terraform + SDK 교체 가이드",           "data_note": "메시지 유실 주의: 마이그레이션 전 큐 비우기 권장"},
    {"match": "sns",                  "category": "yellow", "azure_tf": "azurerm_eventgrid_topic",            "azure_svc": "Event Grid",                   "approach": "Terraform + 구독 설정 변환",            "data_note": "구독자 엔드포인트 업데이트 필요"},
    {"match": "kinesis",              "category": "yellow", "azure_tf": "azurerm_eventhub_namespace",         "azure_svc": "Event Hub",                    "approach": "Terraform + 프로듀서/컨슈머 코드 변경",  "data_note": "AWS Kinesis SDK → Azure Event Hub SDK 교체"},

    # ── Security / Config ──
    {"match": "secretsmanager",       "category": "yellow", "azure_tf": "azurerm_key_vault_secret",           "azure_svc": "Key Vault",                    "approach": "Terraform + 시크릿 이전 스크립트",      "data_note": "시크릿 값 수동 또는 스크립트로 Key Vault에 복사"},
    {"match": "kms",                  "category": "yellow", "azure_tf": "azurerm_key_vault_key",              "azure_svc": "Key Vault",                    "approach": "Terraform + 키 정책 변환",              "data_note": "암호화된 리소스의 키 참조 업데이트 필요"},
    {"match": "iam",                  "category": "green",  "azure_tf": "azurerm_role_assignment",            "azure_svc": "Azure RBAC",                   "approach": "Terraform (IAM 역할 → Azure RBAC 매핑)"},

    # ── DNS / CDN ──
    {"match": "route53",              "category": "yellow", "azure_tf": "azurerm_dns_zone",                   "azure_svc": "Azure DNS",                    "approach": "Terraform + DNS 레코드 이전",           "data_note": "TTL 낮추기 → DNS 전환 → TTL 복원 순서 권장"},
    {"match": "cloudfront",           "category": "green",  "azure_tf": "azurerm_cdn_frontdoor_profile",      "azure_svc": "Azure Front Door",             "approach": "Terraform 자동 생성"},
]


def _match_type(resource_type: str, pattern: str) -> bool:
    """Check if resource_type starts with pattern (case-insensitive)."""
    return resource_type.lower().startswith(pattern.lower())


def _find_rule(resource_type: str) -> Optional[Dict[str, str]]:
    """Return the best matching rule for a given _type."""
    best: Optional[Dict[str, str]] = None
    best_len = 0
    for rule in _RULES:
        pat = rule["match"]
        if _match_type(resource_type, pat) and len(pat) > best_len:
            best = rule
            best_len = len(pat)
    return best


def assess_resource(resource: Dict[str, Any]) -> Dict[str, Any]:
    """Return assessment dict for a single resource."""
    rtype = resource.get("_type") or ""
    rule  = _find_rule(rtype)

    # Extra logic for RDS: engine-specific target
    if rtype == "rds":
        engine = (resource.get("engine") or "").lower()
        if "mysql" in engine or "maria" in engine:
            rule = {**rule, "azure_tf": "azurerm_mysql_flexible_server", "azure_svc": "Azure Database for MySQL"}
        elif "sqlserver" in engine or "mssql" in engine:
            rule = {**rule, "azure_tf": "azurerm_mssql_database", "azure_svc": "Azure SQL Database"}
        elif "aurora" in engine:
            rule = {**rule, "category": "red", "approach": "가이드 문서 생성",
                    "data_note": "Aurora 전용 기능(Global DB, Serverless) → Azure 대안 검토 필요"}

    # Lambda: deprecated runtime → Red
    if rtype == "lambda":
        deprecated = {"nodejs12.x", "nodejs10.x", "python2.7", "python3.6", "ruby2.5", "java8"}
        runtime = resource.get("runtime") or ""
        if runtime in deprecated:
            rule = {**rule, "category": "red",
                    "data_note": f"런타임 {runtime}은 지원 종료됨. 코드 업그레이드 후 마이그레이션 필요."}

    if rule is None:
        # Unknown type — default to Yellow with generic note
        rule = {
            "category": "yellow",
            "azure_tf": "(검토 필요)",
            "azure_svc": "미확인 서비스",
            "approach": "수동 검토 필요",
            "data_note": f"리소스 타입 '{rtype}'에 대한 자동 매핑 없음",
        }

    return {
        "resource_type": rtype,
        "resource_id":   resource.get("id") or resource.get("name") or "",
        "resource_name": resource.get("name") or resource.get("id") or "",
        "arn":           resource.get("arn") or "",
        "category":      rule["category"],
        "azure_tf":      rule.get("azure_tf", ""),
        "azure_svc":     rule.get("azure_svc", ""),
        "approach":      rule.get("approach", ""),
        "data_note":     rule.get("data_note", ""),
    }


def assess_all(resources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assess a list of resources and return a grouped summary."""
    items = [assess_resource(r) for r in resources]

    green  = [i for i in items if i["category"] == "green"]
    yellow = [i for i in items if i["category"] == "yellow"]
    red    = [i for i in items if i["category"] == "red"]

    return {
        "items":  items,
        "summary": {
            "green":  len(green),
            "yellow": len(yellow),
            "red":    len(red),
            "total":  len(items),
        },
        "green":  green,
        "yellow": yellow,
        "red":    red,
    }
