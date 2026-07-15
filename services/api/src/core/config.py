import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _find_project_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "alembic.ini").exists() or (parent / ".env").exists():
            return parent
    parents = list(current.parents)
    if len(parents) >= 3:
        return parents[2]
    return current.parent


_PROJECT_ROOT = _find_project_root()


def _dotenv_disabled() -> bool:
    return os.getenv("PYTHON_DOTENV_DISABLED", "").strip().lower() in _TRUE_VALUES


def _resolve_env_candidates(raw_path: str) -> list[Path]:
    path = Path(raw_path)
    if path.is_absolute():
        return [path]
    candidates = [Path.cwd() / path, _PROJECT_ROOT / path]
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False)).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _load_environment() -> None:
    if _dotenv_disabled():
        return

    configured_path = (
        os.getenv("YS_ENV_FILE", "").strip()
        or ".env"
    )
    for candidate in _resolve_env_candidates(configured_path):
        if not candidate.exists():
            continue
        for encoding in ("utf-8", "utf-8-sig", "cp950"):
            try:
                load_dotenv(dotenv_path=candidate, override=False, encoding=encoding)
                return
            except UnicodeDecodeError:
                continue
        logger.warning("Skipping dotenv file with unsupported encoding: %s", candidate)
        return


_load_environment()

def _env(key, default=None):
    """Load an environment value and strip surrounding whitespace."""
    value = os.getenv(key, default)
    if isinstance(value, str):
        value = value.strip()
        if not value and default is not None:
            return default
    return value


APP_HOST = _env('APP_HOST','0.0.0.0')
APP_PORT = int(_env('APP_PORT','8000'))
DATA_DIR = _env('DATA_DIR','/data')
EXTRACT_SPREADSHEET_DIR = _env('EXTRACT_SPREADSHEET_DIR', '')
OFFICIAL_BASE_URL = _env('OFFICIAL_BASE_URL', '')
OFFICIAL_COLLECTION_ROOTS = _env(
    'OFFICIAL_COLLECTION_ROOTS',
    '/collections/custom-collection,/collections/custom-collection-1',
)
OFFICIAL_REQUEST_TIMEOUT = float(_env('OFFICIAL_REQUEST_TIMEOUT', '20'))
OFFICIAL_RATE_LIMIT_PER_MINUTE = int(_env('OFFICIAL_RATE_LIMIT_PER_MINUTE', '30'))
EXTRACT_WORKER_ID = _env('EXTRACT_WORKER_ID', '')
EXTRACT_JOB_POLL_SECONDS = int(_env('EXTRACT_JOB_POLL_SECONDS', '3'))
EXTRACT_JOB_HEARTBEAT_SECONDS = int(_env('EXTRACT_JOB_HEARTBEAT_SECONDS', '15'))
EXTRACT_JOB_LEASE_SECONDS = int(_env('EXTRACT_JOB_LEASE_SECONDS', '120'))
EXTRACT_JOB_MAX_ATTEMPTS = int(_env('EXTRACT_JOB_MAX_ATTEMPTS', '2'))
PG = {'host': _env('POSTGRES_HOST','postgres'),
      'port': int(_env('POSTGRES_PORT','5432')),
      'db': _env('POSTGRES_DB','ys_uat'),
      'user': _env('POSTGRES_USER','ys_uat'),
      'pw': _env('POSTGRES_PASSWORD','')}
PGVECTOR_DIM = int(_env('PGVECTOR_DIM','384'))
ADMIN_EMAIL = _env('ADMIN_EMAIL','admin@ys.local')
ADMIN_PASSWORD = _env('ADMIN_PASSWORD','')

CERP_BASE_URL = _env('CERP_BASE_URL','https://cerp.winton.com.tw')
CERP_DEFAULT_CUST_ID = _env('CERP_DEFAULT_CUST_ID')
CERP_DEFAULT_SUPPLIER = _env('CERP_DEFAULT_SUPPLIER')
CERP_DEFAULT_COMP_ID = _env('CERP_DEFAULT_COMP_ID')
CERP_API_KEY_ID = _env('CERP_API_KEY_ID', '')
CERP_DEFAULT_API_KEY_ID = CERP_API_KEY_ID
CERP_TOKEN_TTL_SECONDS = int(_env('CERP_TOKEN_TTL_SECONDS','604800'))
CERP_TOKEN_REFRESH_BUFFER_SECONDS = int(_env('CERP_TOKEN_REFRESH_BUFFER_SECONDS','300'))
YS_CERP_MODE = str(_env('YS_CERP_MODE', 'fake') or 'fake').strip().lower()
YS_FAKE_CERP_DEFAULT_XLSX = _env('YS_FAKE_CERP_DEFAULT_XLSX', 'cerp/pk_20260414產品資訊.xlsx')
UPLOAD_STORAGE_PATH = _env('UPLOAD_STORAGE_PATH','py/S3')
FRONTEND_PUBLIC_BASE_URL = _env('FRONTEND_PUBLIC_BASE_URL', '')
EMAIL_ENABLED = _env('EMAIL_ENABLED', 'false').lower() in _TRUE_VALUES
EMAIL_PROVIDER = _env('EMAIL_PROVIDER', 'smtp')
EMAIL_DELIVERY_MODE = _env('EMAIL_DELIVERY_MODE', 'smtp')
EMAIL_FROM = _env('EMAIL_FROM', '')
EMAIL_FROM_NAME = _env('EMAIL_FROM_NAME', 'YS')
EMAIL_REPLY_TO = _env('EMAIL_REPLY_TO', '')
SMTP_HOST = _env('SMTP_HOST', '')
SMTP_PORT = int(_env('SMTP_PORT', '587'))
SMTP_USERNAME = _env('SMTP_USERNAME', '')
SMTP_PASSWORD = _env('SMTP_PASSWORD', '')
SMTP_USE_TLS = _env('SMTP_USE_TLS', 'true').lower() in _TRUE_VALUES
SMTP_USE_SSL = _env('SMTP_USE_SSL', 'false').lower() in _TRUE_VALUES
SMTP_TIMEOUT_SECONDS = float(_env('SMTP_TIMEOUT_SECONDS', '15'))
EMAIL_MOCK_OUTPUT_DIR = _env('EMAIL_MOCK_OUTPUT_DIR', f'{DATA_DIR}/mock-emails')
PASSWORD_ACTION_FRONTEND_BASE_URL = _env(
    'PASSWORD_ACTION_FRONTEND_BASE_URL',
    FRONTEND_PUBLIC_BASE_URL or 'http://localhost:5263',
)
