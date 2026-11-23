"""Store-level settings kept in core.app_settings.

digital_only: the store sells only digital products. Shipping and packaging
costs are then zero by definition (not "missing"), and inventory/stock rules
don't apply. This is the owner's declaration, shown wherever it changes a result.
"""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AppSetting

KEY = "store.settings"
DEFAULTS = {"digital_only": False}


def get_store_settings(s: Session) -> dict:
    row = s.get(AppSetting, KEY)
    return {**DEFAULTS, **((row.value if row else {}) or {})}


def set_store_settings(s: Session, **changes) -> dict:
    value = {**get_store_settings(s), **changes}
    stmt = insert(AppSetting).values(key=KEY, value=value)
    s.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    s.commit()
    return value
