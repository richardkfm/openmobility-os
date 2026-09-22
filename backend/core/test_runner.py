"""Test discovery and test-time storage, for a suite run from the repo root.

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
from django.test.utils import override_settings

# Static files are served in production by WhiteNoise's *manifest* storage,
# which rewrites every `{% static %}` URL to a hashed filename looked up in the
# `staticfiles.json` that `collectstatic` writes. A test run does not collect
# static files, so that manifest does not exist, and every test that renders a
# template died on `ValueError: Missing staticfiles manifest entry for
# 'css/components.css'` — the template layer, not the code under test.
#
# Tests therefore use the plain storage, which passes the path through
# unchanged. Overriding the setting (rather than assigning to it) matters:
# Django's `setting_changed` receiver resets the already-instantiated
# `staticfiles_storage` in response, which a plain assignment would not.
TEST_STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"


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

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._staticfiles_override = override_settings(
            STATICFILES_STORAGE=TEST_STATICFILES_STORAGE
        )
        self._staticfiles_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._staticfiles_override.disable()
        super().teardown_test_environment(**kwargs)
