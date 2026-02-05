import pytest

from gotg.agent import build_prompt


@pytest.fixture
def agent_config():
    return {
        "name": "agent-1",
        "system_prompt": "You are an engineer.",
    }


@pytest.fixture
def iteration():
    return {
        "id": "iter-1",
        "description": "Design a todo app.",
        "status": "in-progress",
        "max_turns": 10,
    }


def test_build_prompt_empty_history_has_system_and_seed(agent_config, iteration):
    """First agent with no history gets a system message and a seed user message."""
    messages = build_prompt(agent_config, iteration, [])
    assert messages[0]["role"] == "system"
    assert "You are an engineer." in messages[0]["content"]
    assert "Design a todo app." in messages[0]["content"]
    # Seed message
    assert messages[1]["role"] == "user"
    assert "Design a todo app." in messages[1]["content"]
    assert len(messages) == 2


def test_build_prompt_maps_own_messages_to_assistant(agent_config, iteration):
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "I think X"},
        {"from": "agent-2", "iteration": "iter-1", "content": "What about Y?"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 2 history messages
    assert len(messages) == 3
    assert messages[1]["role"] == "assistant"  # agent-1's own message
    assert messages[1]["content"] == "I think X"
    assert messages[2]["role"] == "user"  # agent-2's message
    assert messages[2]["content"] == "What about Y?"


def test_build_prompt_maps_other_messages_to_user(iteration):
    """From agent-2's perspective, agent-1's messages are 'user'."""
    agent2 = {"name": "agent-2", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "I think X"},
        {"from": "agent-2", "iteration": "iter-1", "content": "What about Y?"},
    ]
    messages = build_prompt(agent2, iteration, history)
    assert messages[1]["role"] == "user"  # agent-1's message, from agent-2's POV
    assert messages[2]["role"] == "assistant"  # agent-2's own message


def test_build_prompt_system_includes_task_description(agent_config, iteration):
    messages = build_prompt(agent_config, iteration, [])
    system = messages[0]["content"]
    assert "Current task:" in system
    assert "Design a todo app." in system


def test_build_prompt_longer_conversation(agent_config, iteration):
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "msg 1"},
        {"from": "agent-2", "iteration": "iter-1", "content": "msg 2"},
        {"from": "agent-1", "iteration": "iter-1", "content": "msg 3"},
        {"from": "agent-2", "iteration": "iter-1", "content": "msg 4"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 4 history messages
    assert len(messages) == 5
    roles = [m["role"] for m in messages]
    assert roles == ["system", "assistant", "user", "assistant", "user"]


# --- edge cases ---

def test_build_prompt_three_agents_all_others_are_user(iteration):
    """With 3 agents, both other agents' messages map to 'user'."""
    agent = {"name": "alice", "system_prompt": "You are an engineer."}
    history = [
        {"from": "alice", "iteration": "iter-1", "content": "I think X"},
        {"from": "bob", "iteration": "iter-1", "content": "I think Y"},
        {"from": "carol", "iteration": "iter-1", "content": "I think Z"},
    ]
    messages = build_prompt(agent, iteration, history)
    roles = [m["role"] for m in messages[1:]]  # skip system
    assert roles == ["assistant", "user", "user"]


def test_build_prompt_content_preserved_exactly(agent_config, iteration):
    """Content with special chars should pass through unchanged."""
    content = 'Use a dict like {"id": 1, "done": false}\nThen serialize it.'
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": content},
    ]
    messages = build_prompt(agent_config, iteration, history)
    assert messages[1]["content"] == content


def test_build_prompt_seed_not_added_when_history_exists(agent_config, iteration):
    """When history exists, no seed message should be injected."""
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "hello"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 1 history message, no seed
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "hello"


def test_build_prompt_system_message_is_always_first(agent_config, iteration):
    """System message should always be first regardless of history."""
    for history in [[], [{"from": "agent-2", "iteration": "iter-1", "content": "hi"}]]:
        messages = build_prompt(agent_config, iteration, history)
        assert messages[0]["role"] == "system"


def test_build_prompt_agent_only_sees_own_messages_as_assistant(iteration):
    """Even with many agents, only YOUR messages are 'assistant'."""
    agent = {"name": "agent-2", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "a"},
        {"from": "agent-2", "iteration": "iter-1", "content": "b"},
        {"from": "agent-3", "iteration": "iter-1", "content": "c"},
        {"from": "agent-2", "iteration": "iter-1", "content": "d"},
    ]
    messages = build_prompt(agent, iteration, history)
    roles = [m["role"] for m in messages[1:]]
    assert roles == ["user", "assistant", "user", "assistant"]
