
# ── Users ──────────────────────────────────────────────────────────────────
SQL_USER_SEARCH_TRIGGER = """
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

# ── Profiles ───────────────────────────────────────────────────────────────
SQL_PROFILE_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION profiles_profile_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.display_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.bio,          '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.website,      '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS profiles_profile_search_vector_trigger ON profiles_user_profile;
CREATE TRIGGER profiles_profile_search_vector_trigger
  BEFORE INSERT OR UPDATE OF display_name, bio, website
  ON profiles_user_profile
  FOR EACH ROW EXECUTE FUNCTION profiles_profile_search_vector_update();
"""

# ── Posts ──────────────────────────────────────────────────────────────────
SQL_POST_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION social_post_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.body,             '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.location_label,   '')), 'C') ||
    setweight(to_tsvector('english', coalesce(NEW.reshare_comment,  '')), 'D');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS social_post_search_vector_trigger ON social_post;
CREATE TRIGGER social_post_search_vector_trigger
  BEFORE INSERT OR UPDATE OF body, location_label, reshare_comment
  ON social_post
  FOR EACH ROW EXECUTE FUNCTION social_post_search_vector_update();
"""

# ── Media ──────────────────────────────────────────────────────────────────
SQL_MEDIA_SEARCH_TRIGGER = """
CREATE OR REPLACE FUNCTION media_media_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.alt_text,           '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.caption,            '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.original_filename,  '')), 'C');
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS media_media_search_vector_trigger ON media_media;
CREATE TRIGGER media_media_search_vector_trigger
  BEFORE INSERT OR UPDATE OF alt_text, caption, original_filename
  ON media_media
  FOR EACH ROW EXECUTE FUNCTION media_media_search_vector_update();
"""

ALL_TRIGGERS = [
    SQL_USER_SEARCH_TRIGGER,
    SQL_PROFILE_SEARCH_TRIGGER,
    SQL_POST_SEARCH_TRIGGER,
    SQL_MEDIA_SEARCH_TRIGGER,
]
