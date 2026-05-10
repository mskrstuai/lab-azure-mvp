"""Phase 2: Plan — data-migration script generation.

Runs after the AI migration planner completes. Detects stateful resources
(RDS, S3, ElastiCache) in the selected scope and generates the appropriate
data-migration commands (pg_dump, AzCopy, redis RDB, ...).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/plan", tags=["plan"])


@router.post("/data-migration-scripts")
def generate_data_migration_scripts(body: dict):
    """Generate data-migration commands for Yellow resources.

    Body:
        {
          "resources": [...],      // same as assess
          "azure_region": "koreacentral",
          "azure_storage_account": "mystorageaccount"   // optional, for S3→Blob
        }
    """
    from app.services.assessment import assess_all, assess_resource

    resources = body.get("resources") or []
    azure_region = body.get("azure_region") or "koreacentral"
    azure_storage = body.get("azure_storage_account") or "<storage-account>"

    scripts = []
    for r in resources:
        assessment = assess_resource(r)
        if assessment["category"] != "yellow":
            continue

        rtype = r.get("_type", "")
        name  = r.get("name") or r.get("id") or ""

        if rtype == "s3":
            scripts.append({
                "resource": f"S3 {name}",
                "type": "azcopy",
                "title": f"S3 버킷 → Azure Blob 동기화",
                "steps": [
                    {
                        "label": "1. AzCopy 설치 확인",
                        "command": "azcopy --version",
                    },
                    {
                        "label": "2. S3 → Azure Blob 동기화",
                        "command": f"azcopy sync 's3://{name}' 'https://{azure_storage}.blob.core.windows.net/{name}' --recursive",
                    },
                    {
                        "label": "3. 결과 확인",
                        "command": f"azcopy jobs list",
                    },
                ],
                "notes": "SAS 토큰 또는 MSI 인증 필요. 대용량의 경우 야간 실행 권장.",
            })

        elif rtype == "rds":
            engine  = r.get("engine", "postgres")
            host    = r.get("endpoint", "<rds-endpoint>")
            db_name = r.get("id", "<dbname>")

            if "mysql" in engine or "maria" in engine:
                scripts.append({
                    "resource": f"RDS {name} ({engine})",
                    "type": "mysqldump",
                    "title": "RDS MySQL → Azure Database for MySQL",
                    "steps": [
                        {"label": "1. 덤프",    "command": f"mysqldump -h {host} -u <user> -p {db_name} > {db_name}.sql"},
                        {"label": "2. 복원",    "command": f"mysql -h <azure-host> -u <user>@<server> -p {db_name} < {db_name}.sql"},
                        {"label": "3. 검증",    "command": f"mysql -h <azure-host> -u <user>@<server> -p -e 'SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=\"{db_name}\"'"},
                    ],
                    "notes": "유지보수 창 필요. 덤프 중 쓰기 트래픽 차단 권장.",
                })
            else:  # postgres (default)
                scripts.append({
                    "resource": f"RDS {name} ({engine})",
                    "type": "pg_dump",
                    "title": "RDS PostgreSQL → Azure Database for PostgreSQL",
                    "steps": [
                        {"label": "1. 덤프",    "command": f"pg_dump -h {host} -U <user> -Fc {db_name} > {db_name}.pgdump"},
                        {"label": "2. 복원",    "command": f"pg_restore -h <azure-host> -U <user> -d {db_name} {db_name}.pgdump"},
                        {"label": "3. 검증",    "command": f"psql -h <azure-host> -U <user> -c \"\\dt\" {db_name}"},
                    ],
                    "notes": "유지보수 창 필요. --no-privileges 옵션으로 권한 충돌 방지.",
                })

        elif rtype == "elasticache":
            scripts.append({
                "resource": f"ElastiCache {name}",
                "type": "redis_rdb",
                "title": "ElastiCache Redis → Azure Cache for Redis",
                "steps": [
                    {"label": "1. RDB 스냅샷 생성", "command": f"redis-cli -h <elasticache-host> BGSAVE"},
                    {"label": "2. RDB 파일 다운로드", "command": "aws s3 cp s3://<backup-bucket>/dump.rdb ./dump.rdb"},
                    {"label": "3. Azure Redis에 복원", "command": "redis-cli -h <azure-redis-host> -a <access-key> --pipe < dump.rdb"},
                ],
                "notes": "캐시 특성상 데이터 유실 허용 가능 여부를 먼저 확인하세요.",
            })

    return {"scripts": scripts, "count": len(scripts)}
