"""
api_request_identity.py — PURE request-identity + payload-containment helpers.

WHY THIS FILE EXISTS
--------------------
AlienEdge's global API cache (api_cache.py / smart_get) is allowed to answer a
NARROWER request from a cached SUPERSET response, so that Engine A / Engine B /
Engine C all asking for the same SportMonks resource end up producing ONE API
call instead of three. That optimisation is only ever safe if "the cached
response demonstrably contains everything the narrower request needs".

This module holds that decision as pure, dependency-free functions so there is
exactly ONE implementation of the safety rules, shared by:
  * api_cache.py             (in-memory response cache aliasing)
  * shared_fixture_window.py (canonical 7-day future-fixture store aliasing)

A narrower request may reuse a superset ONLY when ALL of the following match:
  1. the same normalised resource path   (so /fixtures/date/2026-09-19 never
                                          serves /fixtures/date/2026-09-20)
  2. identical identity parameters       (page, per_page, filters, sortBy,
                                          order, and every other param except
                                          include / exclude / api_token)
  3. the cached `include` set COVERS every requested include path
  4. the cached `exclude` set excludes at least as much as the request asks
  5. the response page number is the requested page number
  6. structural containment: every requested relation path is actually present
     on every item of the payload (an include string alone is never trusted).

`include` coverage is deliberately strict: a cached `include=statistics` does
NOT cover a request for `statistics.type` (the nested relation may be absent),
while a cached `include=statistics.type` DOES cover `statistics`.

No third-party imports, no repo imports, no side effects.
"""

# ── include / exclude parsing ────────────────────────────────────────────────

def include_set(params):
    """{'participants', 'league', ...} from params['include']."""
    raw = (params or {}).get("include") or ""
    return {p.strip() for p in str(raw).split(";") if p.strip()}


def exclude_set(params):
    """{'lineups', ...} from params['exclude'] (empty when absent)."""
    raw = (params or {}).get("exclude") or ""
    return {p.strip() for p in str(raw).split(";") if p.strip()}


def covers_includes(cached_include, wanted_include):
    """True when `cached_include` (a set) satisfies every path in `wanted_include`.

    A cached path covers the requested path only when it IS the requested path
    or a DEEPER dotted path below it:
        cached {'participants', 'league', 'season'} covers {'participants'}   OK
        cached {'statistics.type'}                   covers {'statistics'}   OK
        cached {'statistics'}                        covers {'statistics.type'}  NOT ok
    """
    want = set(wanted_include or ())
    if not want:
        return True                      # a bare request needs no relations
    cached = set(cached_include or ())
    for w in want:
        if not any(c == w or c.startswith(w + ".") for c in cached):
            return False
    return True


def excludes_satisfy(cached_exclude, wanted_exclude):
    """True when the cached response excluded AT LEAST what the request excludes.

    Serving a payload that excluded less than the caller asked for would hand
    the caller relations it deliberately removed, so that is never aliased.
    """
    return set(cached_exclude or ()) >= set(wanted_exclude or ())


# ── request identity ────────────────────────────────────────────────────────

# Parameters that are NOT part of request identity:
#   api_token  — credentials, never cached and never part of equality
#   include    — handled by the coverage rules (a superset is allowed)
#   exclude    — handled by excludes_satisfy()
_NON_IDENTITY_PARAMS = {"api_token", "include", "exclude"}


def identity(params):
    """Hashable identity of a request: every param except api_token/include/exclude.

    Two requests are the same resource ONLY when their identities are equal —
    this is what stops 'page 2' being served from a cached 'page 1', or a
    filtered call (filters=fixtureStates:5) being served from an unfiltered one.
    """
    items = []
    for k, v in (params or {}).items():
        if k in _NON_IDENTITY_PARAMS:
            continue
        items.append((str(k), "" if v is None else str(v)))
    return tuple(sorted(items))


def request_path(url):
    """Normalised SportMonks path for a URL, without query string.

    'https://api.sportmonks.com/v3/football/fixtures/date/2026-09-19?x=1'
        -> '/fixtures/date/2026-09-19'
    """
    u = str(url or "").split("?", 1)[0].rstrip("/")
    marker = "/football/"
    i = u.find(marker)
    if i >= 0:
        return u[i + len("/football"):] or "/"
    return u


# ── payload containment ─────────────────────────────────────────────────────

def payload_items(body):
    """The list of resource items inside a SportMonks response body."""
    if isinstance(body, dict):
        items = body.get("data")
        return items if isinstance(items, list) else None
    return None


def contains_relation(node, parts):
    """True when the dotted relation `parts` is present inside `node`.

    * dict -> the next key must exist, then recurse into its value
    * list -> every element must contain the remaining relation
              (an EMPTY list is treated as present-but-empty: pre-match future
               fixtures legitimately carry empty scores/lineups/statistics)
    """
    if not parts:
        return True
    key, rest = parts[0], parts[1:]
    if isinstance(node, dict):
        if key not in node:
            return False
        return contains_relation(node[key], rest)
    if isinstance(node, list):
        if not node:
            return True
        return all(contains_relation(el, parts) for el in node)
    return False


def response_page(body, params):
    """The page number a response body represents, as a string ('1' default).

    SportMonks v3 puts pagination at the TOP level of the body
    (`{"data": [...], "pagination": {"current_page": ...}}`). When a provider
    omits it, page 1 is assumed — and `page_matches` below then refuses to
    alias anything that explicitly asked for a later page.
    """
    pag = body.get("pagination") if isinstance(body, dict) else None
    if isinstance(pag, dict) and pag.get("current_page") is not None:
        return str(pag.get("current_page"))
    return "1"


def requested_page(params):
    """The page number the caller asked for, as a string ('1' default)."""
    raw = (params or {}).get("page")
    return "1" if raw in (None, "") else str(raw)


def page_matches(body, cached_params, wanted_params):
    """True when the cached body IS the page the caller asked for.

    Both sides are checked: the caller's requested page must equal the page
    this body represents, and it must also equal the page implied by the
    cached request's own parameters (guards against a payload cached under a
    mismatched params dict).
    """
    return (response_page(body, wanted_params) == requested_page(wanted_params)
            and response_page(body, cached_params) == requested_page(wanted_params))


def request_can_be_served(body, cached_params, path, wanted_params,
                          cached_path=None):
    """The single safety gate: may `body` answer this request?

    `cached_path` defaults to `path` (in-memory alias reads the cached request's
    own recorded path). Returns (ok, reason) so callers can report WHY an alias
    was refused instead of silently missing.
    """
    if body is None:
        return False, "no cached body"
    if (cached_path if cached_path is not None else path) != path:
        return False, "different resource path"
    if identity(cached_params) != identity(wanted_params):
        return False, "identity params differ"
    if not covers_includes(include_set(cached_params), include_set(wanted_params)):
        return False, "cached include is not a superset"
    if not excludes_satisfy(exclude_set(cached_params), exclude_set(wanted_params)):
        return False, "cached exclude is narrower than requested"
    if not page_matches(body, cached_params, wanted_params):
        return False, "page mismatch"
    items = payload_items(body)
    if items is None:
        return False, "payload has no data list"
    for rel in include_set(wanted_params):
        parts = rel.split(".")
        for item in items:
            if not contains_relation(item, parts):
                return False, f"relation '{rel}' missing from payload"
    return True, "safe superset"