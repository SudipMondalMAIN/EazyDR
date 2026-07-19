"""
Import every SQLAlchemy model module here. This file has no other purpose —
it exists purely so that `Base.metadata` is fully populated before
`create_all()` (dev convenience) or Alembic autogenerate runs. If you add a
new module with a models.py, add its import here too.
"""
from app.modules.admin import models as admin_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.banners import models as banner_models  # noqa: F401
from app.modules.bookings import models as booking_models  # noqa: F401
from app.modules.facilities import models as facility_models  # noqa: F401
from app.modules.favorites import models as favorite_models  # noqa: F401
from app.modules.notifications import models as notification_models  # noqa: F401
from app.modules.queue import models as queue_models  # noqa: F401
from app.modules.rewards import earning_models  # noqa: F401
from app.modules.rewards import models as reward_models  # noqa: F401
from app.modules.reviews import models as review_models  # noqa: F401
from app.modules.settlements import models as settlement_models  # noqa: F401
