from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

from accounts.models import Follow, User
from accounts.services.exceptions import ValidationError
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.db.models import (
    BooleanField,
    Case,
    Exists,
    F,
    FloatField,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Value,
    When,
)
from django.db.models.functions import Greatest, Least
from medias.models import Collection, Media
from search.enums import SearchType
from social.models import Comment, Like, Post
from utils.enum import FollowStatus, MediaType, MediaVisibility, PostVisibility

# A query shorter than this returns nothing useful and would scan the whole
# corpus for a near-universal match, so we reject it outright.
MIN_QUERY_LENGTH = 2

# Hard ceiling on how deep any single type is scanned to service one page.
# Results from different tables are interleaved in Python, so serving page N
# means reading the first N*page_size rows of each type -- this bound is what
# keeps that from turning into an unbounded scan. `totalItem` and the facet
# counts always come from real COUNTs and stay accurate regardless, but a page
# deeper than this cap can legitimately come back short or empty.
MAX_WINDOW_PER_TYPE = 200

# ---- Full-text (PostgreSQL) tuning ----------------------------------------

TEXT_SEARCH_CONFIG = "english"

# Divides ts_rank by the document length, so a one-word caption does not
# outrank a paragraph that matches far better. Without it, ts_rank grows with
# document size and short-but-perfect rows get buried.
RANK_NORMALIZATION = 32

# Additive nudges on top of ts_rank, for the two things ts_rank cannot see: a
# field whose entire value is the query, and a field the query starts at the
# beginning of. ts_rank sums the weight of the matching lexemes, so without
# these a post that merely mentions "dancing" ties with one titled "dancing".
# They are deliberately smaller than the spread of a good ts_rank difference,
# so they break ties rather than override relevance.
EXACT_MATCH_BONUS = 0.3
PREFIX_MATCH_BONUS = 0.1

# Character trigrams are meaningless below this length, so a very short query is
# left to the vector alone rather than being fuzzy-matched against handles.
MIN_TRIGRAM_QUERY_LENGTH = 3

# The similarity threshold behind `__trigram_similar` is Postgres's own
# `pg_trgm.similarity_threshold` (0.3 by default), not a setting here -- it is
# deliberately left to the server.

# ---- Portable (substring) tuning -----------------------------------------

# How tightly a single query token matches one field value. Lower sorts first.
RANK_EXACT = 0
RANK_PREFIX = 1
RANK_CONTAINS = 2

# Number of distinct per-token buckets. Used to shift the phrase tier so that
# phrase contiguity always dominates, and tightness only breaks ties within a
# phrase tier.
TIGHTNESS_BUCKETS = 3

# Worst achievable rank on the portable path: phrase tier 1 (scattered) x 3 +
# contains. The portable path reports `RANK_WORST - rank` as a score so that
# higher is better on both paths.
RANK_WORST = TIGHTNESS_BUCKETS + RANK_CONTAINS


class ScoredResult(NamedTuple):
    """One ranked hit, before serialisation."""

    type: str
    item: Any
    score: float
    created_at: Any


class SearchResult(NamedTuple):
    """Everything the view needs to build one response envelope."""

    query: str
    tokens: list[str]
    results: list[ScoredResult]
    facets: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    applied_filters: dict[str, Any]
    engine: str


@dataclass(frozen=True)
class SearchSpec:
    """How one content type is searched.

    vectors : `search_vector` columns, each maintained by a database trigger.
              These are the index-backed, stemmed, weighted fields.
    trigram : plain text columns that are *not* in any vector -- currently the
              author/owner handle on content rows. A row trigger cannot copy a
              related model's column into its own vector (that needs a join),
              so these are matched with pg_trgm instead.
    """

    vectors: tuple[str, ...] = ()
    trigram: tuple[str, ...] = ()
    substring: tuple[str, ...] = ()


