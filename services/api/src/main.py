import os
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
import asyncpg

from .api import (
    routes_admin,
    routes_auth,
    routes_cerp,
    routes_chat,
    routes_console,
    routes_core,
    routes_projects,
    routes_customers,
    routes_edm,
    routes_quotes,
    routes_feedback,
    routes_extract,
    routes_file_resources,
    routes_search,
    routes_label,
    routes_label_print,
    routes_knowledge,
    routes_upload,
)
from .core.models import Base, User, Role, Permission
from .models.customer import Customer  # noqa: F401
from .models.feedback import SearchFeedback  # noqa: F401
from .models.label_description import LabelDescription  # noqa: F401
from .models.label_print_item import LabelPrintItem  # noqa: F401
from .models.extract_job import ExtractJob  # noqa: F401
from .models.file_resource import FileResource  # noqa: F401
from .models.fake_cerp_product import FakeCerpProduct  # noqa: F401
from .models.official_product_profile import OfficialProductProfile  # noqa: F401
from .models.producer_source_domain import ProducerSourceDomain  # noqa: F401
from .models.project import Project, ProjectInvitation, ConversationInvitation  # noqa: F401
from .models.rap_record import RapRecord  # noqa: F401
from .core.database import engine as async_engine, SessionLocal
from .core.security import get_password_hash, verify_password
from .core.config import _env
from .core.module_registry import is_module_enabled
from .cerpModule import is_fake_cerp_mode
from .services.fake_cerp_import_service import FakeCerpImportService

LOG_LEVEL = os.getenv("LOG_LEVEL", _env("LOG_LEVEL", "INFO")).upper()
numeric_log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=numeric_log_level, format="%(levelname)s:%(name)s:%(message)s")
for ulogger in ("uvicorn", "uvicorn.error", "uvicorn.access"):
    logging.getLogger(ulogger).setLevel(numeric_log_level)

ROUTERS = [
    (routes_core.router, "", ["Core"], "core.admin"),
    (routes_projects.router, "", ["Projects"], "core.projects"),
    (routes_chat.router, "", ["Chat"], "core.chat"),
    (routes_extract.router, "", ["Admin"], "core.extract"),
    (routes_search.router, "", ["Search"], "core.search"),
    (routes_feedback.router, "", ["Feedback"], "core.feedback"),
    (routes_console.router, "", ["Console"], "core.console"),
    (routes_file_resources.router, "", ["FileResources"], "core.files"),
    (routes_knowledge.router, "", ["Knowledge"], "core.knowledge"),
    (routes_admin.router, "/admin", ["Admin"], "core.admin"),
    (routes_auth.router, "", ["Auth"], "core.auth"),
    (routes_cerp.router, "/cerp", ["CERP"], "domain.cerp"),
    (routes_label.router, "", ["Label"], "domain.label"),
    (routes_label_print.router, "", ["LabelPrint"], "domain.label"),
    (routes_upload.router, "/upload", ["Upload"], "core.upload"),
    (routes_customers.router, "", ["Customers"], "domain.cerp"),
    (routes_edm.router, "", ["EDM"], "domain.edm"),
    (routes_quotes.router, "", ["Quotes"], "domain.quote"),
]


