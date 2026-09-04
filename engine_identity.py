"""
AstroWebEngine identity & attribution.

AstroWebEngine (AWE) is an open game engine, licensed under the AGPL-3.0. This
module is the single source of truth for the engine's identity, surfaced in
four places:

  * GET /api/engine                  — machine-readable identity
  * GET /.well-known/astrowebengine  — discovery path (curl any deployment)
  * X-Powered-By response header     — visible in devtools / `curl -I`
  * the UI footer ("Powered by AstroWebEngine")

Keeping these is a courtesy, not a license term: the AGPL asks you to pass on
the source, not the credit. They exist so an AWE-powered game is trivially
identifiable, so the optional public registry can verify that a listing is
genuinely AWE, and so operators can tell at a glance which engine version a
deployment is running.
"""

ENGINE_NAME = "AstroWebEngine"
ENGINE_SHORT = "AWE"
ENGINE_HOMEPAGE = "https://astrowebengine.com"
ENGINE_ATTRIBUTION = "Powered by AstroWebEngine"
ENGINE_LICENSE = "AGPL-3.0-or-later"
ENGINE_LICENSE_NOTICE = (
    "AstroWebEngine is free software under the AGPL-3.0. If you modify it and "
    "let others use it over a network, they are entitled to your modified source."
)


def engine_identity(version: str = "unknown") -> dict:
    """Return the canonical engine-identity payload served at /api/engine."""
    return {
        "engine": ENGINE_NAME,
        "short": ENGINE_SHORT,
        "version": version,
        "url": ENGINE_HOMEPAGE,
        "attribution": ENGINE_ATTRIBUTION,
        "license": ENGINE_LICENSE,
        "notice": ENGINE_LICENSE_NOTICE,
    }
