"""Official expansion card/FAQ regression cases; all transitions check invariants."""
from collections import Counter
from copy import deepcopy
import json
import random

import pytest
from warchest import Action, apply_action, deserialize, legal_actions, new_game, observe, serialize, validate_state
from warchest.board import LOCATIONS
from warchest.engine import IllegalAction
from warchest.expansions import DECREES, FORT_LAYOUTS
from warchest.model import Stack
from warchest.recording import new_record, append_step, replay_states
from warchest.serialization import state_digest
from warchest.units import UNITS, BASE_UNITS, EXPANSIONS, unit_family


def position(a=(), b=(), board=(), hands=None, forts=(), decrees=('enlist','redeploy','spy')):
    """Fill unused roster slots, preserving eight independent physical coin types."""
    armies = [list(a), list(b)]
    used = {unit_family(u) for side in armies for u in side}
    for side in armies:
        for unit in BASE_UNITS:
            if len(side) == 4: break
            if unit_family(unit) not in used:
                side.append(unit); used.add(unit_family(unit))
    s = new_game(37, armies, expansions=list(EXPANSIONS), setup={'forts':forts,'decrees':decrees})
    s.board = {p:Stack(who,u,n) for p,who,u,n in board}
    s.history = ()
    hands = hands or (('royal',), ('royal',))
    for who,p in enumerate(s.players):
        p.hand=list(hands[who]); p.bag=[] if 'royal' in p.hand else ['royal']; p.discard=[]
        used=Counter(p.hand)
        used.update({})
        for st in s.board.values():
            if st.owner==who: used[st.unit]+=st.count
        p.supply={u:UNITS[u].coins-used[u] for u in p.supply}
    validate_state(s)
    return s


def act(s, kind=None, **kw):
    actions=[a for a in legal_actions(s) if (kind is None or a.kind==kind) and all(getattr(a,k)==v for k,v in kw.items())]
    assert actions, (kind,kw,legal_actions(s),s.pending)
    old=serialize(s)
    result,events=apply_action(s,actions[0])
    assert serialize(s)==old
    validate_state(result)
    restored=deserialize(serialize(result))
    assert restored==result
    assert legal_actions(restored)==legal_actions(result)
    return result


def finish(s):
    while s.pending:
        s=act(s,'finish')
    return s


def test_catalog_layouts_and_setup():
    assert len(UNITS)==47 and len(BASE_UNITS)==16
    assert Counter(u.expansion for u in UNITS.values())==dict(base=16,nobility=4,siege=4,nightfall=4,shock=7,champions=4,mastery=4,high_seas=4)
    assert sum(UNITS[u].coins for u in UNITS if UNITS[u].expansion=='nightfall')==18
    assert len(set(FORT_LAYOUTS))==6
    for layout in FORT_LAYOUTS:
        assert len(set(layout))==4 and set(layout)<=LOCATIONS
        assert {(-q,-r) for q,r in layout}==set(layout)
    s=new_game(0,expansions=list(EXPANSIONS))
    assert len(s.extras['forts'])==4 and len(s.extras['decrees'])==3
    assert s==new_game(0,expansions=list(EXPANSIONS))
    validate_state(s)
    with pytest.raises(ValueError):
        new_game(0, (('warlord','swordsman','pikeman','archer'),('marshall','scout','cavalry','knight')))
    with pytest.raises(ValueError): new_game(0, expansions=['unknown'])


def test_earl_deploy_optional_move():
    s=position(('earl',),hands=(('earl',),('royal',)))
    s=act(s,'deploy',target=(-1,-2))
    assert s.pending[0]['type']=='x_move'
    s=act(s,'move',path=((0,-2),))
    assert s.board[(0,-2)].unit=='earl' and not s.pending


def test_bannerman_displacement_is_not_maneuver_or_move_attribute():
    s=position(('bannerman',),('war_drummer',),board=(((0,0),0,'bannerman',1),((1,-1),1,'war_drummer',1)),hands=(('bannerman',),('royal',)))
    s=act(s,'move',path=((0,-1),))
    s=act(s,'displace',path=((2,-1),))
    assert not s.pending and s.board[(2,-1)].unit=='war_drummer'