SEARCH_SPECS: dict[str, SearchSpec] = {
    # A user's own searchable text is split across two tables, so it has two
    # vectors; there is no further column worth trigram-matching.
    SearchType.USERS.value: SearchSpec(
        vectors=("search_vector", "profile__search_vector"),
        substring=(
            "username",
            "profile__display_name",
            "profile__first_name",
            "profile__last_name",
            "profile__bio",
        ),
    ),
    SearchType.POSTS.value: SearchSpec(
        vectors=("search_vector",),
        trigram=("author__username",),
        substring=("body", "author__username", "reshare_comment"),
    ),
    SearchType.COMMENTS.value: SearchSpec(
        vectors=("search_vector",),
        trigram=("author__username",),
        substring=("body", "author__username"),
    ),
    SearchType.MEDIA.value: SearchSpec(
        vectors=("search_vector",),
        trigram=("owner__username",),
        substring=(
            "caption",
            "alt_text",
            "original_filename",
            "owner__username",
        ),
    ),
    SearchType.COLLECTIONS.value: SearchSpec(
        vectors=("search_vector",),
        trigram=("owner__username",),
        substring=("name", "description", "owner__username"),
    ),
}



class BaseMatcher:
    """Turns a queryset into "rows matching this query, scored"."""

    #: Advertised in the response so clients (and logs) can tell which
    #: implementation served a request.
    engine = "base"

    def apply(
        self, queryset: QuerySet, *, spec: SearchSpec, query: str, tokens: list[str]
    ) -> QuerySet:
        raise NotImplementedError


