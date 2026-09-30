# 规则范围与覆盖（基础版 16 兵种）

扩展规则另见 [扩展覆盖表](expansion-rules.md)。此页保留基础版规则与回归说明。

依据：[AEG 基础说明书及 FAQ](https://warchestonline.com/api/assets/warchest_rules.pdf)，[Yucata 授权实现的规则、卡牌列表与地图](https://www.yucata.de/en/Rules/WarChest)。支持基础版随机分兵和入门设置，不采用该网站列出的额外变体。皇家卫队使用发行商推荐的修订卡面。

## 棋盘与设置

引擎 `board.py` 使用半径 3 的 37 个合法六边格，公式为 `max(abs(q), abs(r), abs(q+r)) <= 3`。显示时横向为 `q`，纵向为 `2*r+q`，A 位于上方，B 位于下方。坐标取自[双人设置图](https://www.yucata.de/game-plugins/warchest/1.0.4/images/rules/setup.png)。

| 类型 | 坐标 |
|---|---|
| A 初始据点 | `(-1,-2)`、`(2,-3)` |
| B 初始据点 | `(-2,3)`、`(1,2)` |
| 中立据点 | `(-2,0)`、`(1,-1)`、`(3,-2)`、`(-3,2)`、`(-1,1)`、`(2,0)` |

单位堆叠与控制权分别记录，移动进入据点不会自动夺取控制权。每方标记剩余量由 `6 - 已控制数` 推导。

## 基础规则清单

规则主要由 `engine.py` 实现，以下名称对应 `tests/test_rules.py` 的测试（省略 `test_` 前缀）。

| 规则 | 验证 |
|---|---|
| 地图、邻接、距离、初始阵容和币数 | `official_board`、`initial_setup` |
| 部署位置、唯一在场单位、补强与整堆移动、被消灭后重新部署 | `deploy_and_bolster`、`blocked_deployment`、`move_stack_and_blocking`、`destroyed_unit_can_redeploy` |
| 任意币暗弃支付，招募到明弃，供应耗尽 | `recruit_and_pass`、`empty_supply_not_recruitable` |
| 皇家币行动限制 | `royal_only_facedown_actions` |
| 先手仅改变下一轮，每轮只能转移一次 | `initiative_next_round_only` |
| 占点独立行动、敌方起始据点可夺取、胜利立即终止 | `control_is_separate_from_move`、`capture_enemy_start_and_win`、`cannot_control_own_location` |
| 攻击减一层，永久移除，被攻击单位不自动让攻击者前进 | `attack_removes_to_box_and_no_automatic_advance` |
| 抽取期间袋空才重洗，手牌不足及连续行动 | `reshuffle_mid_draw_and_short_hand`、`draw_does_not_reshuffle_early`、`mid_draw_refill_reaches_three` |
| 非法行动无副作用、合法行动稳定去重 | `illegal_atomicity`、`stable_unique_legal_actions` |

## 入门阵容的 8 个兵种

特殊行动生成在 `tactics.py`，斥候部署在基础行动生成器，长枪兵反伤和剑士后续移动在执行器。下列卡图为核对来源，未将卡图作为项目素材分发。

| 兵种 / 总币数 | 行为 | 测试 |
|---|---|---|
| [剑士](https://www.yucata.de/game-plugins/warchest/1.0.4/images/swordsmanCard.jpg) / 5 | 攻击后可移动；击杀后的目标格也可进入 | `swordsman_optional_move_and_capture_space`、`swordsman_cannot_move_onto_surviving_target` |
| [长枪兵](https://www.yucata.de/game-plugins/warchest/1.0.4/images/pikemanCard.jpg) / 4 | 对相邻攻击者同时造成一枚损失；远程攻击不触发 | `pikeman_retaliation_even_when_destroyed`、`lancer_retaliation_after_moving`、`archer_nonstraight_and_blocked_shot` |
| [弩手](https://www.yucata.de/game-plugins/warchest/1.0.4/images/crossbowmanCard.jpg) / 5 | 直线两格远射要求中间空；保留普通攻击 | `crossbow_straight_clear_shot_and_melee` |
| [轻骑兵](https://www.yucata.de/game-plugins/warchest/1.0.4/images/lightCavalryCard.jpg) / 5 | 连续移动两步，逐步检查空格，可转向；保留普通移动 | `light_cavalry_turn_and_return` |
| [弓箭手](https://www.yucata.de/game-plugins/warchest/1.0.4/images/archerCard.jpg) / 4 | 攻击距离恰好为二，可越过单位；禁止普通攻击 | `archer_nonstraight_and_blocked_shot`、`no_normal_attack_for_restricted_units` |
| [骑兵](https://www.yucata.de/game-plugins/warchest/1.0.4/images/cavalryCard.jpg) / 4 | 移动一步后攻击，两个步骤均必需 | `cavalry_move_then_attack` |
| [枪骑兵](https://www.yucata.de/game-plugins/warchest/1.0.4/images/lancerCard.jpg) / 4 | 直线移动一或两步后同方向攻击；禁止普通攻击 | `lancer_straight_charge`、`lancer_cannot_turn_or_cross_units`、`no_normal_attack_for_restricted_units` |
| [斥候](https://www.yucata.de/game-plugins/warchest/1.0.4/images/scoutCard.jpg) / 5 | 可额外部署于友军邻接空格，仍遵守唯一单位限制 | `scout_deployment`、`scout_cannot_duplicate` |

## 信息、回放与系统验收

`tests/test_integrity.py` 覆盖：隐藏区交换不改变对手视角或合法动作、暗弃支付不泄漏、观察对象不引用可变原状态、AI 随机源独立、序列化恢复、回放篡改检测、未知版本与损坏存档拒绝、固定随机轨迹守恒、完整示例获胜和命令行保存恢复。

## 明确的边界

- 支持全部 16 基础兵种，每局双方各四种，不允许同种兵在敌我双方出现。步兵可在同一方部署两个单位。
- 轻骑兵两步按逐步相邻移动处理，允许第二步返回已腾空的起点；不额外添加卡面未规定的“必须最终距离二”限制。
- 基础规则没有本实现采用的自动僵局裁决。模拟到上限只截断，不能把这种记录当成正式和局样本。
- 币袋在引擎内保存有序列表以复现随机性，玩家视角只给数量；已知组成可从自身行动及公开历史推导。
- 回放校验是可复现性检查，不是对不可信文件来源的数字签名认证。


## 新增八兵种与结算流程

卡面来源为 [Yucata 兵种列表](https://www.yucata.de/en/Rules/WarChest)，皇家卫队使用[发行商赛事规则推荐的修订版](https://www.alderac.com/wp-content/uploads/2023/06/WarChest_Tournament_EN01_Rulesheet_FINAL.pdf)。全兵种测试在 `tests/test_base_units.py`。

| 兵种 | 实现与关键验证 |
|---|---|
| 狂战士 / 5 | 调遣后可弃置一枚本单位增强币继续调遣，不能弃掉最后一枚；币进入明弃；费用支付后的层数决定是否能攻击骑士。 |
| 旗手 / 5 | 两格内友军普通移动一格，终点也在两格内；触发被调动者能力。 |
| 步兵 / 5 | 最多两支在场，分别增强；战术令每支各调遣一次，允许不同类型，按顺序继续结算。 |
| 骑士 / 4 | 禁止未增强敌军的攻击；普通及远程/冲锋攻击都检查；长枪兵反伤不是攻击。 |
| 元帅 / 5 | 指挥两格内友军普通攻击，不能绕过弓箭手、枪骑兵的限制；触发剑士、狂战士、战斗牧师的属性。 |
| 雇佣兵 / 5 | 招募后可令在场雇佣兵免费调遣，不能用此能力部署或再次招募。 |
| 皇家卫队 / 5 | 皇家币支付战术，沿空格移动最多两格至己方据点；受击时可用供应币代替单位币损失，由防御方选择。 |
| 战斗牧师 / 4 | 攻击或控制后若仍在场上，抽一枚并必须立即使用该枚币；不可改用原手牌。胜利已触发则立即终止，不再抽币。 |

`pending` 显式记录必须完成或可放弃的后续选择。防御插入由对方操作，技能结算完成后依据 `turn_owner` 恢复正常交替，避免多动或少动。战斗牧师的新币不向对手公开。状态可在技能中途序列化恢复。
