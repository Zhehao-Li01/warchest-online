"""Reproducible full-base stress check: python3 -m scripts.validate_full_base."""
import argparse
from collections import Counter
import json
from pathlib import Path
import random

from warchest import RULES_VERSION, apply_action, deserialize, legal_actions, new_game, serialize, validate_state
from warchest.units import UNITS, BASE_UNITS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--games', type=int, default=100)
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--output', default='docs/full-base-report.json')
    args = parser.parse_args()
    if args.games < 1 or args.limit < 1:
        parser.error('games and limit must be positive')
    results, skills = [], Counter()
    for seed in range(args.games):
        units = random.Random(seed ^ 0x5743).sample(list(BASE_UNITS), 8)
        armies = (units[:4], units[4:])
        first = random.Random(seed ^ 0x494E).randrange(2)
        state = new_game(seed, armies, initiative=first)
        rng = random.Random(seed + 10000)
        for step in range(1, args.limit + 1):
            actions = legal_actions(state)
            assert actions, (seed, step, 'no legal action')
            if state.pending:
                skills[state.pending[0]['type']] += 1
            action = rng.choice(actions)
            state, _ = apply_action(state, action)
            validate_state(state)
            if state.pending or step % 100 == 0:
                assert deserialize(serialize(state)) == state
            if state.winner is not None:
                break
        results.append({'seed': seed, 'armies': armies, 'initiative': first, 'actions': step,
                        'status': 'finished' if state.winner is not None else 'truncated',
                        'winner': state.winner})
        if (seed + 1) % 10 == 0:
            print(f'{seed + 1}/{args.games} checked', flush=True)
    report = {'rules_version': RULES_VERSION, 'games': args.games, 'max_actions': args.limit,
              'total_actions': sum(r['actions'] for r in results),
              'summary': dict(Counter(r['status'] for r in results)),
              'continuations_exercised': dict(skills), 'results': results}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}))


if __name__ == '__main__':
    main()
