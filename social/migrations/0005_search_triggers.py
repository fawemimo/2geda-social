"""Install the post and comment search-vector triggers.

`Comment` gains the `search_vector` column it never had, so comments can be
searched at all.

Both vectors denormalise the author's handle alongside the row's own text. A
`BEFORE ROW` trigger cannot join to `accounts_user`, but it can read the handle
in a subquery -- and it has to, because otherwise a query like
`?q=choreographer routine` (one token naming the author, one naming the
content) could not match a post at all: `ts_rank` and `@@` only ever see what a
row stores about itself. Folding the handle in at write time keeps the search
itself to a single index-backed `search_vector @@ tsquery` lookup, and
websearch's implicit AND then gives per-token "every term must appear"
semantics for free.

The handle sits at weight C: weaker than the content, since a post that
mentions the handle is a weaker match than one that *is* the content, but strong
enough that searching a name surfaces their posts.
"""

from django.db import migrations

# body is the only text on a post that is worth full-text weight; the author
# handle and a reshare quote are progressively weaker signals.
POST_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION social_post_search_vector_update()
RETURNS TRIGGER AS $$
DECLARE
  author_handle text;
BEGIN
  SELECT u.username INTO author_handle
  FROM accounts_user u
  WHERE u.id = NEW.author_id;

  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.body,            '')), 'A') ||
    setweight(to_tsvector('english', coalesce(author_handle,      '')), 'C') ||
    setweight(to_tsvector('english', coalesce(NEW.reshare_comment, '')), 'D');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS social_post_search_vector_trigger ON social_post;
CREATE TRIGGER social_post_search_vector_trigger
  BEFORE INSERT OR UPDATE OF body, reshare_comment, author_id
  ON social_post
  FOR EACH ROW EXECUTE FUNCTION social_post_search_vector_update();
"""

COMMENT_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION social_comment_search_vector_update()
RETURNS TRIGGER AS $$
DECLARE
  author_handle text;
BEGIN
  SELECT u.username INTO author_handle
  FROM accounts_user u
  WHERE u.id = NEW.author_id;

  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.body,       '')), 'A') ||
    setweight(to_tsvector('english', coalesce(author_handle, '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS social_comment_search_vector_trigger ON social_comment;
CREATE TRIGGER social_comment_search_vector_trigger
  BEFORE INSERT OR UPDATE OF body, author_id
  ON social_comment
  FOR EACH ROW EXECUTE FUNCTION social_comment_search_vector_update();
"""

DROP_POST_TRIGGER = "DROP TRIGGER IF EXISTS social_post_search_vector_trigger ON social_post;"
DROP_COMMENT_TRIGGER = (
    "DROP TRIGGER IF EXISTS social_comment_search_vector_trigger ON social_comment;"
)

# Rebuild every existing row: assigning a column to itself fires UPDATE, which is
# enough to make the trigger recompute the vector from scratch.
BACKFILL = """
UPDATE social_post SET body = body;
UPDATE social_comment SET body = body;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("social", "0004_comment_search_vector_comment_comment_search_gin_idx"),
        # The triggers read accounts_user.username.
        ("accounts", "0006_search_triggers_and_trgm"),
    ]

    operations = [
        migrations.RunSQL(POST_SEARCH_TRIGGER, reverse_sql=DROP_POST_TRIGGER),
        migrations.RunSQL(COMMENT_SEARCH_TRIGGER, reverse_sql=DROP_COMMENT_TRIGGER),
        migrations.RunSQL(BACKFILL, reverse_sql=migrations.RunSQL.noop),
    ]
