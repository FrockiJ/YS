from __future__ import annotations

from ...core.extensions import ModuleDefinition
from .chat_hooks import YsOutdoorChatHooks


DOMAIN_MODULE_ID = "ys_outdoor"

DOMAIN_PROFILE = {
    "id": "ys-outdoor",
    "name": "YS",
    "display_name": "YS",
    "description": "Outdoor intelligent system profile for trail gear, fishing tackle, inventory, quotes, labels, and email workflows.",
    "default_tone": "concise, operational, and business-friendly",
}

MODULE_DEFINITIONS = (
    ModuleDefinition(
        id="domain.cerp",
        name="Business connector",
        layer="domain",
        category="connector",
        description="YS Outdoor product inventory connector and product lookup APIs.",
        backend_routes=("cerp", "customers"),
        dependencies=("core.chat",),
        metadata={"domain_module": DOMAIN_MODULE_ID},
    ),
    ModuleDefinition(
        id="domain.quote",
        name="Quote and return workflow",
        layer="domain",
        category="business",
        description="Quote, return, customer pricing, and recommendation workflow.",
        backend_routes=("quotes",),
        frontend_routes=("quote", "quote-returns"),
        dependencies=("domain.cerp",),
        metadata={"domain_module": DOMAIN_MODULE_ID},
    ),
    ModuleDefinition(
        id="domain.label",
        name="Label workflow",
        layer="domain",
        category="business",
        description="Label descriptions and label print workflow.",
        backend_routes=("label", "label_print"),
        frontend_routes=("label-settings", "label-print"),
        permissions=("admin.labels.access",),
        metadata={"domain_module": DOMAIN_MODULE_ID},
    ),
    ModuleDefinition(
        id="domain.edm",
        name="EDM and email workflow",
        layer="domain",
        category="business",
        description="EDM preview/share and email composition workflow.",
        backend_routes=("edm",),
        frontend_routes=("edm", "edm-share", "email"),
        dependencies=("domain.quote",),
        metadata={"domain_module": DOMAIN_MODULE_ID},
    ),
)


def get_chat_hooks() -> YsOutdoorChatHooks:
    return YsOutdoorChatHooks()
