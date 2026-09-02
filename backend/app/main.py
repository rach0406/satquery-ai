"""SatQuery AI - FastAPI application entrypoint.

    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .api.routes_auth import router as auth_router
from .config import settings
from .utils.render import artifacts_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("satquery")

DESCRIPTION = """
**SatQuery AI** - an agentic vision-language assistant for multimodal remote-sensing
analysis through natural-language queries.

*Smart India Hackathon 2026 - problem statement SIH26167 (ISRO / Department of Space).
Team Avengers.*

### The one rule

Every number this API returns was **measured from real satellite pixels**. The language
model, when configured, parses the question and phrases the narration - it never
produces a measurement. Each numeral in the generated text is matched back to a fact in
the request's fact store before it is shown, and any unmatched numeral causes the
narration to be discarded in favour of the deterministic template.

When the archive has no usable observation, the API says so and returns `status:
"no_data"`. It does not estimate.

### Pipeline

`parse → validate → acquire → select tools → execute → ground → narrate`
"""

app = FastAPI(
    title=f"{settings.app_name} API",
    description=DESCRIPTION,
    version=settings.version,
    contact={"name": f"Team {settings.team}", "url": "https://sih.gov.in"},
    license_info={"name": "MIT"},
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins if o.strip()] or ["*"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Error shape
# --------------------------------------------------------------------------
# The console reads `detail` from every failed response and shows it verbatim.
# FastAPI's defaults break that in two places: a validation failure returns
# `detail` as a *list of objects* (which renders as "[object Object]"), and an
# unhandled exception returns Starlette's plain-text "Internal Server Error"
# with no JSON body at all - which is exactly what a user sees as a mysterious
# "Internal Error" on the sign-in screen. Both are normalised to one sentence.
def _humanise(err: dict) -> str:
    loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
    field = " → ".join(loc) or "request"
    return f"{field}: {err.get('msg', 'is invalid')}"


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    problems = [_humanise(e) for e in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"detail": "; ".join(problems) or "The request body was not valid.",
                 "problems": problems},
    )


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}".strip()[:400] or
                 "The server hit an unexpected error.",
                 "path": request.url.path},
    )


app.include_router(auth_router, prefix="/api")
app.include_router(router, prefix="/api")

# Rendered overlays and charts are served statically so the JSON stays small.
app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir())), name="artifacts")

# The built frontend, when present, is served from the same origin.
#
# The console is a single-page app: "/", "/login" and "/app" are client-side
# routes with no file behind them, so a deep link or a page refresh has to be
# answered with index.html and resolved in the browser. Hashed build assets are
# mounted normally; everything else that is not an API path falls through to
# the shell below.
_dist = settings.project_root / "frontend" / "dist"
_index = _dist / "index.html"
#: Paths owned by the server. A miss under these must 404 as itself rather
#: than quietly returning the SPA shell, which would turn a typo'd endpoint
#: into a confusing block of HTML.
_SERVER_PREFIXES = ("api", "artifacts", "docs", "redoc", "openapi.json")

if _dist.exists():
    if (_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")


@app.get("/", include_in_schema=False)
def root():
    if _index.exists():
        return FileResponse(str(_index))
    return RedirectResponse("/docs")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Serve a built file when one exists, otherwise the SPA shell."""
    if not _index.exists():
        raise HTTPException(status_code=404, detail="Not found")
    head = full_path.split("/", 1)[0]
    if head in _SERVER_PREFIXES:
        raise HTTPException(status_code=404, detail=f"No such endpoint: /{full_path}")

    # A real file (favicon, robots.txt, ...) wins over the shell. resolve()
    # keeps "../" out of the dist directory.
    candidate = (_dist / full_path).resolve()
    if candidate.is_file() and _dist.resolve() in candidate.parents:
        return FileResponse(str(candidate))
    return FileResponse(str(_index))


@app.on_event("startup")
def _startup() -> None:
    from .auth import get_store
    from .ml import classifier

    settings.ensure_dirs()
    store = get_store()
    info = classifier.model_info()
    log.info("%s v%s  (%s, team %s)", settings.app_name, settings.version,
             settings.problem_statement, settings.team)
    log.info("data dir      : %s", settings.data_dir)
    log.info("LLM           : %s", settings.llm_model if settings.llm_available
             else "not configured - rule parser and template narrator in use")
    log.info("RS classifier : %s", (
        f"{info['name']} ready, held-out accuracy "
        f"{(info['test_accuracy'] or 0) * 100:.2f}%" if info["available"]
        else f"NOT TRAINED ({info['error']})"))
    log.info("grounding     : strict=%s tolerance=%.3f",
             settings.strict_grounding, settings.numeric_tolerance)
    log.info("auth          : %d account(s), API enforcement %s",
             store.count(), "ON" if settings.require_auth else "off (console still gates)")
    log.info("docs          : http://%s:%s/docs", settings.host, settings.port)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