DEFAULT_LOCAL_ADMIN_USERNAME = ""
DEFAULT_LOCAL_ADMIN_PASSWORD = ""
DEFAULT_LOCAL_SUPER_ADMIN_USERNAME = ""
DEFAULT_LOCAL_SUPER_ADMIN_PASSWORD = ""
RETIRED_LOCAL_ADMIN_USERNAMES = {"ysadmin"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_username(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


async def _get_user_by_username_ci(session, username: str):
    normalized = _normalize_username(username)
    if not normalized:
        return None
    result = await session.execute(select(User).where(func.lower(User.username) == normalized))
    return result.scalar_one_or_none()


async def _get_user_by_email_ci(session, email: str):
    normalized = _normalize_email(email)
    if not normalized:
        return None
    result = await session.execute(select(User).where(func.lower(User.email) == normalized))
    return result.scalar_one_or_none()


async def _ensure_seed_user(*, username: str, password: str, role: str, email: str | None = None) -> None:
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        return

    async with SessionLocal() as session:
        normalized_email = _normalize_email(email) or None
        existing = await _get_user_by_username_ci(session, username)
        if existing is None and normalized_email:
            # The local UAT admin can be renamed through backend.env while
            # retaining its unique email and all existing relationships.
            existing = await _get_user_by_email_ci(session, normalized_email)
        if existing:
            changed = False
            if existing.username != username:
                existing.username = username
                changed = True
            if not (getattr(existing, "name", "") or "").strip():
                existing.name = username
                changed = True
            if normalized_email and getattr(existing, "email", None) != normalized_email:
                existing.email = normalized_email
                changed = True
            if existing.role != role:
                existing.role = role
                changed = True
            if not bool(getattr(existing, "is_active", True)):
                existing.is_active = True
                changed = True
            if not verify_password(password, existing.hashed_password):
                existing.hashed_password = get_password_hash(password)
                existing.password_set_at = _utcnow()
                changed = True
            elif getattr(existing, "password_set_at", None) is None:
                existing.password_set_at = _utcnow()
                changed = True
            if changed:
                existing.session_version = (getattr(existing, "session_version", 1) or 1) + 1
                await session.commit()
            return

        hashed_password = get_password_hash(password)
        session.add(
            User(
                name=username,
                username=username,
                email=normalized_email,
                hashed_password=hashed_password,
                role=role,
                is_active=True,
                password_set_at=_utcnow(),
            )
        )
        await session.commit()
        print(f"{role} '{username}' created.")


async def ensure_super_admin():
    username = os.getenv("YS_SUPER_ADMIN_USERNAME") or DEFAULT_LOCAL_SUPER_ADMIN_USERNAME
    password = os.getenv("YS_SUPER_ADMIN_PASSWORD") or DEFAULT_LOCAL_SUPER_ADMIN_PASSWORD
    await _ensure_seed_user(username=username, password=password, role="SAdmin")


async def ensure_local_admin():
    username = os.getenv("YS_ADMIN_USERNAME") or _env("ADMIN_USERNAME", DEFAULT_LOCAL_ADMIN_USERNAME)
    password = os.getenv("YS_ADMIN_PASSWORD") or _env("ADMIN_PASSWORD", DEFAULT_LOCAL_ADMIN_PASSWORD)
    email = _env("ADMIN_EMAIL", "jopasck@local.local")
    await _ensure_seed_user(username=username, password=password, role="admin", email=email)


async def deactivate_retired_local_admins():
    active_seed_usernames = {
        _normalize_username(os.getenv("YS_SUPER_ADMIN_USERNAME") or DEFAULT_LOCAL_SUPER_ADMIN_USERNAME),
        _normalize_username(os.getenv("YS_ADMIN_USERNAME") or _env("ADMIN_USERNAME", DEFAULT_LOCAL_ADMIN_USERNAME)),
    }
    retired_usernames = RETIRED_LOCAL_ADMIN_USERNAMES - active_seed_usernames
    if not retired_usernames:
        return

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(func.lower(User.username).in_(retired_usernames)))
        changed = False
        for user in result.scalars().all():
            user_changed = False
            if bool(getattr(user, "is_active", True)):
                user.is_active = False
                user_changed = True
            if getattr(user, "role", None) != "user":
                user.role = "user"
                user_changed = True
            if user_changed:
                user.session_version = (getattr(user, "session_version", 1) or 1) + 1
                changed = True
        if changed:
            await session.commit()
            print("Retired local admin users deactivated.")

DEFAULT_ROLES = [
    {
        "name": "user",
        "description": "Standard chat user",
        "is_active": True,
        "conversation_visibility_default": "private",
    },
    {
        "name": "admin",
        "description": "Console operator",
        "is_active": True,
        "conversation_visibility_default": "private",
    },
    {
        "name": "SAdmin",
        "description": "Full platform access",
        "is_active": True,
        "conversation_visibility_default": "private",
    },
]

DEFAULT_PERMISSIONS = [
    {"code": "admin.chat.access", "scope": "app", "description": "Access chat workspace"},
    {"code": "admin.projects.access", "scope": "app", "description": "Access project workspace"},
    {"code": "admin.labels.access", "scope": "app", "description": "Access label workspace"},
    {"code": "admin.files.access", "scope": "app", "description": "Access file resources workspace"},
    {"code": "admin.users.read", "scope": "console", "description": "List and inspect operator accounts"},
    {"code": "admin.users.write", "scope": "console", "description": "Create or update operator accounts"},
    {"code": "admin.roles.manage", "scope": "console", "description": "Create and edit role definitions"},
    {"code": "admin.permissions.manage", "scope": "console", "description": "Define permission codes"},
    {"code": "admin.settings.access", "scope": "app", "description": "Access settings workspace"},
]

DEFAULT_ROLE_PERMISSION_MAP = {
    "user": ["admin.chat.access"],
    "admin": [
        "admin.chat.access",
        "admin.projects.access",
        "admin.labels.access",
        "admin.files.access",
        "admin.users.read",
        "admin.users.write",
        "admin.settings.access",
    ],
    "SAdmin": [payload["code"] for payload in DEFAULT_PERMISSIONS],
}


async def ensure_default_roles():
    async with SessionLocal() as session:
        changed = False
        for payload in DEFAULT_ROLES:
            result = await session.execute(select(Role).where(Role.name == payload["name"]))
            if result.scalar_one_or_none():
                continue
            session.add(Role(**payload))
            changed = True
        if changed:
            await session.commit()
            print("Default roles seeded.")


async def ensure_default_permissions():
    async with SessionLocal() as session:
        changed = False
        for payload in DEFAULT_PERMISSIONS:
            result = await session.execute(select(Permission).where(Permission.code == payload["code"]))
            if result.scalar_one_or_none():
                continue
            session.add(Permission(**payload))
            changed = True
        if changed:
            await session.commit()
            print("Default permissions seeded.")


async def ensure_default_role_permissions():
    async with SessionLocal() as session:
        roles_result = await session.execute(
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.name.in_(DEFAULT_ROLE_PERMISSION_MAP.keys()))
        )
        permission_codes = {
            code
            for codes in DEFAULT_ROLE_PERMISSION_MAP.values()
            for code in codes
        }
        permissions_result = await session.execute(select(Permission).where(Permission.code.in_(permission_codes)))
        roles = {role.name: role for role in roles_result.scalars().all()}
        permissions = {permission.code: permission for permission in permissions_result.scalars().all()}

        changed = False
        for role_name, codes in DEFAULT_ROLE_PERMISSION_MAP.items():
            role = roles.get(role_name)
            if not role:
                continue
            existing_codes = {permission.code for permission in (role.permissions or [])}
            missing = [
                permissions[code]
                for code in codes
                if code in permissions and code not in existing_codes
            ]
            if not missing:
                continue
            role.permissions = [*(role.permissions or []), *missing]
            changed = True
        if changed:
            await session.commit()
            print("Default role permissions synced.")


