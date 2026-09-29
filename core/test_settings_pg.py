"""Test settings backed by a real PostgreSQL server.

The default `core.test_settings` uses in-memory SQLite, which cannot run
`to_tsvector` / `ts_rank` / trigram. The search feature therefore has two
code paths, and this module exists so the Postgres one is actually exercised
rather than shipped untested.

Run with:

    TEST_DB_PORT=55432 pytest search/tests \\
        --ds=core.test_settings_pg -o addopts="-ra --tb=short -p no:cacheprovider"

Connection details come from `TEST_DB_*` (see the defaults below); point
`TEST_DB_HOST`/`TEST_DB_PORT` at any PostgreSQL you can reach, e.g. the
`db` service in docker-compose.

Note the empty `addopts`: the default pytest.ini passes `--no-migrations`,
which builds tables straight from the models and would skip every trigger
migration. Here the migrations must run for the search vectors to exist --
which is also what proves the trigger migrations themselves are correct.
"""

import os

os.environ.setdefault("DB_NAME", os.getenv("TEST_DB_NAME", "social_test"))
os.environ.setdefault("DB_USER", os.getenv("TEST_DB_USER", "postgres"))
os.environ.setdefault("DB_PASSWORD", os.getenv("TEST_DB_PASSWORD", "admin#1234"))
os.environ.setdefault("DB_HOST", os.getenv("TEST_DB_HOST", "127.0.0.1"))
os.environ.setdefault("DB_PORT", os.getenv("TEST_DB_PORT", "5432"))

from core.test_settings import *  # noqa: F401,F403,E402

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ["DB_HOST"],
        "PORT": os.environ["DB_PORT"],
        # No explicit TEST name, so Django builds and tears down a separate
        # `test_<NAME>` database. Pointing TEST at the source name would make
        # Django try to create a database that already exists, fail, and then
        # quietly run the tests against the development data instead.
    }
}