def test_bishop_recruit_then_attack_and_defense():
    s=position(('bishop',),('knight',),board=(((0,0),0,'bishop',2),((1,0),1,'knight',1)),hands=(('bishop',),('royal',)))
    n=s.players[0].supply['bishop']
    s=act(s,'tactic',effect='bishop_attack',target=(1,0),recruit='bishop')
    assert s.players[0].supply['bishop']==n-1 and (1,0) not in s.board
    for count, allowed in ((1,True),(2,False)):
        s=position((),('bishop',),board=(((0,0),0,'swordsman',count),((1,0),1,'bishop',1)),hands=(('swordsman',),('royal',)))
        assert any(a.kind=='attack' for a in legal_actions(s))==allowed


def test_herald_bolsters_other_unbolstered_unit_from_its_supply():
    s=position(('herald','raider'),board=(((0,0),0,'herald',1),((1,0),0,'raider',1)),hands=(('herald',),('royal',)))
    n=s.players[0].supply['raider']
    s=act(s,'tactic',effect='supply_bolster')
    assert s.board[(1,0)].count==2 and s.players[0].supply['raider']==n-1
    assert s.pending[0]['type']=='x_move'
    s=finish(s)


def test_earl_reuses_sealed_decree_and_herald_triggers():
    s=position(('earl','herald'),board=(((-2,0),0,'earl',1),((0,0),0,'herald',1)),hands=(('earl',),('royal',)))
    s.extras['seals'][0]=['enlist']
    s=act(s,'tactic',effect='earl')
    assert s.controls[(-2,0)]==0
    s=act(s,'proclaim',effect='enlist')
    s=act(s,'recruit',recruit='earl'); s=act(s,'recruit',recruit='earl')
    assert s.extras['seals'][0]==['enlist'] and s.pending[0]['unit']=='herald'
    s=finish(s)


def test_forts_block_entry_transit_and_absorb_attack():
    s=position(('light_cavalry',),('bishop',),board=(((0,-1),0,'light_cavalry',1),((1,-1),1,'bishop',1)),hands=(('light_cavalry',),('royal',)),forts=((1,-1),))
    s.controls[(1,-1)]=1
    assert not any((1,-1) in a.path for a in legal_actions(s))
    s=act(s,'attack',target=(1,-1))
    assert s.board[(1,-1)].count==1 and not s.extras['forts']
    s=position(('light_cavalry',),board=(((0,-1),0,'light_cavalry',1),),hands=(('light_cavalry',),('royal',)),forts=((1,-1),))
    assert any(a.path==((1,-1),) for a in legal_actions(s))
    assert not any(len(a.path)==2 and a.path[0]==(1,-1) for a in legal_actions(s))


def test_sapper_build_and_mandatory_attack():
    s=position(('sapper',),board=(((0,0),0,'sapper',1),),hands=(('sapper',),('royal',)))
    assert not any(a.kind=='tactic' for a in legal_actions(s))
    s=act(s,'move',path=((1,-1),)); s=act(s,'build')
    assert [1,-1] in s.extras['forts']
    s=position(('sapper',),board=(((0,0),0,'sapper',1),),hands=(('sapper',),('royal',)),forts=((1,-1),))
    s=act(s,'tactic',path=((1,0),),target=(1,-1))
    assert not s.extras['forts'] and (1,0) in s.board


def test_siege_tower_deploy_bolster_and_double_pikeman_faq():
    s=position(('siege_tower',),hands=(('siege_tower',),('royal',)))
    s=act(s,'deploy'); s=act(s,'supply_bolster')
    assert next(iter(s.board.values())).count==2
    s=position(('siege_tower',),('pikeman',),board=(((0,0),0,'siege_tower',2),((1,0),1,'pikeman',2)),hands=(('siege_tower',),('royal',)))
    s=act(s,'tactic',target=(1,0),effect='double_attack')
    assert s.board[(0,0)].count==1
    s=act(s,'attack',target=(1,0))
    assert not s.board and len(s.players[0].removed)==len(s.players[1].removed)==2


