import argparse
from collections import Counter
import json
from pathlib import Path
import random

from .ai import choose_action
from .board import HEXES
from .engine import apply_action, legal_actions, new_game, observe, validate_state, visible_events
from .recording import append_step, new_record, replay_states
from .serialization import serialize
from .units import UNITS, coin_name

LABELS = {"deploy": "部署", "bolster": "补强", "recruit": "招募", "initiative": "争夺先手",
          "pass": "跳过", "move": "移动", "attack": "攻击", "control": "控制", "tactic": "战术",
          "finish": "结束追加行动", "defend_unit": "承受战场损失", "defend_supply": "移除供应抵挡"}


def render(view):
    board = {tuple(s["pos"]): s for s in view["board"]}
    controls = {tuple(c["pos"]): c["owner"] for c in view["controls"]}
    lines = [f"第 {view['round']} 轮 | 当前 {'AB'[view['current']]} | 先手标记 {'AB'[view['initiative']]}",
             "格子：坐标 / 控制方(*中立，.非据点) / 单位方+缩写+层数"]
    # Axial layout projected to rows. Blank slots preserve hex adjacency.
    for y in range(-6, 7):
        cells = []
        for q in range(-3, 4):
            r = (y - q) // 2
            pos = (q, r)
            if (y - q) % 2 or pos not in HEXES:
                cells.append(" " * 18)
                continue
            owner = controls.get(pos)
            control = ("*" if owner is None else "AB"[owner]) if pos in controls else "."
            s = board.get(pos)
            unit = f"{'AB'[s['owner']]}{UNITS[s['unit']].symbol}{s['count']}" if s else "--"
            cells.append(f"({q:+d},{r:+d}){control}/{unit}".center(18))
        lines.append("".join(cells).rstrip())
    for who, p in enumerate(view["players"]):
        hand = "、".join(coin_name(c) for c in p["hand"]) if p["hand"] is not None else f"{p['hand_count']} 枚暗牌"
        discard = "、".join("暗币" if c is None else coin_name(c) for c in p["discard"])
        supply = "、".join(f"{coin_name(c)}:{n}" for c, n in p["supply"].items())
        controlled = sum(c["owner"] == who for c in view["controls"])
        lines.append(f"{'AB'[who]} 控制 {controlled}/6 | 袋 {p['bag_count']} | 手牌 {hand}")
        lines.append(f"  供应 {supply} | 弃置 {discard or '空'}")
    if view.get("extras"):
        from .expansions import DECREES
        x = view["extras"]
        lines.append(f"堡垒 {x['forts']} | 剩余 {7-len(x['forts'])} | 毒药 {x['poison']} | 诱饵 {x['decoys']}")
        if x['decrees']:
            lines.append("法令：" + "、".join(DECREES[d][0] for d in x['decrees']) + f" | 已盖章 {x['seals']}")
    return "\n".join(lines)


def describe(action):
    parts = [LABELS.get(action.kind, action.kind), f"支付 {coin_name(action.coin)}"]
    if action.path:
        parts.append("路径 " + " → ".join(map(str, action.path)))
    if action.target is not None:
        parts.append(f"目标 {action.target}")
    if action.recruit:
        parts.append(coin_name(action.recruit))
    if action.after is not None:
        parts.append(f"攻击后移动至 {action.after}")
    if action.source is not None:
        parts.append(f"单位 {action.source}")
    if action.effect:
        parts.append(LABELS.get(action.effect, action.effect))
    return " | ".join(parts)


