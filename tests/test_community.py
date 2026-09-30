"""Website expansion cards, public continuations and cross-expansion cases."""
from collections import Counter
from copy import deepcopy
import random

import pytest
from warchest import legal_actions, apply_action, validate_state, serialize, deserialize, observe
from warchest.board import SEA_HEXES
from warchest.community import victory_target, stacks
from test_expansions import position, act, finish


def test_champion_death_lowers_enemy_target_and_wins_immediately():
    s = position(('swordsman',), ('commander',), board=(((0,0),0,'swordsman',1),((1,0),1,'commander',1)), hands=(('swordsman',),('royal',)))
    s.controls = dict.fromkeys(s.controls)
    for p in list(s.controls)[:5]: s.controls[p] = 0
    s = act(s, 'attack', target=(1,0))
    assert s.winner == 0 and not s.pending and victory_target(s, 0) == 5
    assert not legal_actions(s)


def test_champion_bolster_loss_and_shock_do_not_count_as_death():
    s = position(('swordsman',), ('commander',), board=(((0,0),0,'swordsman',1),((1,0),1,'commander',2)), hands=(('swordsman',),('royal',)))
    s = act(s, 'attack', target=(1,0))
    assert victory_target(s, 0) == 6
    s = position(('vanguard',), ('commander',), board=(((0,0),0,'vanguard',2),((1,0),1,'commander',1)), hands=(('vanguard',),('royal',)))
    s = act(s, 'tactic', effect='shock', target=(1,0))
    assert victory_target(s, 0) == 6
    assert ('commander', True) in s.players[1].discard


def test_commander_grants_tactic_without_shocking_ally():
    s = position(('commander','archer'),('swordsman',),board=(((0,0),0,'commander',1),((0,1),0,'archer',1),((2,0),1,'swordsman',1)), hands=(('commander',),('royal',)))
    s = act(s, 'tactic', effect='command_free', target=(0,1))
    s = act(s, 'tactic', target=(2,0))
    assert (2,0) not in s.board and s.board[(0,1)].unit == 'archer'


def test_dragoon_straight_charge_and_marksman_melee():
    s = position(('dragoon',),('swordsman',),board=(((0,0),0,'dragoon',1),((3,0),1,'swordsman',1)), hands=(('dragoon',),('royal',)))
    s = act(s, 'tactic', path=((1,0),(2,0)), target=(3,0))
    assert s.board[(2,0)].unit == 'dragoon' and (3,0) not in s.board
    s = position(('marksman',),('swordsman','pikeman'),board=(((0,0),0,'marksman',1),((1,0),1,'swordsman',1),((2,0),1,'pikeman',1)), hands=(('marksman',),('royal',)))
    assert any(a.kind == 'attack' and a.target == (1,0) for a in legal_actions(s))
    s = act(s, 'tactic', target=(2,0))
    assert (2,0) not in s.board and (1,0) in s.board


def test_ranger_attack_then_move_after_defense():
    s = position(('ranger',), ('royal_guard',), board=(((0,0),0,'ranger',1),((1,0),1,'royal_guard',1)), hands=(('ranger',),('royal',)))
    s = act(s, 'tactic', effect='attack_move', target=(1,0))
    assert s.current == 1
    s = act(s, 'defend_unit')
    s = act(s, 'move', path=((1,0),))
    assert s.board[(1,0)].unit == 'ranger'


def test_alchemist_swap_does_not_trigger_swapped_sapper():
    s = position(('alchemist','sapper'),board=(((0,0),0,'alchemist',1),((1,-1),0,'sapper',1)),hands=(('alchemist',),('royal',)))
    s = act(s, 'tactic', effect='swap', target=(1,-1))
    assert s.board[(0,0)].unit == 'sapper'
    assert all(a.kind != 'build' for a in legal_actions(s))
    s = act(s, 'control', source=(1,-1))
    assert s.controls[(1,-1)] == 0


@pytest.mark.parametrize('mode', ['both','tactic','attribute'])
def test_apprentice_copies_archer_then_expires(mode):
    s = position(('apprentice','archer'),('swordsman',),board=(((0,0),0,'apprentice',1),((0,1),0,'archer',1),((2,0),1,'swordsman',1)),hands=(('apprentice',),('royal',)))
    s = act(s, 'tactic', effect='copy_'+mode, target=(0,1))
    if mode == 'attribute':
        assert not any(a.kind == 'tactic' for a in legal_actions(s))
        s = act(s, 'move', path=((-1,0),))
    else:
        s = act(s, 'tactic', target=(2,0))
        assert (2,0) not in s.board
    assert not s.extras['copies'] and not s.pending
    assert s.players[0].discard.count(('apprentice',True)) == 1


