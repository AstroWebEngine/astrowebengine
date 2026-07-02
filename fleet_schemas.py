from pydantic import BaseModel
from typing import Optional

class BuildShipRequest(BaseModel):
    base_id: int
    ship_type: str
    count: int
    fast_production: bool = False

class FleetSend(BaseModel):
    fleet_id: int
    destination_planet_id: int | None = None
    destination_coords: str | None = None  # "A01:23:05:02" format
    ships: dict[str, int] | None = None   # partial send: {ship_type: count}. None = send all.
    use_jump_gate: bool = False            # player must opt-in to use Jump Gate
    use_wormhole: bool = False             # player must opt-in to use Wormhole

class FleetAttack(BaseModel):
    fleet_id: int
    target_user_id: Optional[int] = None
    target_fleet_id: Optional[int] = None
    attack_mode: Optional[str] = None

class ColonizeRequest(BaseModel):
    fleet_id: int
    planet_id: int