def test_trebuchet_range_and_blockers():
    for count in (1,2):
        s=position(('trebuchet','swordsman'),('knight',),board=(((0,0),0,'trebuchet',count),((1,0),0,'swordsman',1),((3,0),1,'knight',1)),hands=(('trebuchet',),('royal',)))
        attacks=[a for a in legal_actions(s) if a.kind=='tactic']
        assert bool(attacks)==(count==2)
        assert not any(a.kind=='attack' for a in legal_actions(s))
        if count==2: s=act(s,'tactic',target=(3,0)); assert (3,0) not in s.board


def test_wagon_push_and_intercept_pikeman_retaliation():
    s=position(('war_wagon','war_drummer'),board=(((0,0),0,'war_wagon',2),((1,0),0,'war_drummer',1)),hands=(('war_wagon',),('royal',)))
    s=act(s,'tactic',effect='wagon_push',target=(1,0),path=((2,0),))
    assert s.board[(1,0)].unit=='war_wagon' and s.board[(2,0)].unit=='war_drummer'
    assert s.pending[0]['type']=='x_drum'; s=finish(s)
    s=position(('swordsman',),('pikeman','war_wagon'),board=(((0,0),0,'swordsman',1),((1,0),1,'pikeman',1),((2,0),1,'war_wagon',1)),hands=(('swordsman',),('royal',)))
    s=act(s,'attack',target=(1,0)); assert s.current==1
    s=act(s,'defend_wagon')
    assert (0,0) not in s.board and (2,0) not in s.board and (1,0) in s.board


def test_poison_reassignment_cure_and_fort_knight_bishop():
    s=position(('saboteur',),('knight','bishop'),board=(((0,0),0,'saboteur',2),((1,-1),1,'knight',1),((2,0),1,'bishop',1)),hands=(('saboteur','saboteur'),('knight','royal')),forts=((1,-1),))
    s=act(s,'tactic',effect='poison',target=(1,-1))
    assert not any(a.coin=='knight' and a.kind in ('move','attack','control','bolster','tactic') for a in legal_actions(s))
    s=act(s,'pass',coin='royal'); s=act(s,'tactic',effect='poison',target=(2,0))
    assert s.extras['poison']=={'saboteur':[2,0]}


def test_poisoned_footmen_single_cure_and_unpoisoned_grants_other():
    s=position(('footman',),('assassin','saboteur'),board=(((0,0),0,'footman',1),((1,0),0,'footman',1)),hands=(('footman',),('royal',)))
    s.extras['poison']={'assassin':[0,0],'saboteur':[1,0]}
    s=act(s,'cure'); assert not s.extras['poison']
    s=position(('footman',),('assassin',),board=(((0,0),0,'footman',1),((1,0),0,'footman',1)),hands=(('footman',),('royal',)))
    s.extras['poison']={'assassin':[0,0]}
    s=act(s,'tactic',source=(1,0),path=((2,0),))
    s=act(s,'move',source=(0,0),path=((0,1),))
    assert s.extras['poison']['assassin']==[0,1]


def test_assassin_mutual_elimination_still_culls_supply():
    s=position(('assassin',),('pikeman',),board=(((0,0),0,'assassin',1),((1,0),1,'pikeman',1)),hands=(('assassin',),('royal',)))
    s.extras['poison']={'assassin':[1,0]}
    s=act(s,'attack',target=(1,0)); assert not s.board
    n=s.players[1].supply['pikeman']; s=act(s,'cull')
    assert s.players[1].supply['pikeman']==n-1


def test_infiltrator_decoy_and_decoy_actions():
    s=position(('infiltrator',),board=(((0,2),0,'infiltrator',1),),hands=(('infiltrator',),('royal',)))
    s=act(s,'tactic',path=((1,2),),effect='move_control'); s=act(s,'deceive')
    p=s.players[1]; p.discard.remove(('decoy_infiltrator',True)); p.hand.append('decoy_infiltrator')
    kinds={a.kind for a in legal_actions(s) if a.coin=='decoy_infiltrator'}
    assert kinds=={'return_decoy','pass','initiative','recruit'}
    s=act(s,'return_decoy'); assert s.extras['decoys']['infiltrator']


