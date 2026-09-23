from dataclasses import dataclass


@dataclass(frozen=True)
class UnitSpec:
    name: str
    coins: int
    help: str
    symbol: str
    expansion: str = "base"
    family: str | None = None


UNITS = {
    "swordsman": UnitSpec("剑士", 5, "攻击后若仍存活，可以移动一格。", "Sw"),
    "pikeman": UnitSpec("长枪兵", 4, "受到相邻单位攻击时，同时移除攻击者一枚币；自身被消灭也会触发。", "Pi"),
    "crossbowman": UnitSpec("弩手", 5, "战术：攻击直线两格外的敌军，中间必须无单位；也能普通近战。", "Cr"),
    "light_cavalry": UnitSpec("轻骑兵", 5, "战术：移动两格，每步均须为空格；也能普通移动一格。", "Li"),
    "archer": UnitSpec("弓箭手", 4, "只能用战术攻击距离恰为两格的敌军，可越过中间单位。", "Ar"),
    "cavalry": UnitSpec("骑兵", 4, "战术：移动一格，然后攻击相邻敌军。", "Ca"),
    "lancer": UnitSpec("枪骑兵", 4, "只能用战术攻击：沿直线移动一或两格，再攻击同方向相邻敌军。", "La"),
    "scout": UnitSpec("斥候", 5, "还可部署到任意友军相邻的空格。", "Sc"),
    "berserker": UnitSpec("狂战士", 5, "调遣后可从本单位移一枚增强币到弃牌堆，再调遣一次，可重复但不能移除最后一枚。", "Be"),
    "ensign": UnitSpec("旗手", 5, "战术：选择两格内友军，令其普通移动一格，终点仍须在旗手两格内。", "En"),
    "footman": UnitSpec("步兵", 5, "可同时部署两个单位。战术：每个步兵单位各执行一次调遣。", "Fo"),
    "knight": UnitSpec("骑士", 4, "只有获得增强的敌方单位（至少两枚币）才能攻击骑士。", "Kn"),
    "marshall": UnitSpec("元帅", 5, "战术：令两格内一支友军执行普通攻击，仍受兵种攻击限制。", "Ma"),
    "mercenary": UnitSpec("雇佣兵", 5, "招募雇佣兵后，已部署的雇佣兵可免费调遣一次。", "Me"),
    "royal_guard": UnitSpec("皇家卫队", 5, "战术：支付皇家币，移动最多两格到己方据点。受到攻击时可移除供应中的一枚币代替战场损失。", "Rg"),
    "warrior_priest": UnitSpec("战斗牧师", 4, "攻击或控制后，从袋中抽一枚币，立即用这枚币执行行动。", "Wp"),
}
BASE_UNITS = tuple(UNITS)
UNITS.update({
    "bannerman": UnitSpec("掌旗官", 4, "调遣后，可将相邻的一支敌军移动一格（不是调遣，不触发其移动技能）。", "Ba", "nobility"),
    "bishop": UnitSpec("主教", 5, "战术：招募一枚币，然后移动或攻击。不能被已增强的单位攻击。", "Bi", "nobility"),
    "earl": UnitSpec("伯爵", 5, "部署后可移动。战术：控制据点后免费颁布一道法令，不使用印章，可重复用已盖章法令。", "Ea", "nobility"),
    "herald": UnitSpec("传令官", 5, "战术：用供应币增强相邻未增强友军。己方颁布法令后可免费调遣。", "He", "nobility"),
    "sapper": UnitSpec("工兵", 5, "战术：移动后攻击堡垒。移动到没有堡垒的据点时可修建堡垒。", "Sa", "siege"),
    "siege_tower": UnitSpec("攻城塔", 5, "部署后可从供应增强。攻城战术：连续攻击两次，发动时必须已增强。", "St", "siege"),
    "trebuchet": UnitSpec("投石机", 5, "只能使用攻城战术攻击：攻击直线两或三格外目标，可越过单位；发动时必须已增强。", "Tr", "siege"),
    "war_wagon": UnitSpec("战车", 4, "攻城战术：移动相邻友军，再移动到其原位。相邻友军被攻击时，可由战车承受损失。", "Wa", "siege"),
    "assassin": UnitSpec("刺客", 4, "战术：移动后毒害相邻敌军。攻击中毒敌军后，可从其供应额外移除一枚币。", "As", "nightfall"),
    "saboteur": UnitSpec("破坏者", 5, "战术：毒害一或两格内敌军，可越过单位。招募后可免费使用战术。", "Sb", "nightfall"),
    "infiltrator": UnitSpec("渗透者", 5, "战术：移动到敌方控制的据点并控制。控制后可将自己的诱饵币放入对手弃牌。", "In", "nightfall"),
    "skirmisher": UnitSpec("散兵", 4, "战术：移动一或两格，终点须邻接敌军。被攻击时，可交出诱饵币给对手弃牌以抵挡。", "Sk", "nightfall"),
    "rearguard": UnitSpec("后卫", 5, "另一支友军被攻击并完成攻击效果后，后卫可移动一格。", "Re", "shock"),
    "raider": UnitSpec("劫掠者", 5, "增强后可移动。战术：弃置一枚增强币，移动后控制据点。", "Ra", "shock"),
    "pitch_thrower": UnitSpec("火油投手", 5, "招募时可用招募币直接增强。战术：弃置一枚增强币，震慑两格外敌军。", "Pt", "shock"),
    "war_drummer": UnitSpec("战鼓手", 5, "移动后可将任意一方供应中的一枚币放在其袋顶，成为下次抽到的币。", "Wd", "shock"),
    "heavy_cavalry": UnitSpec("重骑兵", 4, "替代枪骑兵。战术：沿直线移动恰好两格，可进入敌军所在格并震慑该敌军。", "Hc", "shock", "lancer"),
    "vanguard": UnitSpec("先锋", 5, "替代步兵。部署后可调遣。战术：震慑相邻敌军，须已增强。", "Va", "shock", "footman"),
    "warlord": UnitSpec("军阀", 5, "替代元帅。战术：令两格内友军调遣，然后震慑该友军。", "Wl", "shock", "marshall"),
})
EXPANSIONS = {
    "base": "基础版", "nobility": "贵族", "siege": "攻城",
    "nightfall": "夜幕", "shock": "震慑战术",
}


def unit_family(unit):
    return UNITS[unit].family or unit


def unit_pool(expansions):
    return [u for u, spec in UNITS.items() if spec.expansion in expansions]


ARMIES = (
    ("swordsman", "pikeman", "crossbowman", "light_cavalry"),
    ("archer", "cavalry", "lancer", "scout"),
)
ROYAL = "royal"


def coin_name(coin):
    if coin.startswith("decoy_"):
        return UNITS[coin.removeprefix("decoy_")].name + "诱饵"
    return "皇家币" if coin == ROYAL else UNITS[coin].name