async def ensure_conversation_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS customer_id INTEGER REFERENCES customers(id)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS project_id VARCHAR(255)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS project_label VARCHAR(255)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS owner_role VARCHAR(100)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'private'
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS archived_by INTEGER
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS archived_role VARCHAR(100)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS conversations
        ADD COLUMN IF NOT EXISTS customer_snapshot JSONB
        """
    ))
    await conn.execute(text(
        """
        UPDATE conversations
        SET visibility = 'private'
        WHERE visibility IS NULL OR visibility NOT IN ('private','public')
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_user_archived'
            ) THEN
                CREATE INDEX ix_conversations_user_archived ON conversations(user_id, is_archived);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_is_archived'
            ) THEN
                CREATE INDEX ix_conversations_is_archived ON conversations(is_archived);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_user_id'
            ) THEN
                CREATE INDEX ix_conversations_user_id ON conversations(user_id);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_customer_id'
            ) THEN
                CREATE INDEX ix_conversations_customer_id ON conversations(customer_id);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_visibility_owner'
            ) THEN
                CREATE INDEX ix_conversations_visibility_owner ON conversations(visibility, owner_role);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_project_id'
            ) THEN
                CREATE INDEX ix_conversations_project_id ON conversations(project_id);
            END IF;
        END
        $$;
        """
    ))
    await conn.execute(text(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = 'ix_conversations_user_project'
            ) THEN
                CREATE INDEX ix_conversations_user_project ON conversations(user_id, project_id);
            END IF;
        END
        $$;
        """
    ))

