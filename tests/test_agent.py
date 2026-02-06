import pytest

from gotg.agent import build_prompt


PREFIX = "add the following to the conversation:"


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
    assert f"[agent-2] {PREFIX}\nWhat about Y?" in messages[2]["content"]


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


def test_build_prompt_uses_default_prompt_when_no_system_prompt(iteration):
    """Agent config without system_prompt should use DEFAULT_SYSTEM_PROMPT."""
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    agent = {"name": "agent-1"}
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert DEFAULT_SYSTEM_PROMPT in system


def test_build_prompt_custom_prompt_overrides_default(iteration):
    """Agent config with system_prompt should use it instead of default."""
    agent = {"name": "agent-1", "system_prompt": "You are a designer."}
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "You are a designer." in system
    from gotg.scaffold import DEFAULT_SYSTEM_PROMPT
    assert DEFAULT_SYSTEM_PROMPT not in system


def test_build_prompt_system_includes_agent_name(agent_config, iteration):
    messages = build_prompt(agent_config, iteration, [])
    system = messages[0]["content"]
    assert "Your name is agent-1." in system


def test_build_prompt_system_includes_message_format_explanation(agent_config, iteration):
    messages = build_prompt(agent_config, iteration, [])
    system = messages[0]["content"]
    assert "more than one teammate at a time" in system
    assert "[teammate-name] add the following to the conversation:" in system


def test_build_prompt_longer_conversation(agent_config, iteration):
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "msg 1"},
        {"from": "agent-2", "iteration": "iter-1", "content": "msg 2"},
        {"from": "agent-1", "iteration": "iter-1", "content": "msg 3"},
        {"from": "agent-2", "iteration": "iter-1", "content": "msg 4"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 4 history messages (alternating, so no consolidation)
    assert len(messages) == 5
    roles = [m["role"] for m in messages]
    assert roles == ["system", "assistant", "user", "assistant", "user"]


# --- consolidation ---

def test_build_prompt_consolidates_consecutive_user_messages(iteration):
    """Consecutive non-self messages should be merged into one user message."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "proposal"},
        {"from": "human", "iteration": "iter-1", "content": "consider auth"},
        {"from": "agent-2", "iteration": "iter-1", "content": "good point"},
    ]
    messages = build_prompt(agent, iteration, history)
    # system + assistant + ONE consolidated user message
    assert len(messages) == 3
    roles = [m["role"] for m in messages]
    assert roles == ["system", "assistant", "user"]
    # Both speakers in the consolidated message
    consolidated = messages[2]["content"]
    assert f"[human] {PREFIX}\nconsider auth" in consolidated
    assert f"[agent-2] {PREFIX}\ngood point" in consolidated


def test_build_prompt_three_agents_consolidates(iteration):
    """With 3 agents, consecutive non-self messages get consolidated."""
    agent = {"name": "alice", "system_prompt": "You are an engineer."}
    history = [
        {"from": "alice", "iteration": "iter-1", "content": "I think X"},
        {"from": "bob", "iteration": "iter-1", "content": "I think Y"},
        {"from": "carol", "iteration": "iter-1", "content": "I think Z"},
    ]
    messages = build_prompt(agent, iteration, history)
    # system + assistant + ONE consolidated user (bob + carol)
    assert len(messages) == 3
    roles = [m["role"] for m in messages[1:]]
    assert roles == ["assistant", "user"]
    consolidated = messages[2]["content"]
    assert "[bob]" in consolidated
    assert "[carol]" in consolidated


def test_build_prompt_content_preserved_exactly(agent_config, iteration):
    """Content with special chars should pass through in the prefixed message."""
    content = 'Use a dict like {"id": 1, "done": false}\nThen serialize it.'
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": content},
    ]
    messages = build_prompt(agent_config, iteration, history)
    assert content in messages[1]["content"]


def test_build_prompt_seed_not_added_when_history_exists(agent_config, iteration):
    """When history exists, no seed message should be injected."""
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "hello"},
    ]
    messages = build_prompt(agent_config, iteration, history)
    # system + 1 history message, no seed
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert f"[agent-2] {PREFIX}\nhello" in messages[1]["content"]


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
    # agent-1 → user, agent-2 → assistant, agent-3 → user, agent-2 → assistant
    assert roles == ["user", "assistant", "user", "assistant"]


# --- prefix format ---

def test_build_prompt_prefix_format(iteration):
    """Non-self messages use the 'add the following to the conversation' prefix."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "hello"},
    ]
    messages = build_prompt(agent, iteration, history)
    expected = f"[agent-2] {PREFIX}\nhello"
    assert messages[1]["content"] == expected


def test_build_prompt_no_prefix_on_own_messages(iteration):
    """Own messages (assistant role) should NOT get a prefix."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "my idea"},
    ]
    messages = build_prompt(agent, iteration, history)
    assert messages[1]["content"] == "my idea"


def test_build_prompt_human_message_consolidated_with_agent(iteration):
    """Human + agent messages between own turns get consolidated."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "proposal"},
        {"from": "human", "iteration": "iter-1", "content": "consider auth"},
        {"from": "agent-2", "iteration": "iter-1", "content": "good point"},
    ]
    messages = build_prompt(agent, iteration, history)
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "proposal"
    # human + agent-2 consolidated into one user message
    assert messages[2]["role"] == "user"
    assert f"[human] {PREFIX}\nconsider auth" in messages[2]["content"]
    assert f"[agent-2] {PREFIX}\ngood point" in messages[2]["content"]


def test_build_prompt_no_consecutive_user_messages(iteration):
    """There should never be consecutive user messages in the output."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "a"},
        {"from": "agent-3", "iteration": "iter-1", "content": "b"},
        {"from": "agent-1", "iteration": "iter-1", "content": "c"},
        {"from": "human", "iteration": "iter-1", "content": "d"},
        {"from": "agent-2", "iteration": "iter-1", "content": "e"},
        {"from": "agent-3", "iteration": "iter-1", "content": "f"},
    ]
    messages = build_prompt(agent, iteration, history)
    for i in range(1, len(messages)):
        if messages[i]["role"] == "user":
            assert messages[i - 1]["role"] != "user", (
                f"Consecutive user messages at index {i - 1} and {i}"
            )


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
    # agent-1 should not be listed as its own teammate
    teammates_section = system.split("Your teammates are:")[1].split("Current task:")[0]
    assert "agent-1" not in teammates_section


def test_build_prompt_without_participants_no_teammate_list(iteration):
    """When all_participants is None, system prompt has no teammate list."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "Your teammates are:" not in system
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
    assert "Your teammates are: agent-2 (Software Engineer)." in system