def print_events(events, player):
    for event in visible_events(events, player):
        print(event["kind"], json.dumps(dict(event["data"]), ensure_ascii=False))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def play(args):
    record = new_record(args.seed)
    state = new_game(args.seed)
    if args.load:
        record = json.loads(Path(args.load).read_text(encoding="utf-8"))
        for state, _ in replay_states(record):
            pass
        if state.winner is None:
            record["status"] = "ongoing"
    human = 0 if args.side == "A" else 1
    rng = random.Random(args.ai_seed)
    print("输入编号行动；help 查看技能，save 保存回放，quit 保存并中止。")
    while state.winner is None:
        print(render(observe(state, human, include_history=False)))
        actions = legal_actions(state)
        if state.current != human:
            action = choose_action(observe(state, state.current, include_history=False), actions, rng)
            print("随机 AI 行动：")
        else:
            for i, action in enumerate(actions, 1):
                print(f"{i:3}. {describe(action)}")
            try:
                command = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                command = "quit"
            if command == "help":
                for spec in UNITS.values():
                    print(f"{spec.name} ({spec.symbol}, {spec.coins} 枚)：{spec.help}")
                continue
            if command in ("save", "quit"):
                if command == "quit":
                    record["status"] = "aborted"
                write_json(args.output, record)
                print(f"已保存完整调试回放：{args.output}")
                if command == "quit":
                    return
                continue
            try:
                index = int(command)
                if not 1 <= index <= len(actions):
                    raise ValueError
                action = actions[index - 1]
            except ValueError:
                print("请输入有效行动编号。")
                continue
        state, events = apply_action(state, action)
        validate_state(state)
        append_step(record, action, state, events)
        print_events(events, human)
    print(render(observe(state, human, include_history=False)))
    print(f"{'AB'[state.winner]} 方获胜。")
    write_json(args.output, record)


def simulate(args):
    results = []
    for seed in range(args.seed, args.seed + args.games):
        state = new_game(seed)
        rng = random.Random(args.ai_seed + seed)
        record = new_record(seed) if args.record_dir else None
        for step in range(1, args.max_actions + 1):
            actions = legal_actions(state)
            action = choose_action(observe(state, state.current, include_history=False), actions, rng)
            state, events = apply_action(state, action)
            validate_state(state)
            if record is not None:
                append_step(record, action, state, events)
            if state.winner is not None:
                break
        status = "finished" if state.winner is not None else "truncated"
        results.append({"seed": seed, "actions": step, "status": status, "winner": state.winner})
        if record is not None:
            record["status"] = status
            Path(args.record_dir).mkdir(parents=True, exist_ok=True)
            write_json(Path(args.record_dir) / f"game-{seed}.json", record)
        if args.verbose:
            print(json.dumps(results[-1]), flush=True)
    report = {"games": args.games, "max_actions": args.max_actions, "ai_seed": args.ai_seed,
              "summary": dict(Counter(r["status"] for r in results)), "results": results}
    print(json.dumps(report["summary"]))
    if args.output:
        write_json(args.output, report)


def replay(args):
    record = json.loads(Path(args.file).read_text(encoding="utf-8"))
    player = {"A": 0, "B": 1}.get(args.view)
    for index, (state, events) in enumerate(replay_states(record)):
        print(f"--- 第 {index} 步 ---")
        if player is None:
            print(render(observe(state, 0, include_history=False)))
            print("完整调试状态：", serialize(state))
        else:
            print(render(observe(state, player, include_history=False)))
            print_events(events, player)
        if args.step:
            input("回车继续")
    print(f"校验通过；结果：{record['status']}")


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return result


def main():
    parser = argparse.ArgumentParser(description="战争之匣：官方入门阵容规则引擎")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("play", help="人类对随机 AI")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ai-seed", type=int, default=10000)
    p.add_argument("--side", choices=("A", "B"), default="A")
    p.add_argument("--output", default="save.json")
    p.add_argument("--load", help="从已保存的完整回放恢复")
    p.set_defaults(run=play)
    p = sub.add_parser("simulate", help="批量随机对局并检查状态守恒")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--ai-seed", type=int, default=10000)
    p.add_argument("--games", type=positive, default=100)
    p.add_argument("--max-actions", type=positive, default=2000)
    p.add_argument("--output")
    p.add_argument("--record-dir")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(run=simulate)
    p = sub.add_parser("replay", help="校验并回放一局")
    p.add_argument("file")
    p.add_argument("--view", choices=("A", "B", "full"), default="A")
    p.add_argument("--step", action="store_true")
    p.set_defaults(run=replay)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"错误：{exc}\n")
