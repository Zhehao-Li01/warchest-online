"""Observation-only random agent."""


def choose_action(observation, actions, rng):
    if observation["current"] != observation["player"]:
        raise ValueError("AI can only act on its own turn")
    if not actions:
        raise ValueError("no legal actions")
    return rng.choice(actions)