async def ensure_user_session_version(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 1
        """
    ))

async def ensure_user_role(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS role VARCHAR(50) NOT NULL DEFAULT 'user'
        """
    ))
    await conn.execute(text(
        """
        UPDATE users
        SET role = 'user'
        WHERE role IS NULL
        """
    ))


async def ensure_user_profile_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS name VARCHAR(255)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
        """
    ))
    await conn.execute(text(
        """
        UPDATE users
        SET
            name = COALESCE(NULLIF(TRIM(name), ''), username),
            is_active = COALESCE(is_active, true),
            updated_at = COALESCE(updated_at, NOW())
        """
    ))


async def ensure_user_email_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS email VARCHAR(255)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS users
        ADD COLUMN IF NOT EXISTS password_set_at TIMESTAMPTZ
        """
    ))
    await conn.execute(text(
        """
        UPDATE users
        SET email = LOWER(username)
        WHERE
            email IS NULL
            AND username IS NOT NULL
            AND POSITION('@' IN username) > 1
        """
    ))
    await conn.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email
        ON users (LOWER(email))
        WHERE email IS NOT NULL
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_users_email
        ON users (LOWER(email))
        WHERE email IS NOT NULL
        """
    ))


async def ensure_password_action_schema(conn):
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS password_action_tokens (
            id UUID PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            purpose VARCHAR(32) NOT NULL,
            token_hash VARCHAR(128) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by VARCHAR(255)
        )
        """
    ))
    await conn.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_password_action_tokens_hash
        ON password_action_tokens (token_hash)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_password_action_tokens_user_purpose
        ON password_action_tokens (user_id, purpose)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_password_action_tokens_email
        ON password_action_tokens (LOWER(email))
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_password_action_tokens_expires_at
        ON password_action_tokens (expires_at)
        """
    ))


async def ensure_role_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS roles
        ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS roles
        ADD COLUMN IF NOT EXISTS conversation_visibility_default VARCHAR(20) NOT NULL DEFAULT 'private'
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS roles
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
        """
    ))
    await conn.execute(text(
        """
        UPDATE roles
        SET
            is_active = COALESCE(is_active, true),
            conversation_visibility_default = CASE
                WHEN LOWER(COALESCE(conversation_visibility_default, 'private')) = 'public' THEN 'public'
                ELSE 'private'
            END,
            updated_at = COALESCE(updated_at, NOW())
        """
    ))

async def ensure_message_enrichment_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS messages
        ADD COLUMN IF NOT EXISTS summary_snapshot VARCHAR(255)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS messages
        ADD COLUMN IF NOT EXISTS highlights JSONB
        """
    ))

async def ensure_label_description_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS label_descriptions
        ADD COLUMN IF NOT EXISTS price_override INTEGER
        """
    ))


