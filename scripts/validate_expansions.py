"""Fixed-seed mixed-expansion stress run, separate from quick tests."""
import json
from pathlib import Path
import random
from warchest import new_game, legal_actions, apply_action, observe, validate_state, serialize, deserialize
from warchest.ai import choose_basic_action
from warchest.units import UNITS, EXPANSIONS, unit_family
from warchest.serialization import state_digest
from warchest.recording import new_record, append_step, replay_states


def main():
    results=[]; covered=set(); sample=None; winning_sample=None
    for seed in range(100):
        rng=random.Random(seed ^ 12345); pool=list(UNITS); rng.shuffle(pool)
        roster=[]; families=set()
        for u in pool:
            if unit_family(u) not in families:
                roster.append(u); families.add(unit_family(u))
            if len(roster)==8: break
        armies=(roster[:4],roster[4:]); covered.update(roster)
        s=new_game(seed,armies,expansions=list(EXPANSIONS)); steps=0
        record=new_record(seed,armies=armies,expansions=list(EXPANSIONS)) if seed==0 or winning_sample is None else None
        for steps in range(1,2001):
            actions=legal_actions(s)
            assert actions, (seed,steps,s.pending)
            a=rng.choice(actions)
            # Also evaluate the user-facing basic AI against every state.
            assert choose_basic_action(observe(s,s.current,include_history=False),actions,rng) in actions
            s,events=apply_action(s,a); validate_state(s)
            if steps%100==0:
                restored=deserialize(serialize(s))
                assert state_digest(restored)==state_digest(s)
                assert legal_actions(restored)==legal_actions(s)
                s=restored
            if record: append_step(record,a,s,events)
            if s.winner is not None: break
        status='finished' if s.winner is not None else 'truncated'
        results.append(dict(seed=seed,steps=steps,status=status,winner=s.winner,armies=armies))
        if record:
            record['status']=status
            assert state_digest(list(replay_states(record))[-1][0])==state_digest(s)
            if seed==0: sample=record
            if status=='finished' and winning_sample is None: winning_sample=record
        if seed%10==9: print(f'{seed+1}/100 verified',flush=True)
    Path('docs/expansion-simulation-results.json').write_text(json.dumps(dict(games=results,covered_units=sorted(covered)),indent=2)+'\n')
    Path('examples/expansion-random.json').write_text(json.dumps(sample,ensure_ascii=False,separators=(',',':'))+'\n')
    if winning_sample:
        Path('examples/expansion-win.json').write_text(json.dumps(winning_sample,ensure_ascii=False,separators=(',',':'))+'\n')
    print(f'100 games, {len(covered)} unit types, {sum(r["status"]=="finished" for r in results)} finished; remaining truncated',flush=True)

if __name__=='__main__': main()
