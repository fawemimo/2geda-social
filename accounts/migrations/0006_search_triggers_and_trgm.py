from core.indexes import TrigramGinIndex
from django.contrib.postgres.indexes import OpClass
from django.db import migrations
from django.db.models import F

# username is the strongest signal on a user row, email slightly weaker.
USER_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION accounts_user_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.username, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.email,    '')), 'B');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_user_search_vector_trigger ON accounts_user;
CREATE TRIGGER accounts_user_search_vector_trigger
  BEFORE INSERT OR UPDATE OF username, email
  ON accounts_user
  FOR EACH ROW EXECUTE FUNCTION accounts_user_search_vector_update();
"""

# display_name / first_name / last_name are how people find each other, so they
# all carry weight A. The previous version omitted first/last name even though
# the model's docstring claimed they were covered.
PROFILE_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION profiles_profile_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.display_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.first_name,  '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.last_name,   '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.bio,          '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.website,      '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS profiles_profile_search_vector_trigger ON profiles_user_profile;
CREATE TRIGGER profiles_profile_search_vector_trigger
  BEFORE INSERT OR UPDATE OF display_name, first_name, last_name, bio, website
  ON profiles_user_profile
  FOR EACH ROW EXECUTE FUNCTION profiles_profile_search_vector_update();
"""

DROP_USER_TRIGGER = (
    "DROP TRIGGER IF EXISTS accounts_user_search_vector_trigger ON accounts_user;"
)
DROP_PROFILE_TRIGGER = (
    "DROP TRIGGER IF EXISTS profiles_profile_search_vector_trigger"
    " ON profiles_user_profile;"
)

# Assigning a column to itself is enough to fire `BEFORE UPDATE OF <col>`, so
# this populates every pre-existing row without recomputing in Python.
BACKFILL = """
UPDATE accounts_user SET username = username WHERE search_vector IS NULL;
UPDATE profiles_user_profile SET display_name = display_name WHERE search_vector IS NULL;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_user_last_seen_userprofile_current_city_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(USER_SEARCH_TRIGGER, reverse_sql=DROP_USER_TRIGGER),
        migrations.RunSQL(PROFILE_SEARCH_TRIGGER, reverse_sql=DROP_PROFILE_TRIGGER),
        migrations.AddIndex(
            model_name="user",
            index=TrigramGinIndex(
                OpClass(F("username"), name="gin_trgm_ops"),
                name="user_username_trgm_idx",
            ),
        ),
        migrations.RunSQL(BACKFILL, reverse_sql=migrations.RunSQL.noop),
    ]
