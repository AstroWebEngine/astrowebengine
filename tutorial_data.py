"""
Tutorial step definitions for the AstroWebEngine.
Each step has: title, description text, mission(s), requirements, reward, and an optional flag.
Mission checks are keyed by type so the backend can auto-detect completion.
"""

TUTORIAL_STEPS = [
    # 0 — Introduction
    {
        "id": "introduction",
        "title": "Introduction",
        "description": (
            "Welcome to AstroWebEngine!\n\n"
            "Prepare to embark on an exciting journey as this interactive tutorial "
            "guides you through the fundamental steps to mastering the game.\n\n"
            "Let's get started! Good luck!"
        ),
        "mission": None,  # No mission — just a "Start the tutorial" button
        "requirements": [],
        "reward": 0,
    },
    # 1 — Base Structures
    {
        "id": "base_structures",
        "title": "Base Structures",
        "description": (
            "You begin with a single base, which you will start developing now.\n\n"
            "Let's build 2 Metal Refineries to increase your base economy and construction capacity.\n\n"
            "1) Enter the Bases menu.\n"
            "2) Click on the Structures tab.\n"
            "3) On the Metal Refineries row, click the Build button.\n\n"
            "Every construction will take a certain time. The game may seem a little slow at the "
            "beginning but it will get more intense as you build your empire."
        ),
        "mission": {
            "text": "Construct a level 2 Metal Refineries",
            "type": "building",
            "building_type": "metal_refineries",
            "target_level": 2,
        },
        "requirements": [],
        "reward": 5,
    },
    # 2 — Base Energy
    {
        "id": "base_energy",
        "title": "Base Energy",
        "description": (
            "Energy structures are one of the most important structures, without energy, "
            "you cannot expand your bases, as most structures require energy.\n\n"
            "Base structures have a energy value that denotes the amount of energy each level "
            "of the structure produces/consumes. For example, if that says +2, building one level "
            "will add 2 energy to your base.\n\n"
            "By now build the energy structure that has the higher positive number.\n\n"
            "Every time you need additional energy in your base you will need to build a energy structure."
        ),
        "mission": {
            "text": "Build 1 level of any energy structure",
            "type": "building_any_energy",
            "target_level": 1,  # at least 1 level of gas_plants or solar_plants (beyond starting)
        },
        "requirements": [],
        "reward": 5,
    },
    # 3 — Technologies
    {
        "id": "technologies",
        "title": "Technologies",
        "description": (
            "Technologies influence many different factors from increasing your bases capacity "
            "to improving your ships characteristics.\n\n"
            "To research technologies you need to build a Research Labs structure.\n\n"
            "Once you have a Research Labs, you can start researching.\n\n"
            "You can keep building structures at same time you research, for example you can keep "
            "upgrading your Metal Refineries while researching Energy.\n\n"
            "To research Energy:\n\n"
            "1) Enter the Bases menu.\n"
            "2) Click on the Research tab.\n"
            "3) On the Energy row press the Research button."
        ),
        "mission": {
            "text": "Research level 1 Energy technology",
            "type": "research",
            "tech_type": "energy",
            "target_level": 1,
        },
        "requirements": [
            {"text": "Construct a level 1 Research Labs", "type": "building", "building_type": "research_labs", "target_level": 1},
        ],
        "reward": 10,
    },
    # 4 — Base Population
    {
        "id": "base_population",
        "title": "Base Population",
        "description": (
            "Most structures require population, if you do not have the required population, "
            "then you cannot build the structure.\n\n"
            "The population boost of an Urban Structure is calculated off the astro's fertility "
            "that can be viewed on the astro's overview page. For example, if the astro has a "
            "fertility of 4, then each Urban Structure level will increase your base's population by 4.\n\n"
            "Every time you need additional population in your base you will need to upgrade "
            "your Urban Structures."
        ),
        "mission": {
            "text": "Construct a level 2 Urban Structures",
            "type": "building",
            "building_type": "urban_structures",
            "target_level": 2,
        },
        "requirements": [],
        "reward": 5,
    },
    # 5 — Weapons Technology
    {
        "id": "weapons_technology",
        "title": "Weapons Technology",
        "description": (
            "There are several weapons technologies, one of them is the Laser technology, "
            "required to build some defenses and units.\n\n"
            "Each level of Laser technology you research will increase the attack power by 5% "
            "of units or defenses that use Laser weapons.\n\n"
            "To research Laser, you must have 2 levels of Research Labs and have researched "
            "2 levels of Energy.\n\n"
            "To check the requirements for any given technology, you can refer yourself to the "
            "Tables link at the top of the screen."
        ),
        "mission": {
            "text": "Research level 1 Laser technology",
            "type": "research",
            "tech_type": "laser",
            "target_level": 1,
        },
        "requirements": [
            {"text": "Construct a level 2 Research Labs", "type": "building", "building_type": "research_labs", "target_level": 2},
            {"text": "Research level 2 Energy technology", "type": "research", "tech_type": "energy", "target_level": 2},
        ],
        "reward": 10,
    },
    # 6 — Combat Units
    {
        "id": "combat_units",
        "title": "Combat Units",
        "description": (
            "Units can be used to attack, defend or to scout. And unlike Defenses, units can be moved.\n\n"
            "But before you can produce ships you first need to build a Shipyards structure.\n\n"
            "Once you have a Shipyard you can start producing units. Just follow these steps:\n\n"
            "1) On your base page select the Production tab.\n"
            "2) Write the number 1 in the quantity box of the Fighters row.\n"
            "3) On the bottom of the page hit the Submit button.\n\n"
            "When units are produced they are placed on a new Fleet or an existent one.\n\n"
            "Since Fighters cannot be moved without a hangar ship, you don't need to worry about "
            "fleets just yet.\n\n"
            "Each unit have basic combat characteristics:\n"
            "Attack = amount of damage a unit deals when attacking or defending.\n"
            "Armour = amount of damage a unit can receive before being killed.\n"
            "Shield = amount of damage that is absorbed before hitting armour from each shot of enemy fire."
        ),
        "mission": {
            "text": "Produce 1 Fighter",
            "type": "ship",
            "ship_type": "fighters",
            "target_count": 1,
        },
        "requirements": [
            {"text": "Construct a level 1 Shipyards", "type": "building", "building_type": "shipyard", "target_level": 1},
        ],
        "reward": 10,
    },
    # 7 — Trade
    {
        "id": "trade",
        "title": "Trade",
        "description": (
            "Trading is an important element of the game as it increases your empire economy.\n"
            "The game's trade system is simple and consists in the creation of trade routes between bases.\n\n"
            "To create a trade route you need to have a Spaceports structure at your base.\n\n"
            "After you build the Spaceports you can create a trade route (while is not part of the "
            "mission is advisable to increase your economy).\n\n"
            "The trade route must have a destination. The destination can be of a base of other players "
            "close by. But is best you ask him if he want to set a trade route with you, as he/she will "
            "have to accept the trade route after you set it.\n\n"
            "Long distances trade routes have an increased cost but also provide more income, but for now "
            "its best you make a short range trade route to save credits.\n\n"
            "To start a new trade route:\n\n"
            "1) On your base page click on the Trade tab.\n"
            "2) Click on Set a new Trade Route.\n"
            "3) Fill the Destination field.\n"
            "4) You can check the profit with the button Calculate Profit.\n"
            "5) Click Start New Trade Route to start it.\n"
            "6) The other player will need to activate the route.\n\n"
            "You can get more information about trade routes in the Help section (link on top menu)."
        ),
        "mission": {
            "text": "Construct a level 1 Spaceports",
            "type": "building",
            "building_type": "spaceports",
            "target_level": 1,
        },
        "optional_mission": {
            "text": "Create 1 trade route",
            "type": "trade_route",
            "target_count": 1,
        },
        "requirements": [],
        "reward": 20,
    },
    # 8 — Stellar Drive
    {
        "id": "stellar_drive",
        "title": "Stellar Drive",
        "description": (
            "Stellar Drive technology allows you to build Stellar units that can travel to other astros.\n\n"
            "Each level of Stellar Drive technology also increases your stellar units travel speed by 5%."
        ),
        "mission": {
            "text": "Research level 1 Stellar Drive technology",
            "type": "research",
            "tech_type": "stellar_drive",
            "target_level": 1,
        },
        "requirements": [
            {"text": "Construct a level 5 Research Labs", "type": "building", "building_type": "research_labs", "target_level": 5},
            {"text": "Research level 6 Energy technology", "type": "research", "tech_type": "energy", "target_level": 6},
        ],
        "reward": 25,
    },
    # 9 — Moving Units
    {
        "id": "moving_units",
        "title": "Moving Units",
        "description": (
            "Stellar and Warp units can move between astros alone.\n\n"
            "In this mission we will produce a Corvette, and move it to a different location.\n\n"
            "After producing the Corvette lets move it, you should give a look first in the map "
            "around your base to select a location to move.\n\n"
            "To move the Corvette:\n\n"
            "1) On the Astro page where you want to move, select 'Move fleet here' button.\n"
            "2) Select the fleet that has the Corvette.\n"
            "3) Select the units to move.\n"
            "4) Click in the Move button.\n\n"
            "The fleet travel time is calculated dividing the fleet speed by the moving distance.\n"
            "The fleet speed is the lower unit speed in the fleet."
        ),
        "mission": {
            "text": "Build a Corvette and move it to a location outside your base(s)",
            "type": "move_fleet",
            "ship_type": "corvettes",
            "target_count": 1,
        },
        "requirements": [
            {"text": "Construct a level 4 Shipyards", "type": "building", "building_type": "shipyard", "target_level": 4},
            {"text": "Research level 1 Computer technology", "type": "research", "tech_type": "computer", "target_level": 1},
            {"text": "Research level 2 Armour technology", "type": "research", "tech_type": "armour", "target_level": 2},
            {"text": "Research level 2 Laser technology", "type": "research", "tech_type": "laser", "target_level": 2},
            {"text": "Produce 1 Corvette", "type": "ship", "ship_type": "corvettes", "target_count": 1},
        ],
        "reward": 25,
    },
    # 10 — Warp Drive
    {
        "id": "warp_drive",
        "title": "Warp Drive",
        "description": (
            "Warp Drive technology allows you to build Warp units, which can move between galaxies.\n\n"
            "Also each level of Warp Drive technology increases your Warp units travel speed by 5%."
        ),
        "mission": {
            "text": "Research level 1 Warp Drive technology",
            "type": "research",
            "tech_type": "warp_drive",
            "target_level": 1,
        },
        "requirements": [
            {"text": "Construct a level 8 Research Labs", "type": "building", "building_type": "research_labs", "target_level": 8},
            {"text": "Research level 8 Energy technology", "type": "research", "tech_type": "energy", "target_level": 8},
            {"text": "Research level 4 Stellar Drive technology", "type": "research", "tech_type": "stellar_drive", "target_level": 4},
        ],
        "reward": 50,
    },
    # 11 — Additional Bases
    {
        "id": "additional_bases",
        "title": "Additional Bases",
        "description": (
            "Additional bases will provide your empire with more economy, besides giving you more "
            "places to build fleets and research.\n\n"
            "To build an additional base you will need to use an Outpost Ship, so you need to produce it first.\n"
            "After producing the Outpost Ship you will need to move it to an empty Astro "
            "(planet, moon or asteroid) and select the Build Base tab in this fleet menu.\n\n"
            "The first additional base will have a setup cost of 100 credits and each additional base "
            "will have an increased setup cost."
        ),
        "mission": {
            "text": "Build a 2nd Base",
            "type": "colony_count",
            "target_count": 2,
        },
        "requirements": [
            {"text": "Construct a level 8 Shipyards", "type": "building", "building_type": "shipyard", "target_level": 8},
            {"text": "Produce 1 Outpost Ship", "type": "ship", "ship_type": "outpost_ships", "target_count": 1},
        ],
        "reward": 50,
    },
    # 12 — Base Defenses
    {
        "id": "base_defenses",
        "title": "Base Defenses",
        "description": (
            "Base defenses are stationary structures that automatically return fire against anyone "
            "who attacks your base. However, they are only used in defense, which means that you "
            "cannot attack fleets over your base with them.\n\n"
            "Once a defense is built, it will never be destroyed, even if your base is attacked. "
            "Instead, it will be reduced to 0% power. Once your base is no longer occupied, it will "
            "automatically regenerate 1% per hour until it is at 100%.\n\n"
            "To construct a defense:\n\n"
            "1) On your Base page go to the Defenses section, near the Structures.\n"
            "2) Select the defense to be built and click Build.\n\n"
            "Each level of one defense you build consists of 5 units."
        ),
        "mission": {
            "text": "Build one level of any defense",
            "type": "defense_any",
            "target_level": 1,
        },
        "requirements": [],
        "reward": 20,
    },
    # 13 — Command Centers
    {
        "id": "command_centers",
        "title": "Command Centers",
        "description": (
            "For each Command Center you have your fleets can occupy 1 base of another player.\n"
            "Also each Command Center increases your fleet attack power at the base by 5%.\n\n"
            "Command Center are a good structure to protect your base, especially helping you to "
            "free your bases in case of occupation."
        ),
        "mission": {
            "text": "Construct a level 1 Command Centers",
            "type": "building",
            "building_type": "command_centers",
            "target_level": 1,
        },
        "requirements": [
            {"text": "Research level 6 Computer technology", "type": "research", "tech_type": "computer", "target_level": 6},
        ],
        "reward": 20,
    },
    # 14 — Combat Fleets
    {
        "id": "combat_fleets",
        "title": "Combat Fleets",
        "description": (
            "Attacking others players' bases, pillaging the base, or plundering their trade routes "
            "are ways of get additional credits.\n\n"
            "You can also attack others players fleets and recycle the debris with Recyclers, "
            "to get credits. Each Recycler can collect 10 credits in debris per hour, at the "
            "half hour mark.\n\n"
            "There are lots of combat fleet configurations, we will build a small one in this mission "
            "composed of 1 Frigate and 4 Fighters, and moving it.\n\n"
            "When we have hangar units like Fighters, we need to transport those using bigger units "
            "with hangar spaces. If we produce 1 Frigate that has 4 hangar spaces, we will be able "
            "to move 4 Fighters.\n\n"
            "You can get more information about fleets and combats in the Help section (link on top menu)."
        ),
        "mission": {
            "text": "Move 1 Frigate with 4 Fighters to a location outside your bases",
            "type": "move_combat_fleet",
            "required_ships": {"frigates": 1, "fighters": 4},
        },
        "requirements": [
            {"text": "Research level 6 Missiles technology", "type": "research", "tech_type": "missiles", "target_level": 6},
            {"text": "Research level 8 Armour technology", "type": "research", "tech_type": "armour", "target_level": 8},
            {"text": "Produce 4 Fighters", "type": "ship", "ship_type": "fighters", "target_count": 4},
            {"text": "Produce 1 Frigate", "type": "ship", "ship_type": "frigates", "target_count": 1},
        ],
        "reward": 80,
    },
    # 15 — End Tutorial
    {
        "id": "end_tutorial",
        "title": "End Tutorial",
        "description": (
            "Congratulations! You have completed the tutorial.\n\n"
            "You now know the basics. Continue building your empire, "
            "forge alliances, and conquer the galaxy!\n\n"
            "Total tutorial rewards earned: 335 credits.\n\n"
            "Good luck, Commander!"
        ),
        "mission": None,
        "requirements": [],
        "reward": 0,
    },
]

# Quick lookup by step ID
TUTORIAL_STEP_MAP = {s["id"]: i for i, s in enumerate(TUTORIAL_STEPS)}
TOTAL_TUTORIAL_REWARDS = sum(s["reward"] for s in TUTORIAL_STEPS)  # 335