def test_skirmisher_one_two_steps_and_double_attack_decoy():
    s=position(('skirmisher',),('pikeman',),board=(((0,0),0,'skirmisher',1),((2,0),1,'pikeman',1)),hands=(('skirmisher',),('royal',)))
    assert {len(a.path) for a in legal_actions(s) if a.kind=='tactic'}=={1,2}
    s=position(('siege_tower',),('skirmisher',),board=(((0,0),0,'siege_tower',2),((1,0),1,'skirmisher',1)),hands=(('siege_tower',),('royal',)))
    s=act(s,'tactic',effect='double_attack'); s=act(s,'defend_decoy')
    assert s.board[(1,0)].count==1 and ('decoy_skirmisher',True) in s.players[0].discard
    s=act(s,'attack'); assert (1,0) not in s.board


def test_saboteur_recruit_attribute_works_while_poisoned():
    s=position(('saboteur',),('assassin',),board=(((0,0),0,'saboteur',1),((1,0),1,'assassin',1)))
    s.extras['poison']={'assassin':[0,0]}
    s=act(s,'recruit',recruit='saboteur'); s=act(s,'tactic',effect='poison')
    assert s.extras['poison']['saboteur']==[1,0]


def test_rearguard_moves_between_tower_attacks():
    s=position(('siege_tower',),('pikeman','rearguard'),board=(((0,0),0,'siege_tower',3),((1,0),1,'pikeman',2),((1,-1),1,'rearguard',1)),hands=(('siege_tower',),('royal',)))
    s=act(s,'tactic',effect='double_attack',target=(1,0))
    assert s.current==1 and s.pending[0]['unit']=='rearguard'
    s=act(s,'move',path=((2,-1),)); assert s.current==0
    s=act(s,'attack',target=(1,0)); s=finish(s)


def test_raider_bolster_moves_and_tactic_spends_bolster():
    s=position(('raider',),board=(((0,0),0,'raider',1),),hands=(('raider','raider'),('royal',)))
    s=act(s,'bolster'); s=act(s,'finish'); s=act(s,'pass')
    s=act(s,'tactic',path=((1,-1),),effect='move_control')
    assert s.controls[(1,-1)]==0 and s.board[(1,-1)].count==1
    assert s.players[0].hand.count('raider')==2


def test_pitch_recruited_bolster_while_poisoned_and_shock():
    s=position(('pitch_thrower',),('assassin',),board=(((0,0),0,'pitch_thrower',1),))
    s.extras['poison']={'assassin':[0,0]}
    s=act(s,'recruit',recruit='pitch_thrower'); s=act(s,'recruit_bolster')
    assert s.board[(0,0)].count==2
    s=position(('pitch_thrower',),('knight',),board=(((0,0),0,'pitch_thrower',2),((2,0),1,'knight',3)),hands=(('pitch_thrower',),('royal',)))
    s=act(s,'tactic',effect='shock'); assert (2,0) not in s.board
    assert s.board[(0,0)].count==1 and not s.players[1].removed
    assert s.players[1].discard.count(('knight',True))==3


def test_drummer_top_order_and_public_knowledge():
    s=position(('war_drummer',),('pikeman',),board=(((0,0),0,'war_drummer',1),),hands=(('war_drummer',),('royal',)))
    s=act(s,'move',path=((1,0),)); s=act(s,'drum',effect='1',recruit='pikeman')
    assert s.players[1].bag[-1]=='pikeman'
    assert any(e['kind']=='bag_top' for e in observe(s,0)['history'])
    s=act(s,'pass'); assert s.players[1].hand[0]=='pikeman'