class PostgresFullTextMatcher(BaseMatcher):
    """Index-backed search using the models' `search_vector` columns.

    Relies on the triggers installed by the `accounts`/`social`/`medias`
    search migrations. The query itself is built with `websearch_to_tsquery`,
    so users get web search syntax for free: quoted phrases, `or`, and `-`
    exclusions.
    """

    engine = "postgres_fulltext"

    def build_ts_query(self, raw_query: str) -> Any:
        from django.contrib.postgres.search import SearchQuery

        return SearchQuery(raw_query, config=TEXT_SEARCH_CONFIG, search_type="websearch")

    def ts_query_is_empty(self, raw_query: str) -> bool:
        """A query made only of stopwords or punctuation yields an empty tsquery.

        An empty tsquery matches nothing, so this has to be detected up front
        or those searches would silently return zero results.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT websearch_to_tsquery(%s, %s) = ''::tsquery",
                [TEXT_SEARCH_CONFIG, raw_query],
            )
            return bool(cursor.fetchone()[0])

    def apply(
        self, queryset: QuerySet, *, spec: SearchSpec, query: str, tokens: list[str]
    ) -> QuerySet:
        from django.contrib.postgres.search import SearchRank, TrigramSimilarity

        ts_query = self.build_ts_query(query)

        # Content match: the whole query against any of the vector columns.
        # `search_vector=<SearchQuery>` uses SearchVectorField's registered
        # `exact` lookup (SearchVectorExact), which emits `search_vector @@ q`
        # and is what the GIN index can serve.
        #
        # `websearch_to_tsquery` ANDs its terms, so this one predicate already
        # enforces "every token must be accounted for" -- including tokens that
        # name the author or owner, because the triggers denormalise the handle
        # into the vector.
        vector_match = Q()
        for vector in spec.vectors:
            vector_match |= Q(**{vector: ts_query})

        # Typo tolerance for handles only. The whole query is the needle, so
        # this never widens a multi-word query to unrelated content: it either
        # finds a handle that looks like what was typed, or it does not.
        # `__trigram_similar` compiles to the `%` operator, and the server's
        # `similarity_threshold` (0.3 by default) decides what counts as a hit.
        fuzzy_handles = [
            column
            for column in spec.trigram
            if len(query) >= MIN_TRIGRAM_QUERY_LENGTH
        ]

        trigram_match = Q()
        for column in fuzzy_handles:
            trigram_match |= Q(**{f"{column}__trigram_similar": query})

        match = vector_match | trigram_match

        # Base relevance: the best rank across all vector columns, or the
        # trigram similarity, whichever is higher. Both land in roughly 0..1.
        score_parts = [
            SearchRank(F(vector), ts_query, normalization=RANK_NORMALIZATION)
            for vector in spec.vectors
        ]
        for column in fuzzy_handles:
            score_parts.append(TrigramSimilarity(column, query))

        if not score_parts:
            base_score = Value(0.0)
        elif len(score_parts) == 1:
            base_score = score_parts[0]
        else:
            base_score = Greatest(*score_parts)

        # `ts_rank` sums the weight of the matching lexemes and knows nothing
        # about where they sat in the document, so a post that merely mentions
        # "dancing" ties with one that is called "dancing". A whole-field or
        # word-initial match therefore gets a nudge, which is what actually
        # separates the two. Applied as an annotation rather than a filter so it
        # cannot push the planner off the GIN index scan.
        return queryset.filter(match).annotate(
            search_score=base_score + self._exactness_bonus(spec, query)
        )

    def _exactness_bonus(self, spec: SearchSpec, query: str) -> Case:
        exact = Q()
        prefix = Q()
        for field in spec.substring:
            exact |= Q(**{f"{field}__iexact": query})
            prefix |= Q(**{f"{field}__istartswith": query})

        return Case(
            When(exact, then=Value(EXACT_MATCH_BONUS)),
            When(prefix, then=Value(PREFIX_MATCH_BONUS)),
            default=Value(0.0),
            output_field=FloatField(),
        )


class PortableSubstringMatcher(BaseMatcher):
    """Case-insensitive substring matching that runs anywhere.

    Used on SQLite (the default test database) and as a safety net if the
    search triggers have not been applied to a PostgreSQL database. Slower than
    full-text -- `LIKE '%x%'` cannot use a btree index -- but it never depends
    on database state that might be missing.
    """

    engine = "portable_substring"

    def apply(
        self, queryset: QuerySet, *, spec: SearchSpec, query: str, tokens: list[str]
    ) -> QuerySet:
        fields = spec.substring
        if not fields:
            return queryset.none()

        phrase = " ".join(tokens)

        phrase_match = Q()
        for field in fields:
            phrase_match |= Q(**{f"{field}__icontains": phrase})

        match = Q()
        ranks = []
        for token in tokens:
            exact = Q()
            prefix = Q()
            contains = Q()
            for field in fields:
                exact |= Q(**{f"{field}__iexact": token})
                prefix |= Q(**{f"{field}__istartswith": token})
                contains |= Q(**{f"{field}__icontains": token})

            match &= contains
            ranks.append(
                Case(
                    When(exact, then=Value(RANK_EXACT)),
                    When(prefix, then=Value(RANK_PREFIX)),
                    default=Value(RANK_CONTAINS),
                    output_field=IntegerField(),
                )
            )

        # Best token = lowest bucket.
        tightness = ranks[0] if len(ranks) == 1 else Least(*ranks)
        phrase_tier = Case(
            When(phrase_match, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
        rank = phrase_tier * TIGHTNESS_BUCKETS + tightness

        # Flip to "higher is better" so both engines report a comparable score.
        return queryset.filter(match).annotate(
            search_score=Value(float(RANK_WORST), output_field=models.FloatField()) - rank
        )


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------

# Postgres is only used when the triggers are actually installed. A database
# where the search migrations have not been run has NULL vectors, and
# `search_vector @@ query` would match nothing at all -- a silent total search
# failure, which is precisely how this feature was broken before.
#
# Every trigger is checked, not just one. Each searchable type has its own
# vector, so a partially-migrated database would keep serving user results while
# posts, comments, media and collections quietly returned nothing.
REQUIRED_SEARCH_TRIGGERS = (
    "accounts_user_search_vector_trigger",
    "profiles_profile_search_vector_trigger",
    "social_post_search_vector_trigger",
    "social_comment_search_vector_trigger",
    "media_media_search_vector_trigger",
    "media_collection_search_vector_trigger",
)

_fts_available: dict[str, bool] = {}


def postgres_fulltext_ready(alias: str = "default") -> bool:
    if connection.vendor != "postgresql":
        return False
    if alias in _fts_available:
        return _fts_available[alias]
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(DISTINCT tgname) FROM pg_trigger
                WHERE tgname = ANY(%s) AND NOT tgisinternal
                """,
                [list(REQUIRED_SEARCH_TRIGGERS)],
            )
            installed = cursor.fetchone()[0]
        ready = installed == len(REQUIRED_SEARCH_TRIGGERS)
    except Exception:
        ready = False
    _fts_available[alias] = ready
    return ready


