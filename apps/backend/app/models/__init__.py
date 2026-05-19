# Import all model modules so Alembic autogenerate sees them.
from app.models import (
    ai,  # noqa: F401
    content,  # noqa: F401
    core,  # noqa: F401
    food,  # noqa: F401
    tracking,  # noqa: F401
)
# from app.models import bills      # add when Tier S ships
# from app.models import health     # add when Tier S ships
# from app.models import community  # add when Tier B ships