def test_heavy_cavalry_shock_is_not_attack_and_fort_immunity():
    s=position(('heavy_cavalry',),('pikeman',),board=(((0,0),0,'heavy_cavalry',1),((2,0),1,'pikeman',2)),hands=(('heavy_cavalry',),('royal',)))
    s=act(s,'tactic',path=((1,0),(2,0)))
    assert s.board[(2,0)].unit=='heavy_cavalry' and s.board[(2,0)].count==1
    assert not s.players[0].removed and not s.players[1].removed
    s=position(('heavy_cavalry',),('pikeman',),board=(((0,0),0,'heavy_cavalry',1),((2,0),1,'pikeman',2)),hands=(('heavy_cavalry',),('royal',)),forts=((2,0),))
    assert not any(a.path==((1,0),(2,0)) for a in legal_actions(s))


def test_vanguard_deploy_maneuver_and_shock_requirement():
    s=position(('vanguard',),hands=(('vanguard',),('royal',)))
    s=act(s,'deploy'); assert s.pending[0]['type']=='x_maneuver'; s=act(s,'move')
    for n in (1,2):
        s=position(('vanguard',),('bishop',),board=(((0,0),0,'vanguard',n),((1,0),1,'bishop',1)),hands=(('vanguard',),('royal',)))
        assert any(a.effect=='shock' for a in legal_actions(s))==(n==2)


def test_warlord_tracks_moving_ally_after_restore():
    s=position(('warlord','cavalry'),('pikeman',),board=(((0,0),0,'warlord',1),((1,0),0,'cavalry',2),((3,0),1,'pikeman',1)),hands=(('warlord',),('royal',)))
    s=act(s,'tactic',effect='command',target=(1,0))
    s=deserialize(serialize(s))
    s=act(s,'tactic',path=((2,0),),target=(3,0))
    assert set(s.board)=={(0,0)} and s.players[0].discard.count(('cavalry',True))==1
    assert s.players[0].removed==['cavalry']


@pytest.mark.parametrize('decree',list(DECREES))
def test_all_decrees_seals_and_execution(decree):
    others=[d for d in DECREES if d!=decree][:2]
    s=position(('swordsman',),('pikeman',),board=(((-1,-2),0,'swordsman',2),((0,-2),1,'pikeman',1)),decrees=(decree,*others))
    s.players[0].supply['swordsman']-=1; s.players[0].removed.append('swordsman')
    s=act(s,'proclaim',effect=decree)
    assert s.extras['seals'][0]==[decree]
    if decree=='enlist': s=act(s,'recruit'); s=act(s,'recruit')
    elif decree=='reinforce': s=act(s,'reinforce'); assert not s.players[0].removed
    elif decree=='spy':
        s=act(s,'spy'); assert observe(s,0)['extras']['spied_hand']==['royal']
        assert 'spied_hand' not in observe(s,1)['extras']
        s=act(s,'spy_discard',recruit='royal')
    elif decree=='redeploy': s=act(s,'redeploy',target=(2,-3)); assert s.board[(2,-3)].count==2
    elif decree=='march': s=act(s,'move'); assert len(s.board)==2
    else:
        s=act(s,'attack'); assert (0,-2) not in s.board
        if decree=='sacrifice': assert (-1,-2) not in s.board
    s=finish(s)


def test_last_control_wins_before_earl_proclaim_and_no_future_actions():
    s=position(('earl',),board=(((-2,0),0,'earl',1),),hands=(('earl',),('royal',)))
    for p in sorted(LOCATIONS- {(-2,0)})[:5]: s.controls[p]=0
    for p in sorted(LOCATIONS- {(-2,0)})[5:]: s.controls[p]=None
    s=act(s,'tactic',effect='earl')
    assert s.winner==0 and not s.pending and not legal_actions(s)
    with pytest.raises(IllegalAction): apply_action(s,Action('pass','royal'))


def test_hidden_pair_legal_actions_observation_and_invalid_no_mutation():
    s=new_game(19,expansions=list(EXPANSIONS)); other=deepcopy(s)
    other.players[1].bag.reverse(); other.seed=92
    other.rng_state=random.Random(92).getstate()
    # Swap enemy unknown hand/bag without affecting public totals.
    other.players[1].hand[0],other.players[1].bag[0]=other.players[1].bag[0],other.players[1].hand[0]
    assert observe(s,0)==observe(other,0) and legal_actions(s)==legal_actions(other)
    before=serialize(s)
    with pytest.raises(IllegalAction): apply_action(s,Action('tactic','unknown'))
    assert serialize(s)==before