def test_apprentice_attribute_berserker_uses_own_coins():
    s = position(('apprentice','berserker'),board=(((0,0),0,'apprentice',2),((0,1),0,'berserker',1)),hands=(('apprentice',),('royal',)))
    s = act(s, 'tactic', effect='copy_attribute', target=(0,1))
    s = act(s, 'move', path=((1,0),))
    assert s.pending[0]['type'] == 'x_berserk'
    s = act(s, 'move', path=((2,0),))
    assert s.board[(2,0)].count == 1 and not s.extras['copies']


def test_apprentice_royal_movement_ends_adjacent_friend():
    s = position(('apprentice','archer'),('swordsman',),board=(((0,0),0,'apprentice',1),((2,0),0,'archer',1)),hands=(('royal',),('royal',)))
    s = act(s, 'tactic', coin='royal', path=((1,0),))
    assert s.board[(1,0)].unit == 'apprentice'


def test_emissary_control_and_take_initiative_triggers_free_maneuver():
    s = position(('emissary',),board=(((1,-1),0,'emissary',1),),hands=(('emissary',),('royal',)))
    s.initiative = 1
    s = act(s, 'tactic', effect='emissary')
    s = act(s, 'change_initiative', effect='take')
    assert s.initiative == 0 and s.initiative_claimed
    s = act(s, 'move', path=((0,-1),))
    assert not s.pending


def test_enemy_claim_initiative_triggers_emissary_without_spending_hand():
    s = position((),('emissary',),board=(((0,0),1,'emissary',1),),hands=(('royal',),('royal',)))
    s.initiative = 1
    s = act(s, 'initiative')
    assert s.current == 1 and s.pending[0]['unit'] == 'emissary'
    s = act(s, 'move', path=((1,0),))
    assert s.current == 1 and s.players[1].hand == ['royal']


def test_overlord_captures_then_loses_bottom_coin():
    s = position(('overlord',),('swordsman','pikeman'),board=(((0,0),0,'overlord',1),((1,0),1,'swordsman',1),((0,1),1,'pikeman',1)),hands=(('overlord',),('pikeman',)))
    s = act(s, 'attack', target=(1,0))
    s = act(s, 'capture', recruit='swordsman')
    assert s.board[(0,0)].count == 2 and s.players[1].removed == []
    s = act(s, 'attack', target=(0,0))
    assert s.board[(0,0)].count == 1 and s.players[1].removed == ['swordsman']
    assert not s.extras['captured']['overlord']


def test_overlord_capture_limit_and_shock_returns_trophies_to_owner():
    s = position(('overlord',),('swordsman','vanguard'),board=(((0,0),0,'overlord',1),((1,0),1,'swordsman',1),((0,1),1,'vanguard',2)),hands=(('overlord',),('vanguard','royal')))
    s = act(s, 'attack', target=(1,0));s = act(s, 'capture', recruit='swordsman')
    s = act(s, 'tactic', effect='shock', target=(0,0))
    assert (0,0) not in s.board
    assert ('overlord',True) in s.players[0].discard and ('swordsman',True) in s.players[1].discard


def test_pirate_sea_moves_and_sea_attack():
    s = position(('pirate',),('swordsman',),board=(((3,0),0,'pirate',1),((3,-1),1,'swordsman',1)),hands=(('pirate','pirate'),('royal',)))
    s = act(s, 'move', path=((3,1),))
    assert (3,1) in SEA_HEXES
    s = act(s, 'pass')
    assert any(a.kind == 'move' and a.path == ((-3,-3),) for a in legal_actions(s))
    s = act(s, 'tactic', target=(3,-1))
    assert (3,-1) not in s.board


def test_land_units_cannot_enter_sea():
    s = position(('light_cavalry',),board=(((3,0),0,'light_cavalry',1),),hands=(('light_cavalry',),('royal',)))
    assert all(not set(a.path) & SEA_HEXES for a in legal_actions(s))


