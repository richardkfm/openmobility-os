"""Test discovery that works when run from the repository root.

The Django apps live under ``backend/``. ``manage.py`` puts that directory on
``sys.path``, which is why ``workspaces``, ``datasets`` and the rest import as
top-level modules — but ``backend/`` is deliberately not a package itself, and
unittest discovery cannot descend into a directory that has no ``__init__.py``.

Discovery starts at the current working directory. So ``python manage.py test``
run from the repository root — the command CONTRIBUTING.md and CLAUDE.md both
tell contributors to run before every commit — found nothing at all and exited
0. CI reported ``Ran 0 tests in 0.000s`` and the job went green, for every pull
request, while ~600 tests sat in the tree untouched.

Pointing discovery at ``BACKEND_DIR`` when no labels are given repairs the
contributor command and CI in one place. It is done here rather than by adding
``backend/__init__.py``, because making ``backend`` a package would break the
top-level app imports that the whole project is built on.
"""

from django.conf import settings
from django.test.runner import DiscoverRunner


class BackendDiscoverRunner(DiscoverRunner):
    """``DiscoverRunner`` that discovers under ``BACKEND_DIR`` by default.

    Explicit labels (``manage.py test workspaces``, ``manage.py test
    measures.tests.ScoringTests``) are passed straight through untouched. This
    only changes what "run everything" resolves to.

    ``top_level`` is left for ``DiscoverRunner`` to infer. It walks up from the
    start directory while ``__init__.py`` files exist, so it stops at
    ``backend/`` itself — exactly the entry that is on ``sys.path``, which keeps
    each app importable under the same name the settings use.
    """

    def build_suite(self, test_labels=None, **kwargs):
        return super().build_suite(test_labels or [str(settings.BACKEND_DIR)], **kwargs)
