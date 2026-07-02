"""
Player gameplay endpoints for AstroWebEngine — Route orchestrator.
Registers all player-facing route modules.
"""

from routes_bases import register_bases_routes
from routes_research import register_research_routes
from routes_fleets import register_fleet_routes
from routes_trade import register_trade_routes
from routes_social import register_social_routes


def register_player_routes(app):
    """Register all player gameplay endpoints via sub-modules."""
    register_bases_routes(app)
    register_research_routes(app)
    register_fleet_routes(app)
    register_trade_routes(app)
    register_social_routes(app)