def test_expansion_record_replays_all_steps():
    armies=(('bannerman','siege_tower','saboteur','warlord'),('raider','skirmisher','herald','war_drummer'))
    record=new_record(11,armies=armies,expansions=list(EXPANSIONS))
    s=new_game(11,armies,expansions=list(EXPANSIONS)); rng=random.Random(18)
    for _ in range(250):
        if s.winner is not None: break
        a=rng.choice(legal_actions(s)); s,events=apply_action(s,a)
        validate_state(s); assert state_digest(deserialize(serialize(s)))==state_digest(s)
        append_step(record,a,s,events)
    assert list(replay_states(json.loads(json.dumps(record))))[-1][0]==s


def test_warlord_can_grant_ensign_tactic_but_shocks_only_ensign():
    s=position(('warlord','ensign','sapper'),board=(((0,0),0,'warlord',1),((1,0),0,'ensign',1),((1,-1),0,'sapper',1)),hands=(('warlord',),('royal',)))
    s=act(s,'tactic',effect='command',target=(1,0))
    s=act(s,'tactic',coin='ensign',source=(1,-1),path=((2,-1),))
    assert (1,0) not in s.board and s.board[(2,-1)].unit=='sapper'


def test_poisoned_royal_guard_royal_coin_exception():
    s=position(('royal_guard',),('assassin',),board=(((0,-2),0,'royal_guard',1),))
    s.extras['poison']={'assassin':[0,-2]}
    s=act(s,'tactic',coin='royal',path=((1,-2),(2,-3)))
    assert s.extras['poison']['assassin']==[2,-3]


def test_decree_redeploy_cures_poison_and_retriggers_deployment():
    s=position(('siege_tower',),('assassin',),board=(((0,0),0,'siege_tower',2),))
    s.extras['poison']={'assassin':[0,0]}
    s=act(s,'proclaim',effect='redeploy'); s=act(s,'redeploy',target=(-1,-2))
    assert not s.extras['poison'] and s.board[(-1,-2)].count==2
    s=act(s,'supply_bolster'); assert s.board[(-1,-2)].count==3


def test_drummer_lifo_with_partial_bag_then_reshuffle():
    from warchest.engine import _draw_extra
    s=position(('war_drummer',),('pikeman','knight'),board=(((0,0),0,'war_drummer',1),),hands=(('war_drummer','war_drummer'),('royal',)))
    s=act(s,'move',path=((1,0),)); s=act(s,'drum',effect='1',recruit='pikeman')
    s=act(s,'pass'); s=act(s,'move',path=((0,0),)); s=act(s,'drum',effect='1',recruit='knight')
    # The last normal action started the next round: top two drawn before reshuffle.
    assert s.players[1].hand[:2]==['knight','pikeman']


def test_spy_private_history_and_replacement_draw():
    s=position(('earl',),hands=(('royal',),('archer','royal')))
    # B roster is inferred from available base units; choose a member for its hand.
    p=s.players[1]
    s=act(s,'proclaim',effect='spy'); s=act(s,'spy')
    assert any(e['kind']=='spy_view' for e in observe(s,0)['history'])
    assert not any(e['kind']=='spy_view' for e in observe(s,1)['history'])
    n=len(p.hand); s=act(s,'spy_discard',recruit='archer')
    assert len(s.players[1].hand)==n
    assert ('archer',False) in s.players[1].discard or 'archer' in s.players[1].hand


def test_warlord_can_command_itself_as_unit_within_two_spaces():
    s=position(('warlord',),board=(((0,0),0,'warlord',1),),hands=(('warlord',),('royal',)))
    s=act(s,'tactic',effect='command',target=(0,0))
    s=act(s,'move',path=((1,0),))
    assert not s.board and s.players[0].discard.count(('warlord',True))==2