async def ensure_label_print_schema(conn):
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS label_print_items (
            id UUID PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            product_code VARCHAR(64) NOT NULL,
            size VARCHAR(16) NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS label_print_items
        ADD COLUMN IF NOT EXISTS price_override INTEGER
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS label_print_items
        ADD COLUMN IF NOT EXISTS product_snapshot JSONB
        """
    ))
    await conn.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_label_print_user_product_size
        ON label_print_items (user_id, product_code, size)
        """
    ))


async def ensure_project_schema(conn):
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(255) PRIMARY KEY,
            owner_user_id INTEGER NOT NULL REFERENCES users(id),
            name VARCHAR(255) NOT NULL,
            visibility VARCHAR(20) NOT NULL DEFAULT 'private',
            customer_type VARCHAR(20),
            trade_count INTEGER,
            last_trade_at TIMESTAMPTZ,
            avg_unit_price INTEGER,
            preference_note TEXT,
            region VARCHAR(255),
            has_wine_cabinet BOOLEAN,
            is_archived BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ))
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS project_invitations (
            id UUID PRIMARY KEY,
            project_id VARCHAR(255) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            invited_email VARCHAR(255) NOT NULL,
            invited_user_id INTEGER REFERENCES users(id),
            invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            responded_at TIMESTAMPTZ
        )
        """
    ))
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS conversation_invitations (
            id UUID PRIMARY KEY,
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            invited_email VARCHAR(255) NOT NULL,
            invited_user_id INTEGER REFERENCES users(id),
            invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            responded_at TIMESTAMPTZ
        )
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_projects_owner_archived
        ON projects(owner_user_id, is_archived)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_projects_name
        ON projects(name)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_project_invitations_project_status
        ON project_invitations(project_id, status)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_project_invitations_email_status
        ON project_invitations(invited_email, status)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_invitations_conversation_status
        ON conversation_invitations(conversation_id, status)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_conversation_invitations_email_status
        ON conversation_invitations(invited_email, status)
        """
    ))
    await conn.execute(text(
        """
        INSERT INTO projects (id, owner_user_id, name, visibility, created_at, updated_at)
        WITH ranked AS (
            SELECT
                c.project_id,
                c.user_id,
                c.project_label,
                c.visibility,
                ROW_NUMBER() OVER (
                    PARTITION BY c.project_id
                    ORDER BY
                        c.updated_at DESC NULLS LAST,
                        c.created_at DESC NULLS LAST,
                        c.id DESC
                ) AS rn
            FROM conversations c
            WHERE
                c.project_id IS NOT NULL
                AND c.project_id <> ''
                AND c.user_id IS NOT NULL
        )
        SELECT
            r.project_id,
            r.user_id,
            COALESCE(NULLIF(r.project_label, ''), r.project_id),
            COALESCE(NULLIF(r.visibility, ''), 'private'),
            NOW(),
            NOW()
        FROM ranked r
        WHERE r.rn = 1
        ON CONFLICT (id) DO UPDATE
        SET
            name = COALESCE(NULLIF(projects.name, ''), EXCLUDED.name),
            owner_user_id = COALESCE(projects.owner_user_id, EXCLUDED.owner_user_id),
            updated_at = NOW()
        """
    ))