def test_longboat_board_transport_disembark_and_no_double_deploy():
    s = position(('longboat','archer'),('swordsman',),board=(((0,0),0,'longboat',1),((1,0),0,'archer',1)),hands=(('archer','longboat','archer'),('royal','swordsman')))
    s = act(s, 'move', path=((0,0),))
    assert s.extras['underlays']['0,0']['unit'] == 'longboat'
    assert not any(a.kind == 'bolster' and a.coin == 'longboat' for a in legal_actions(s))
    s = act(s, 'pass')
    assert not any(a.kind == 'deploy' and a.coin in ('archer','longboat') for a in legal_actions(s))
    s = act(s, 'move', coin='longboat', path=((0,1),))
    assert s.board[(0,1)].unit == 'archer' and '0,1' in s.extras['underlays']
    s = act(s, 'pass')
    s = act(s, 'move', coin='archer', path=((1,1),))
    assert s.board[(0,1)].unit == 'longboat' and s.board[(1,1)].unit == 'archer'
    assert not s.extras['underlays']


def test_longboat_can_be_attacked_separately_from_passenger():
    s = position(('longboat','knight'),('pikeman',),board=(((0,0),0,'longboat',1),((1,0),0,'knight',1),((0,1),1,'pikeman',1)),hands=(('knight',),('pikeman',)))
    s = act(s, 'move', path=((0,0),))
    actions = [a for a in legal_actions(s) if a.kind == 'attack' and a.target == (0,0)]
    assert actions and {a.target_unit for a in actions} == {'longboat'}
    s = act(s, 'attack', target=(0,0), target_unit='longboat')
    assert s.board[(0,0)].unit == 'knight' and not s.extras['underlays']


def test_longboat_poison_and_cure_affect_only_selected_unit():
    s = position(('longboat','archer'),('saboteur',),board=(((0,0),0,'longboat',1),((1,0),0,'archer',1),((0,1),1,'saboteur',1)),hands=(('archer','longboat'),('saboteur',)))
    s = act(s, 'move', path=((0,0),))
    s = act(s, 'tactic', effect='poison', target=(0,0), target_unit='longboat')
    assert not any(a.kind == 'move' and a.coin == 'longboat' for a in legal_actions(s))
    s = act(s, 'cure', coin='longboat')
    assert not s.extras['poison']


def test_longboat_deploy_passenger_and_transport_sapper_hook():
    s = position(('longboat','sapper'),board=(((0,-1),0,'longboat',1),),hands=(('sapper','longboat'),('royal',)))
    s = act(s, 'deploy', coin='sapper', target=(0,-1))
    s = act(s, 'pass')
    s = act(s, 'move', coin='longboat', path=((1,-1),))
    s = act(s, 'build')
    assert [1,-1] in s.extras['forts']


def test_corsair_vault_attack_and_spend_move():
    s = position(('corsair',),('swordsman','pikeman'),board=(((0,0),0,'corsair',2),((1,0),1,'swordsman',1),((2,-1),1,'pikeman',1)),hands=(('corsair',),('royal',)))
    assert not any(a.kind == 'attack' for a in legal_actions(s))
    moved = act(s, 'tactic', effect='vault', path=((2,0),))
    attacked = act(moved, 'attack', target=(1,0))
    assert (1,0) not in attacked.board
    spent = act(moved, 'spend_move', path=((3,0),))
    assert spent.board[(3,0)].count == 1


def test_admiral_interrupt_returns_turn_after_optional_maneuver():
    s = position(('swordsman',),('admiral',),board=(((1,-1),0,'swordsman',1),((0,0),1,'admiral',1)),hands=(('swordsman','royal'),('royal',)))
    s = act(s, 'control')
    assert s.current == 1 and s.pending[0]['unit'] == 'admiral'
    s = act(s, 'move', path=((0,1),))
    assert s.current == 1 and s.players[1].hand == ['royal']


def test_apprentice_uses_existing_poison_counter():
    s=position(('apprentice','saboteur'),('knight',),board=(((0,0),0,'apprentice',1),((0,1),0,'saboteur',1),((2,0),1,'knight',1)),hands=(('apprentice',),('royal',)))
    s=act(s,'tactic',effect='copy_tactic',target=(0,1))
    s=act(s,'tactic',effect='poison',target=(2,0))
    assert s.extras['poison']=={'saboteur':[2,0]} and not s.extras['copies']


