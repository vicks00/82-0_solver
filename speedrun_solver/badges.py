from __future__ import annotations

from .models import Card

# Presentation-only player identity badges. These do not participate in
# ranking, simulation, position assignment, or any policy decision. A player
# only receives one when this specific team/era card is graded S or S+.
# Player nicknames are shown for notable players on any card tier. The elite
# emblem table below controls the emoji, so lower-tier cards never receive one.
PLAYER_NICKNAMES = {
    "Allen Iverson": "THE ANSWER",
    "Anthony Davis": "THE BROW",
    "Bill Russell": "RINGS",
    "Bob McAdoo": "MAC",
    "Bob Pettit": "BIG BLUE",
    "Charles Barkley": "SIR CHARLES",
    "Chris Bosh": "CB4",
    "Chris Paul": "CP3",
    "Chris Webber": "C-WEBB",
    "Clyde Drexler": "CLYDE THE GLIDE",
    "Damian Lillard": "DAME TIME",
    "David Robinson": "THE ADMIRAL",
    "DeMarcus Cousins": "BOOGIE",
    "Dennis Rodman": "THE WORM",
    "Dirk Nowitzki": "THE GERMAN",
    "Dwyane Wade": "FLASH",
    "Elgin Baylor": "RABBIT",
    "Gary Payton": "THE GLOVE",
    "George Gervin": "THE ICE MAN",
    "Giannis Antetokounmpo": "GREEK FREAK",
    "Grant Hill": "HILL",
    "Hakeem Olajuwon": "THE DREAM",
    "Isiah Thomas": "Zeke",
    "Ja Morant": "JA",
    "James Harden": "THE BEARD",
    "Jason Kidd": "J-KIDD",
    "Jayson Tatum": "DEUCE",
    "Jerry West": "MR. CLUTCH",
    "Joel Embiid": "THE PROCESS",
    "Julius Erving": "DR. J",
    "Kareem Abdul-Jabbar": "SKYHOOK",
    "Karl Malone": "THE MAILMAN",
    "Kevin Durant": "SLIM REAPER",
    "Kevin Garnett": "THE BIG TICKET",
    "Kevin McHale": "THE BLACK HOLE",
    "Kobe Bryant": "MAMBA",
    "Kyrie Irving": "UNCLE DREW",
    "Larry Bird": "LARRY LEGEND",
    "LeBron James": "KING",
    "Luka Dončić": "LUKA MAGIC",
    "Magic Johnson": "MAGIC",
    "Manu Ginóbili": "MANU",
    "Moses Malone": "CHAIRMAN OF THE BOARDS",
    "Nate Thurmond": "NATE THE GREAT",
    "Nikola Jokić": "JOKER",
    "Oscar Robertson": "THE BIG O",
    "Patrick Ewing": "THE PATRICK",
    "Paul Pierce": "THE TRUTH",
    "Pete Maravich": "PISTOL PETE",
    "Ray Allen": "JESUS SHUTTLESWORTH",
    "Reggie Miller": "MILLER TIME",
    "Russell Westbrook": "BRODIE",
    "Scottie Pippen": "PIP",
    "Shaquille O'Neal": "DIESEL",
    "Stephen Curry": "CHEF",
    "Steve Nash": "NASH",
    "Tim Duncan": "THE BIG FUNDAMENTAL",
    "Tracy McGrady": "T-MAC",
    "Victor Wembanyama": "THE ALIEN",
    "Vince Carter": "VINSANITY",
    "Walt Frazier": "CLYDE",
    "Wilt Chamberlain": "THE STILT",
}

S_TIER_EMBLEMS = {
    "Wilt Chamberlain": "🛸",
    "Kareem Abdul-Jabbar": "🪝",
    "Nikola Jokić": "🃏",
    "Giannis Antetokounmpo": "🦌",
    "Russell Westbrook": "⚡",
    "Luka Dončić": "🎮",
    "Bob McAdoo": "🦬",
    "Michael Jordan": "🐐",
    "Hakeem Olajuwon": "🌀",
    "LeBron James": "👑",
    "David Robinson": "⚓",
    "DeMarcus Cousins": "🦍",
    "Kevin Garnett": "🐺",
    "Moses Malone": "💪",
    "Shaquille O'Neal": "🧱",
    "Nate Thurmond": "🌉",
    "Victor Wembanyama": "👽",
    "James Harden": "🧔",
    "Anthony Davis": "🪶",
    "Bob Pettit": "🔵",
    "Larry Bird": "🦅",
    "Chris Webber": "🕸️",
    "Oscar Robertson": "📽️",
    "Bill Russell": "💍",
}

ELITE_TIERS = {"S+", "S"}
FLEX_TIERS = {"S+", "S", "A+", "A"}


def player_badges(card: Card) -> list[dict[str, str]]:
    badges: list[dict[str, str]] = []
    nickname = PLAYER_NICKNAMES.get(card.player)
    elite_emblem = S_TIER_EMBLEMS.get(card.player)
    if elite_emblem and card.tier in ELITE_TIERS:
        badges.append(
            {
                "kind": "identity",
                "icon": elite_emblem,
                "label": nickname or "S-TIER",
            }
        )
    elif nickname:
        badges.append({"kind": "nickname", "icon": "", "label": nickname})
    if card.tier in FLEX_TIERS and len(card.positions) >= 3:
        position_count = len(card.positions)
        gem = {
            3: ("🔹", "3-position versatility"),
            4: ("🔷", "4-position versatility"),
            5: ("💎", "5-position versatility"),
        }.get(position_count)
        if gem is None:
            return badges
        icon, label = gem
        badges.append(
            {
                "kind": "flex",
                "icon": icon,
                "label": label,
            }
        )
    return badges
