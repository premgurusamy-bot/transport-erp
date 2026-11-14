"""Import every model module so SQLAlchemy metadata (and Alembic) see all tables."""
from app.core.db import Base  # noqa: F401
from app.modules.commercial import models as commercial  # noqa: F401
from app.modules.finance import models as finance  # noqa: F401
from app.modules.fleet import models as fleet  # noqa: F401
from app.modules.masters import models as masters  # noqa: F401
from app.modules.operations import models as operations  # noqa: F401
from app.modules.people import models as people  # noqa: F401
from app.modules.platform import models as platform  # noqa: F401
from app.modules.risk import models as risk  # noqa: F401
from app.modules.supply import models as supply  # noqa: F401
