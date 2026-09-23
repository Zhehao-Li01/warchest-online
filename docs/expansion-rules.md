# 扩展规则覆盖表

实现位于 `warchest/expansions.py`，卡片数据位于 `warchest/units.py`；测试主文件为 `tests/test_expansions.py`。原基础版覆盖表保留在 [rules.md](rules.md)。规则来源和版本解释见 [expansions.md](expansions.md#规则来源与裁定)。

| 规则 / 卡面 / FAQ | 实现入口 | 专项测试名（省略 test_） |
|---|---|---|
| 35 张卡、币数、替代版本、六种地图布局 | `initialize`, `validate_extras` | `catalog_layouts_and_setup` |
| 掌旗官调遣后驱离；不是目标的调遣 | `maneuver_hooks`, `displace` | `bannerman_displacement_is_not_maneuver_or_move_attribute` |
| 主教招募+移动/攻击、增强攻击者禁攻 | `maneuvers`, `attackable` | `bishop_recruit_then_attack_and_defense` |
| 伯爵部署后移动 | `deploy_hooks` | `earl_deploy_optional_move` |
| 伯爵控制+免印章法令，重复已有印章 | `decree_options`, `proclaim` | `earl_reuses_sealed_decree_and_herald_triggers` |
| 新控制能启用守卫法令 | 伯爵战术的预览校验 | `earl_new_control_can_enable_guard_decree` |
| 传令官只增强相邻未增强友军；颁布后调遣 | `supply_bolster`, `proclaim` | `herald_bolsters_other_unbolstered_unit_from_its_supply`、伯爵联动测试 |
| 堡垒进入、穿越、先摧毁堡垒再伤单位 | `can_enter`, `paths`, `attack` | `forts_block_entry_transit_and_absorb_attack` |
| 工兵移动建造、移动后必须有堡垒可攻击 | `move_hooks`, `maneuvers` | `sapper_build_and_mandatory_attack` |
| 攻城塔部署增强、两次攻击；反伤减至一层仍继续 | `deploy_hooks`, `double_attack` | `siege_tower_deploy_bolster_and_double_pikeman_faq` |
| 投石机直线二/三格、越过阻挡、须增强、禁普通攻击 | `maneuvers` | `trebuchet_range_and_blockers` |
| 战车推移后填入原位；代伤不取消长枪兵反伤 | `wagon_push`, `defend_wagon` | `wagon_push_and_intercept_pikeman_retaliation` |
| 刺客攻击中毒单位扣供应，互灭仍触发 | `after_attack`, `cull` | `assassin_mutual_elimination_still_culls_supply` |
| 破坏者毒害一/二格；中毒时招募属性仍触发 | `recruit`, `poison` | `saboteur_recruit_attribute_works_while_poisoned` |
| 毒药转移、跟随移动、无视堡垒/骑士/主教防御 | `poison`, `move` | `poison_reassignment_cure_and_fort_knight_bishop` |
| 两个步兵一币解毒；健康步兵指挥中毒步兵 | `cure`, 步兵追加 | `poisoned_footmen_single_cure_and_unpoisoned_grants_other` |
| 皇家币仍可移动中毒卫队 | 皇家币合法动作分支 | `poisoned_royal_guard_royal_coin_exception` |
| 渗透者移动到敌方据点并控制、发诱饵 | `move_control`, `deceive` | `infiltrator_decoy_and_decoy_actions` |
| 散兵移动一/二格须邻敌；诱饵只能挡一次塔攻击 | `maneuvers`, `defend_decoy` | `skirmisher_one_two_steps_and_double_attack_decoy` |
| 后卫在塔两次攻击之间移动 | `after_attack` 队列 | `rearguard_moves_between_tower_attacks` |
| 劫掠者增强后移动；战术支付增强币 | `bolster`, `unbolster` | `raider_bolster_moves_and_tactic_spends_bolster` |
| 火油投手招募增强（含中毒）、消耗增强震慑二格 | `recruit_bolster`, `shock` | `pitch_recruited_bolster_while_poisoned_and_shock` |
| 战鼓手可指定任一方；袋顶后进先出 | `drum` | `drummer_top_order_and_public_knowledge`, `drummer_lifo_with_partial_bag_then_reshuffle` |
| 重骑兵恰好直线两格、震慑不反伤、堡垒内免疫 | `charge_shock`, `shock` | `heavy_cavalry_shock_is_not_attack_and_fort_immunity` |
| 先锋部署调遣、增强条件 | `deploy_hooks`, `maneuvers` | `vanguard_deploy_maneuver_and_shock_requirement` |
| 军阀指挥后震慑、跟随位移且可恢复 | `command`, `x_shock_self` | `warlord_tracks_moving_ally_after_restore` |
| 军阀可授予旗手战术、可选自己 | `maneuvers` | `warlord_can_grant_ensign_tactic_but_shocks_only_ensign`, `warlord_can_command_itself_as_unit_within_two_spaces` |
| 七道法令、双方独立印章 | `decree_actions`, `proclaim` | `all_decrees_seals_and_execution`（7 个参数案例） |
| 重新部署整栈、清除毒药、重新触发部署属性 | `redeploy` | `decree_redeploy_cures_poison_and_retriggers_deployment` |
| 侦察私密历史、弃币与补抽 | `spy`, `spy_discard`, `observe_extras` | `spy_private_history_and_replacement_draw` |
| 第六据点立即终止，不继续免费法令 | `control`, `pump` | `last_control_wins_before_earl_proclaim_and_no_future_actions` |
| 隐藏配对观察一致、非法行动不改状态/RNG | `observe`, `apply_action` | `hidden_pair_legal_actions_observation_and_invalid_no_mutation` |
| 存档与逐步回放一致 | `serialization`, `recording` | `expansion_record_replays_all_steps`；每个 `act` 都做恢复与合法动作对比 |
| 房主配置、关闭扩展、重复/替代冲突、再战继承 | `Rooms.configuration`, `fresh_state` | `tests/test_web.py` 三项扩展测试 |
| 浏览器选扩展/双方阵容、好友加入、法令/侦察 | `setup.js`, `app.js` | `tests/test_browser.py` 两项扩展流程 |
| 100 个固定种子、每局上限 2,000、覆盖全部卡 | `scripts/validate_expansions.py` | [完整结果](expansion-simulation-results.json) |
