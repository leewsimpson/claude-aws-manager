"""ORM models. Importing this package registers every table on ``Base.metadata``.

Alembic autogeneration and the test suite rely on importing ``app.models`` so
that all tables are present before ``Base.metadata`` is read.
"""

from app.models.audit_log import AuditLog
from app.models.cost_centre import CostCentre
from app.models.cost_centre_owner import CostCentreOwner
from app.models.global_setting import GlobalSetting
from app.models.inference_profile import InferenceProfile
from app.models.key import Key
from app.models.key_request import KeyRequest
from app.models.pricing_cache import PricingCache
from app.models.usage_snapshot import UsageSnapshot
from app.models.user import User

__all__ = [
    "AuditLog",
    "CostCentre",
    "CostCentreOwner",
    "GlobalSetting",
    "InferenceProfile",
    "Key",
    "KeyRequest",
    "PricingCache",
    "UsageSnapshot",
    "User",
]