def test_apprentice_can_copy_commander_tactic():
    s=position(('apprentice','commander','archer'),('swordsman',),board=(((0,0),0,'apprentice',1),((0,1),0,'commander',1),((1,0),0,'archer',1),((3,0),1,'swordsman',1)),hands=(('apprentice',),('royal',)))
    s=act(s,'tactic',effect='copy_tactic',target=(0,1))
    s=act(s,'tactic',effect='command_free',target=(1,0))
    s=act(s,'tactic',target=(3,0))
    assert not s.extras['copies'] and s.board[(1,0)].unit=='archer'


def test_apprentice_transport_persists_until_passenger_disembarks():
    s=position(('apprentice','longboat','archer'),('swordsman',),board=(((0,0),0,'apprentice',1),((0,1),0,'longboat',1),((1,0),0,'archer',1)),hands=(('apprentice','archer'),('royal',)))
    s=act(s,'tactic',effect='copy_attribute',target=(0,1))
    s=act(s,'move',path=((1,0),))
    assert s.extras['underlays']['1,0']['unit']=='apprentice' and not s.extras['copies']
    s=act(s,'pass')
    s=act(s,'move',coin='archer',path=((2,0),))
    assert not s.extras['underlays'] and s.board[(1,0)].unit=='apprentice'


def test_empty_ship_can_move_under_friend_and_cannot_bolster_from_herald():
    s=position(('longboat','herald'),board=(((0,0),0,'longboat',1),((1,0),0,'herald',1)),hands=(('longboat','herald'),('royal',)))
    assert not any(a.kind=='bolster' and a.coin=='longboat' for a in legal_actions(s))
    assert not any(a.effect=='supply_bolster' and a.target==(0,0) for a in legal_actions(s))
    s=act(s,'move',coin='longboat',path=((1,0),))
    assert s.board[(1,0)].unit=='herald' and s.extras['underlays']['1,0']['unit']=='longboat'


def test_cargo_bolsters_independently_and_march_selects_only_cargo():
    s=position(('longboat','archer'),('swordsman',),board=(((0,0),0,'longboat',1),),hands=(('archer','archer','royal'),('royal','swordsman')),decrees=('march','enlist','reinforce'))
    # Ensure the enemy has its stated payment unit.
    s=act(s,'deploy',coin='archer',target=(0,0));s=act(s,'pass',coin='royal')
    s=act(s,'bolster',coin='archer');s=act(s,'pass')
    s=act(s,'proclaim',effect='march')
    assert all(a.coin=='archer' for a in legal_actions(s))
    s=act(s,'move',path=((1,0),))
    assert s.board[(1,0)].count==2 and s.board[(0,0)].count==1


def test_overlord_cannot_capture_above_five_layers():
    s=position(('overlord',),('swordsman','archer'),board=(((0,0),0,'overlord',2),((1,0),1,'swordsman',1)),hands=(('overlord',),('royal',)))
    s.board[(0,0)].count=5
    s.players[1].supply['archer']-=3
    s.extras['captured']={'overlord':[[1,'archer'] for _ in range(3)]}
    validate_state(s)
    s=act(s,'attack',target=(1,0))
    assert not s.pending and s.players[1].removed==['swordsman']


def test_community_full_game_record_replays_and_public_ai_sees_no_bags():
    from warchest import new_game
    from warchest.units import EXPANSIONS
    from warchest.recording import new_record, append_step, replay_states
    from warchest.serialization import state_digest
    from warchest.ai import choose_action
    armies=(('apprentice','longboat','commander','pirate'),('overlord','emissary','ranger','admiral'))
    state=new_game(120,armies,expansions=list(EXPANSIONS))
    record=new_record(120,armies=armies,expansions=list(EXPANSIONS))
    rng=random.Random(512)
    assert state.version=='expansions-2'
    for i in range(300):
        actions=legal_actions(state)
        obs=observe(state,state.current,include_history=False)
        assert obs['players'][1-state.current]['hand'] is None
        assert all('bag' not in p for p in obs['players'])
        action=choose_action(obs,actions,rng)
        state,events=apply_action(state,action)
        validate_state(state)
        append_step(record,action,state,events)
        if state.winner is not None:break
    # A random-policy rollout may be truncated; replay must still be exact.
    assert state_digest(list(replay_states(record))[-1][0])==state_digest(state)
