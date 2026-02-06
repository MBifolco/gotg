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
    assert messages[2]["content"] == "[agent-2]: What about Y?"


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
    """Content with special chars should pass through with name prefix."""
    content = 'Use a dict like {"id": 1, "done": false}\nThen serialize it.'
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": content},
    ]
    messages = build_prompt(agent_config, iteration, history)
    assert messages[1]["content"] == f"[agent-2]: {content}"


def test_build_prompt_seed_not_added_when_history_exists(agent_config, iteration):
    """When history exists, no seed message should be injected."""
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "hello"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 1 history message, no seed
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "[agent-2]: hello"


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


# --- name prefix ---

def test_build_prompt_prefixes_other_messages(iteration):
    """Non-self messages should get [speaker]: prefix."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "hello"},
    ]
    messages = build_prompt(agent, iteration, history)
    assert messages[1]["content"] == "[agent-2]: hello"


def test_build_prompt_no_prefix_on_own_messages(iteration):
    """Own messages (assistant role) should NOT get a prefix."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "my idea"},
    ]
    messages = build_prompt(agent, iteration, history)
    assert messages[1]["content"] == "my idea"


def test_build_prompt_human_message_gets_prefix(iteration):
    """Human messages should get [human]: prefix."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "proposal"},
        {"from": "human", "iteration": "iter-1", "content": "consider auth"},
        {"from": "agent-2", "iteration": "iter-1", "content": "good point"},
    ]
    messages = build_prompt(agent, iteration, history)
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "proposal"
    assert messages[2]["role"] == "user"
    assert messages[2]["content"] == "[human]: consider auth"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"] == "[agent-2]: good point"


# --- all_participants ---

def test_build_prompt_with_participants_lists_teammates(iteration):
    """System prompt should list teammates when all_participants provided."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    participants = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
        {"name": "human", "role": "Product Manager"},
    ]
    messages = build_prompt(agent, iteration, [], participants)
    system = messages[0]["content"]
    assert "agent-2 (Software Engineer)" in system
    assert "human (Product Manager)" in system
    assert "agent-1" not in system.split("Your teammates:")[1].split("Current task:")[0]


def test_build_prompt_without_participants_backward_compat(iteration):
    """When all_participants is None, system prompt has no teammate list."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "Your teammates:" not in system
    assert "Current task:" in system


def test_build_prompt_participants_only_two_agents(iteration):
    """With two agents, one teammate is listed."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    participants = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
    ]
    messages = build_prompt(agent, iteration, [], participants)
    system = messages[0]["content"]
    assert "Your teammates: agent-2 (Software Engineer)" in system
