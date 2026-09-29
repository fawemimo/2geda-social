"""Install the media and collection search-vector triggers.

`media_media` already had a trigger definition (in a module at the repo root
that nothing imported, so it was never applied) and `media_collection` had a
`search_vector` column plus a GIN index but no trigger at all, so the column was
permanently NULL. Both are wired up here.

Both vectors also denormalise the owner's handle, for the same reason as
`social.0005_search_triggers`: without it, `?q=ade+shoes` could not find a clip
owned by `ade`, because `@@` only sees what a row stores about itself.

`original_filename` and the handle both sit at C: weak signals, neither worth
outranking a real caption.
"""

from django.db import migrations

# alt_text is authored deliberately to describe the content, so it outranks the
# auto-generated caption and filename.
MEDIA_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION media_media_search_vector_update()
RETURNS TRIGGER AS $$
DECLARE
  owner_handle text;
BEGIN
  SELECT u.username INTO owner_handle
  FROM accounts_user u
  WHERE u.id = NEW.owner_id;

  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.alt_text,          '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.caption,           '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.original_filename, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(owner_handle,           '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS media_media_search_vector_trigger ON media_media;
CREATE TRIGGER media_media_search_vector_trigger
  BEFORE INSERT OR UPDATE OF alt_text, caption, original_filename, owner_id
  ON media_media
  FOR EACH ROW EXECUTE FUNCTION media_media_search_vector_update();
"""

COLLECTION_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION media_collection_search_vector_update()
RETURNS TRIGGER AS $$
DECLARE
  owner_handle text;
BEGIN
  SELECT u.username INTO owner_handle
  FROM accounts_user u
  WHERE u.id = NEW.owner_id;

  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.name,        '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(owner_handle,    '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS media_collection_search_vector_trigger ON media_collection;
CREATE TRIGGER media_collection_search_vector_trigger
  BEFORE INSERT OR UPDATE OF name, description, owner_id
  ON media_collection
  FOR EACH ROW EXECUTE FUNCTION media_collection_search_vector_update();
"""

DROP_MEDIA_TRIGGER = "DROP TRIGGER IF EXISTS media_media_search_vector_trigger ON media_media;"
DROP_COLLECTION_TRIGGER = (
    "DROP TRIGGER IF EXISTS media_collection_search_vector_trigger ON media_collection;"
)

# Rebuild every existing row: assigning a column to itself fires UPDATE, which is
# enough to make the trigger recompute the vector from scratch.
BACKFILL = """
UPDATE media_media SET caption = caption;
UPDATE media_collection SET name = name;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("medias", "0001_initial"),
        # The triggers read accounts_user.username.
        ("accounts", "0006_search_triggers_and_trgm"),
    ]

    operations = [
        migrations.RunSQL(MEDIA_SEARCH_TRIGGER, reverse_sql=DROP_MEDIA_TRIGGER),
        migrations.RunSQL(COLLECTION_SEARCH_TRIGGER, reverse_sql=DROP_COLLECTION_TRIGGER),
        migrations.RunSQL(BACKFILL, reverse_sql=migrations.RunSQL.noop),
    ]