async def ensure_file_resource_schema(conn):
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS file_resources (
            id UUID PRIMARY KEY,
            resource_type VARCHAR(32) NOT NULL DEFAULT 'wine_label',
            display_name VARCHAR(255) NOT NULL,
            producer VARCHAR(255),
            department_role VARCHAR(100),
            visibility VARCHAR(20) NOT NULL DEFAULT 'public',
            attachment_path TEXT NOT NULL,
            attachment_filename VARCHAR(255) NOT NULL,
            attachment_mime VARCHAR(255) NOT NULL,
            attachment_size BIGINT,
            cerp_code_full VARCHAR(64),
            cerp_code_family VARCHAR(64),
            created_by_user_id INTEGER REFERENCES users(id),
            created_by_username VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE file_resources
        ADD COLUMN IF NOT EXISTS department_role VARCHAR(100)
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE file_resources
        ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) NOT NULL DEFAULT 'public'
        """
    ))
    await conn.execute(text(
        """
        UPDATE file_resources
        SET visibility = 'public'
        WHERE visibility IS NULL OR LOWER(COALESCE(visibility, '')) NOT IN ('private', 'public')
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_type
        ON file_resources(resource_type)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_cerp_code_full
        ON file_resources(cerp_code_full)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_cerp_code_family
        ON file_resources(cerp_code_family)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_created_by_user_id
        ON file_resources(created_by_user_id)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_department_role
        ON file_resources(department_role)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_visibility
        ON file_resources(visibility)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_file_resources_type_visibility_department
        ON file_resources(resource_type, visibility, department_role)
        """
    ))

async def ensure_feedback_phase2_schema(conn):
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS case_id TEXT
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS review_status TEXT
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS reviewed_by TEXT
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS review_note TEXT
        """
    ))
    await conn.execute(text(
        """
        ALTER TABLE IF EXISTS search_feedback
        ADD COLUMN IF NOT EXISTS dataset_split TEXT
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_search_feedback_case_id
        ON search_feedback(case_id)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_search_feedback_review_status
        ON search_feedback(review_status)
        """
    ))
    await conn.execute(text(
        """
        CREATE INDEX IF NOT EXISTS ix_search_feedback_dataset_split
        ON search_feedback(dataset_split)
        """
    ))

async def prepare_database():
    max_attempts = int(os.getenv("DB_INIT_MAX_RETRIES", "20"))
    delay_seconds = int(os.getenv("DB_INIT_RETRY_DELAY", "3"))

    for attempt in range(1, max_attempts + 1):
        try:
            async with async_engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await ensure_conversation_schema(conn)
                await ensure_user_role(conn)
                await ensure_user_session_version(conn)
                await ensure_user_profile_schema(conn)
                await ensure_user_email_schema(conn)
                await ensure_role_schema(conn)
                await ensure_password_action_schema(conn)
                await ensure_message_enrichment_schema(conn)
                await ensure_label_description_schema(conn)
                await ensure_label_print_schema(conn)
                await ensure_project_schema(conn)
                await ensure_file_resource_schema(conn)
                await ensure_feedback_phase2_schema(conn)
            await ensure_default_roles()
            await ensure_default_permissions()
            await ensure_default_role_permissions()
            await ensure_super_admin()
            await ensure_local_admin()
            await deactivate_retired_local_admins()
            if is_module_enabled("domain.cerp") and is_fake_cerp_mode():
                seed_result = await FakeCerpImportService().ensure_seeded()
                if seed_result.get("seeded"):
                    print(f"Fake CERP seeded: {seed_result.get('imported_rows', 0)} products.")
                elif seed_result.get("missing_default_path"):
                    print(f"Fake CERP seed skipped: missing default workbook {seed_result.get('missing_default_path')}")
            print("Database tables created/checked.")
            return
        except (OperationalError, asyncpg.exceptions.CannotConnectNowError) as exc:
            if attempt >= max_attempts:
                print("Database initialization failed after retries.")
                raise
            wait = delay_seconds
            print(f"Database not ready (attempt {attempt}/{max_attempts}): {exc}. Retrying in {wait}s...")
            await asyncio.sleep(wait)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup: Creating database tables...")
    await prepare_database()
    yield
    print("Application shutdown.")


app = FastAPI(lifespan=lifespan)


for router, prefix, tags, module_id in ROUTERS:
    if not is_module_enabled(module_id):
        continue
    app.include_router(router, prefix=prefix, tags=tags)
    api_prefix = f"/api{prefix}" if prefix else "/api"
    app.include_router(router, prefix=api_prefix, tags=tags)


@app.get("/")
async def read_root():
    return {"message": "YS API is running."}
