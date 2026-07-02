"""
AstroWebEngine identity & attribution.

AstroWebEngine (AWE) is an open game engine. Games built on it must preserve
the "Powered by AstroWebEngine" attribution per the project LICENSE. This
module is the single source of truth for the engine's identity. It is surfaced
in three places so an operator who strips one still leaves the others:

  * GET /api/engine                  — machine-readable identity
  * GET /.well-known/astrowebengine  — discovery path (curl any deployment)
  * X-Powered-By response header      — visible in devtools / `curl -I`
  * the UI footer ("Powered by AstroWebEngine")

None of these are tamper-proof against someone editing the source — that is
what the LICENSE attribution clause is for. They exist so an AWE-powered game
is trivially identifiable, and so removing the credit is a deliberate,
provable act rather than an accident.
"""

ENGINE_NAME = "AstroWebEngine"
ENGINE_SHORT = "AWE"
ENGINE_HOMEPAGE = "https://astrowebengine.com"
ENGINE_ATTRIBUTION = "Powered by AstroWebEngine"
ENGINE_LICENSE_NOTICE = "Attribution to AstroWebEngine is required by the engine license."


def engine_identity(version: str = "unknown") -> dict:
    """Return the canonical engine-identity payload served at /api/engine."""
    return {
        "engine": ENGINE_NAME,
        "short": ENGINE_SHORT,
        "version": version,
        "url": ENGINE_HOMEPAGE,
        "attribution": ENGINE_ATTRIBUTION,
        "notice": ENGINE_LICENSE_NOTICE,
    }
