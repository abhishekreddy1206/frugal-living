# Import all model modules so Alembic autogenerate sees them.
from app.models import core  # noqa: F401
from app.models import food  # noqa: F401
from app.models import content  # noqa: F401
from app.models import ai  # noqa: F401
from app.models import tracking  # noqa: F401
# from app.models import bills      # add when Tier S ships
# from app.models import health     # add when Tier S ships
# from app.models import community  # add when Tier B ships