def reset_fulltext_probe() -> None:
    """Forget the cached capability probe (used by tests)."""
    _fts_available.clear()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SearchService:
    """Cross-type search over users, posts, comments, media and collections.

    Two interchangeable matchers sit behind one interface: PostgreSQL
    full-text when the search triggers are installed, and a portable substring
    matcher otherwise. Everything around them -- visibility scoping, filters,
    facet counts, cross-type interleaving, pagination -- is shared.
    """

    def search(
        self,
        *,
        query: str,
        types: list[str] | None = None,
        media_type: str | None = None,
        date_from: Any = None,
        date_to: Any = None,
        sort: str = "relevance",
        page: int = 1,
        page_size: int = 20,
        user: User | None = None,
    ) -> SearchResult:
        query = (query or "").strip()
        tokens = [token for token in query.split() if token]

        if len(query) < MIN_QUERY_LENGTH or not tokens:
            raise ValidationError(
                f"Search query must be at least {MIN_QUERY_LENGTH} characters long.",
                code="query_too_short",
            )

        selected_types = self._resolve_types(types)
        if media_type:
            media_type = self._resolve_media_type(media_type)
        if sort not in ("relevance", "recent"):
            raise ValidationError(
                "sort must be either 'relevance' or 'recent'.", code="invalid_sort",
            )

        # A media_type filter is meaningless without the media type selected,
        # and asking for it on a narrowed query is a client mistake worth
        # surfacing rather than silently returning nothing.
        if media_type and SearchType.MEDIA.value not in selected_types:
            raise ValidationError(
                "media_type requires the 'media' type to be selected.",
                code="invalid_filter_combination",
            )

        matcher = self._build_matcher(query)
        window = min((page * page_size) or page_size, MAX_WINDOW_PER_TYPE)

        scored_by_type: dict[str, list[ScoredResult]] = {}
        facets: list[dict[str, Any]] = []
        total = 0

        for search_type_value in selected_types:
            search_type = SearchType.from_value(search_type_value)
            spec = SEARCH_SPECS[search_type.value]
            queryset = self._base_queryset(search_type, user=user)
            if queryset is None:
                continue

            queryset = self._apply_scope(queryset, search_type, user=user)
            queryset = self._apply_common_filters(
                queryset,
                media_type=media_type if search_type is SearchType.MEDIA else None,
                date_from=date_from,
                date_to=date_to,
            )
            queryset = matcher.apply(queryset, spec=spec, query=query, tokens=tokens)

            count = queryset.count()
            facets.append(
                {"type": search_type.value, "label": search_type.value.title(), "count": count}
            )
            total += count

            if count:
                scored_by_type[search_type.value] = self._fetch_window(
                    queryset, search_type.value, window, sort=sort
                )

        merged = self._merge(scored_by_type, sort=sort)
        offset = (page - 1) * page_size
        results = merged[offset:offset + page_size]

        total_pages = (total + page_size - 1) // page_size if page_size else 0

        return SearchResult(
            query=query,
            tokens=tokens,
            results=results,
            facets=facets,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
            applied_filters={
                "types": list(selected_types),
                "media_type": media_type,
                "date_from": self._isoformat(date_from),
                "date_to": self._isoformat(date_to),
                "sort": sort,
            },
            engine=matcher.engine,
        )

    # ---- matcher selection -------------------------------------------------

    def _build_matcher(self, query: str) -> BaseMatcher:
        if not postgres_fulltext_ready():
            return PortableSubstringMatcher()

        fts = PostgresFullTextMatcher()
        # Stopword-only or punctuation-only queries produce an empty tsquery,
        # which matches nothing at all. Fall back so they still behave like the
        # substring matcher.
        if fts.ts_query_is_empty(query):
            return PortableSubstringMatcher()
        return fts

    # ---- type resolution ---------------------------------------------------

    def _resolve_types(self, types: list[str] | None) -> list[str]:
        """Validate the `types` filter, defaulting to every searchable type."""
        if not types:
            return SearchType.values()

        resolved: list[str] = []
        unknown: list[str] = []
        for raw in types:
            candidate = str(raw).strip().lower()
            if not candidate:
                continue
            if candidate not in SearchType.values():
                unknown.append(candidate)
            elif candidate not in resolved:
                resolved.append(candidate)

        if unknown:
            raise ValidationError(
                f"Unknown search type(s): {', '.join(sorted(unknown))}. "
                f"Valid types are: {', '.join(SearchType.values())}.",
                code="invalid_search_type",
            )
        if not resolved:
            raise ValidationError(
                "At least one search type must be selected.", code="empty_search_type",
            )
        return resolved

    def _resolve_media_type(self, media_type: str) -> str:
        candidate = str(media_type).strip().lower()
        if candidate not in [member.value for member in MediaType]:
            raise ValidationError(
                f"Invalid media_type '{candidate}'. "
                f"Valid values are: {', '.join(m.value for m in MediaType)}.",
                code="invalid_media_type",
            )
        return candidate

    # ---- queryset construction ---------------------------------------------

    def _base_queryset(self, search_type: SearchType, *, user: User | None) -> QuerySet | None:
        """Unfiltered, un-joined base queryset with the right select_related.

        Post and comment results carry an `is_liked` flag, which the shared
        serializers read as an attribute -- so it has to be annotated here or
        serialisation raises AttributeError.
        """
        viewer = user if (user is not None and user.is_authenticated) else None

        if search_type is SearchType.USERS:
            return User.objects.select_related("profile__avatar", "profile__cover_photo")
        if search_type is SearchType.POSTS:
            queryset = Post.objects.select_related(
                "author", "author__profile__avatar", "reshare_of"
            ).prefetch_related("attachments__media")
            return self._annotate_is_liked(queryset, Post, viewer)
        if search_type is SearchType.COMMENTS:
            queryset = Comment.objects.select_related(
                "author", "author__profile__avatar", "post", "post__author"
            )
            return self._annotate_is_liked(queryset, Comment, viewer)
        if search_type is SearchType.MEDIA:
            return Media.objects.select_related("owner", "owner__profile__avatar")
        if search_type is SearchType.COLLECTIONS:
            return Collection.objects.select_related(
                "owner", "owner__profile__avatar", "cover_media"
            )
        return None

    def _annotate_is_liked(
        self, queryset: QuerySet, model, viewer: User | None
    ) -> QuerySet:
        """Annotate `is_liked` for a model that can be a Like target."""
        if viewer is None:
            return queryset.annotate(is_liked=Value(False, output_field=BooleanField()))
        content_type = ContentType.objects.get_for_model(model)
        return queryset.annotate(
            is_liked=Exists(
                Like.objects.filter(
                    user_id=viewer.id,
                    content_type=content_type,
                    object_id=OuterRef("pk"),
                )
            )
        )

    def _apply_scope(
        self, queryset: QuerySet, search_type: SearchType, *, user: User | None
    ) -> QuerySet:
        """Hide soft-deleted rows and anything the viewer may not see.

        Visibility rules mirror the rest of the API: own rows are always
        visible, other people's rows only when public (posts) or when the
        viewer is in the audience (followers-only posts, private media).
        """
        viewer = user if (user is not None and user.is_authenticated) else None
        viewer_id = viewer.id if viewer is not None else None

        if search_type is SearchType.USERS:
            return queryset.filter(is_active=True, is_deleted=False)

        if search_type is SearchType.POSTS:
            queryset = queryset.filter(is_deleted=False)
            if viewer_id is None:
                return queryset.filter(visibility=PostVisibility.PUBLIC.value)
            # Public posts, your own posts, or followers-only posts from
            # accounts you have an accepted follow edge with. Private posts
            # stay author-only.
            return queryset.filter(
                Q(visibility=PostVisibility.PUBLIC.value)
                | Q(author_id=viewer_id)
                | (
                    Q(visibility=PostVisibility.FOLLOWERS.value)
                    & self._following_filter(viewer_id, "author_id")
                )
            )

        if search_type is SearchType.COMMENTS:
            # A comment is only as visible as the post it hangs off.
            queryset = queryset.filter(
                is_deleted=False,
                post__is_deleted=False,
                post__visibility=PostVisibility.PUBLIC.value,
            )
            if viewer_id is not None:
                queryset = queryset.filter(
                    Q(post__author_id=viewer_id) | Q(author_id=viewer_id)
                )
            return queryset

        if search_type is SearchType.MEDIA:
            queryset = queryset.filter(is_deleted=False)
            if viewer_id is None:
                return queryset.filter(visibility=MediaVisibility.PUBLIC.value)
            return queryset.filter(
                Q(visibility=MediaVisibility.PUBLIC.value) | Q(owner_id=viewer_id)
            )

        if search_type is SearchType.COLLECTIONS:
            queryset = queryset.filter(is_deleted=False)
            if viewer_id is None:
                return queryset.filter(is_public=True)
            return queryset.filter(Q(is_public=True) | Q(owner_id=viewer_id))

        return queryset

    def _following_filter(self, viewer_id, target_field: str) -> Q:
        """Q matching rows whose `target_field` the viewer has accepted-follow."""
        if viewer_id is None:
            return Q(pk__in=[])
        following_ids = Follow.objects.filter(
            follower_id=viewer_id,
            following_id__isnull=False,
            status=FollowStatus.ACCEPTED.value,
        ).values("following_id")
        return Q(**{f"{target_field}__in": following_ids})

    def _apply_common_filters(
        self,
        queryset: QuerySet,
        *,
        media_type: str | None,
        date_from: Any,
        date_to: Any,
    ) -> QuerySet:
        if media_type:
            queryset = queryset.filter(media_type=media_type)
        if date_from:
            queryset = queryset.filter(created_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__lte=date_to)
        return queryset

    # ---- windowing, merging ------------------------------------------------

    def _fetch_window(
        self, queryset: QuerySet, search_type: str, window: int, *, sort: str
    ) -> list[ScoredResult]:
        if sort == "recent":
            ordering = ["-created_at"]
        else:
            ordering = ["-search_score", "-created_at"]

        rows = list(queryset.order_by(*ordering)[:window])
        return [
            ScoredResult(
                type=search_type,
                item=row,
                score=float(getattr(row, "search_score", 0.0) or 0.0),
                created_at=row.created_at,
            )
            for row in rows
        ]

    def _merge(
        self, scored_by_type: dict[str, list[ScoredResult]], *, sort: str
    ) -> list[ScoredResult]:
        """Interleave types so one chatty type cannot monopolise the page.

        `sort=recent` is an explicit request for pure recency, so it is applied
        globally. Otherwise each type keeps its own relevance ordering and the
        types are alternated: the best post, then the best user, then the second
        best post, and so on.

        Comparing raw scores across types is not meaningful anyway -- each type
        has its own vector, its own document lengths and its own normalisation
        -- so interleaving is both fairer and more predictable than a global
        score sort, which would put one type's weakest hit ahead of another
        type's strongest.
        """
        if sort == "recent":
            merged = [hit for hits in scored_by_type.values() for hit in hits]
            merged.sort(key=lambda hit: hit.created_at, reverse=True)
            return merged
        return self._round_robin(list(scored_by_type.values()))

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _isoformat(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)


    def _round_robin(self, columns: list[list[ScoredResult]]) -> list[ScoredResult]:
        """Take one hit from each column per pass, until every column is drained.

        Each column arrives already ordered by score then recency, so this
        preserves per-type relevance while keeping the page balanced.
        """
        ordered: list[ScoredResult] = []
        index = 0
        total = sum(len(column) for column in columns)
        while len(ordered) < total:
            for column in columns:
                if index < len(column):
                    ordered.append(column[index])
            index += 1
        return ordered