def test_earl_new_control_can_enable_guard_decree():
    s=position(('earl',),('pikeman',),board=(((-2,0),0,'earl',1),((-1,0),1,'pikeman',1)),hands=(('earl',),('royal',)),decrees=('guard','march','reinforce'))
    assert any(a.effect=='earl' for a in legal_actions(s))
    s=act(s,'tactic',effect='earl'); s=act(s,'proclaim',effect='guard')
    s=act(s,'attack'); assert not s.board


@pytest.mark.parametrize('owner', [None, 0, 1])
def test_fort_protects_enemy_garrison_regardless_of_control(owner):
    target = (1,-1)
    s = position(('pikeman',), ('bishop',),
                 board=(((0,-1),0,'pikeman',2),(target,1,'bishop',1)),
                 hands=(('pikeman',),('royal',)), forts=(target,))
    s.controls[target] = owner
    # The Bishop normally cannot be attacked by a bolstered unit, but the fort can.
    action = next(a for a in legal_actions(s) if a.kind == 'attack' and a.target == target)
    assert action.effect == 'fort_attack'
    after, events = apply_action(s, action)
    validate_state(after)
    assert not after.extras['forts'] and after.board[target].count == 1
    assert after.controls[target] == owner
    assert any(e.kind == 'fort_destroyed' for e in events)
    assert not any(e.kind == 'damage' for e in events)


def test_empty_neutral_fort_can_be_entered_or_destroyed():
    target = (1,-1)
    s = position(('pikeman',), board=(((0,-1),0,'pikeman',1),),
                 hands=(('pikeman',),('royal',)), forts=(target,))
    assert s.controls[target] is None
    move = next(a for a in legal_actions(s) if a.kind == 'move' and a.path == (target,))
    attack = next(a for a in legal_actions(s) if a.kind == 'attack' and a.target == target)
    moved, _ = apply_action(s, move)
    destroyed, events = apply_action(s, attack)
    validate_state(moved); validate_state(destroyed)
    assert list(target) in moved.extras['forts'] and target in moved.board
    assert not destroyed.extras['forts'] and target not in destroyed.board
    assert (0,-1) in destroyed.board and destroyed.controls[target] is None
    assert any(e.kind == 'fort_destroyed' for e in events)


def test_neutral_fort_ranged_attack_obeys_archer_restriction():
    s = position(('archer',), board=(((-1,-1),0,'archer',1),),
                 hands=(('archer',),('royal',)), forts=((1,-1),))
    assert not any(a.kind == 'attack' for a in legal_actions(s))
    after = act(s, 'tactic', target=(1,-1))
    assert not after.extras['forts']


def test_march_can_move_either_bolstered_unit_to_shared_destination():
    s = position(('knight','pikeman'), board=(((0,0),0,'knight',2),((1,-1),0,'pikeman',2)),
                 decrees=('march','guard','reinforce'))
    s = act(s, 'proclaim', effect='march')
    moves = [a for a in legal_actions(s) if a.kind == 'move' and a.path == ((1,0),)]
    assert {a.source for a in moves} == {(0,0),(1,-1)}
    for action in moves:
        after, _ = apply_action(s, action)
        validate_state(after)
        assert after.board[(1,0)].unit == action.coin
        assert after.board[(1,0)].count == 2 and action.source not in after.board


@pytest.mark.parametrize('count', [1, 2])
def test_priest_pikeman_survival_matches_base(count):
    from test_base_units import position as base_position
    armies = (('warrior_priest','footman','berserker','marshall'),
              ('pikeman','knight','ensign','mercenary'))
    board = (((0,0),0,'warrior_priest',count),((1,0),1,'pikeman',1))
    hands = (('warrior_priest',),('royal',))
    base = base_position(*armies, board=board, hands=hands)
    expanded = position(*armies, board=board, hands=hands)
    for state in (base, expanded):
        result = act(state, 'attack', target=(1,0))
        assert bool(result.pending) == (count == 2)
        assert result.players[0].bag == ([] if count == 2 else ['royal'])
        assert result.current == (0 if count == 2 else 1)
