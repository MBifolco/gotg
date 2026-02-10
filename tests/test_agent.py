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


def test_build_prompt_system_includes_mention_instructions(agent_config, iteration):
    messages = build_prompt(agent_config, iteration, [])
    system = messages[0]["content"]
    assert "use @name" in system
    assert "@agent-1" in system  # watch for messages directed at you


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
    teammates_line = system.split("Your teammates are:")[1].split("\n")[0]
    assert "agent-1" not in teammates_line


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


# --- phase prompts ---

def test_build_prompt_includes_grooming_phase_prompt():
    """Iteration with phase=grooming should inject grooming instructions."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "grooming", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "CURRENT PHASE: GROOMING" in system
    assert "scope" in system.lower()
    assert "DO NOT" in system


def test_build_prompt_includes_planning_phase_prompt():
    """Planning phase should inject planning instructions."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "CURRENT PHASE: PLANNING" in system
    assert "tasks" in system.lower()
    assert "CURRENT PHASE: GROOMING" not in system


def test_build_prompt_no_phase_prompt_when_phase_missing():
    """Iteration without phase field should not get phase prompt (backward compat)."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "CURRENT PHASE" not in system


# --- coach awareness in agent prompt ---

def test_build_prompt_includes_coach_awareness():
    """Agent prompt should mention coach when coach is in participants."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    participants = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
        {"name": "coach", "role": "Agile Coach"},
    ]
    messages = build_prompt(agent, iteration, [], participants)
    system = messages[0]["content"]
    assert "Agile Coach" in system
    assert "process management" in system.lower()


def test_build_prompt_no_coach_awareness_without_coach():
    """Agent prompt should not mention coach facilitation when no coach."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    participants = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
    ]
    messages = build_prompt(agent, iteration, [], participants)
    system = messages[0]["content"]
    assert "process management" not in system.lower()


# --- build_coach_prompt ---

def test_build_coach_prompt_uses_facilitation_prompt():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPT
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress", "max_turns": 10}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "I think X"},
        {"from": "agent-2", "iteration": "iter-1", "content": "I agree"},
    ]
    messages = build_coach_prompt(coach, iteration, history)
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPT in system
    assert "CURRENT PHASE" not in system


def test_build_coach_prompt_maps_own_messages_to_assistant():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress", "max_turns": 10}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "idea"},
        {"from": "agent-2", "iteration": "iter-1", "content": "agree"},
        {"from": "coach", "iteration": "iter-1", "content": "summary so far"},
        {"from": "agent-1", "iteration": "iter-1", "content": "more ideas"},
    ]
    messages = build_coach_prompt(coach, iteration, history)
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert "summary so far" in assistant_msgs[0]["content"]


def test_build_coach_prompt_no_phase_injection():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "grooming", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert "CURRENT PHASE: GROOMING" not in system


def test_build_coach_prompt_lists_teammates():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress", "max_turns": 10}
    participants = [
        {"name": "agent-1", "role": "Software Engineer"},
        {"name": "agent-2", "role": "Software Engineer"},
        {"name": "coach", "role": "Agile Coach"},
    ]
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ], participants)
    system = messages[0]["content"]
    assert "agent-1 (Software Engineer)" in system
    assert "agent-2 (Software Engineer)" in system


def test_build_coach_prompt_consolidates_consecutive_messages():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress", "max_turns": 10}
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "idea A"},
        {"from": "agent-2", "iteration": "iter-1", "content": "idea B"},
        {"from": "agent-3", "iteration": "iter-1", "content": "idea C"},
    ]
    messages = build_coach_prompt(coach, iteration, history)
    # system + 1 consolidated user message
    assert len(messages) == 2
    assert messages[1]["role"] == "user"
    assert "[agent-1]" in messages[1]["content"]
    assert "[agent-2]" in messages[1]["content"]
    assert "[agent-3]" in messages[1]["content"]


# --- groomed summary injection ---

def test_build_prompt_injects_groomed_summary():
    """When groomed_summary is provided, it appears in the system message."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    summary = "## Summary\nBuild an auth system."
    messages = build_prompt(agent, iteration, [], groomed_summary=summary)
    system = messages[0]["content"]
    assert "GROOMED SCOPE SUMMARY" in system
    assert "Build an auth system." in system


def test_build_prompt_no_groomed_summary_when_none():
    """When groomed_summary is None, no summary section appears."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [], groomed_summary=None)
    system = messages[0]["content"]
    assert "GROOMED SCOPE SUMMARY" not in system


def test_build_prompt_groomed_summary_after_phase_prompt():
    """Groomed summary should appear after the phase prompt in system message."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    summary = "## Summary\nBuild an auth system."
    messages = build_prompt(agent, iteration, [], groomed_summary=summary)
    system = messages[0]["content"]
    phase_pos = system.index("CURRENT PHASE: PLANNING")
    summary_pos = system.index("GROOMED SCOPE SUMMARY")
    assert summary_pos > phase_pos


def test_build_coach_prompt_injects_groomed_summary():
    """Coach prompt should include groomed summary when provided."""
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    summary = "## Summary\nBuild an auth system."
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ], groomed_summary=summary)
    system = messages[0]["content"]
    assert "GROOMED SCOPE SUMMARY" in system
    assert "Build an auth system." in system


def test_build_coach_prompt_no_groomed_summary_when_none():
    """Coach prompt should not include summary section when None."""
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "planning", "max_turns": 10,
    }
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ], groomed_summary=None)
    system = messages[0]["content"]
    assert "GROOMED SCOPE SUMMARY" not in system


# --- tasks_summary injection ---

def test_build_prompt_injects_tasks_summary():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 10,
    }
    summary = "### Layer 0\n- **add-auth** [pending]"
    messages = build_prompt(agent, iteration, [], tasks_summary=summary)
    system = messages[0]["content"]
    assert "TASK LIST" in system
    assert "add-auth" in system


def test_build_prompt_no_tasks_summary_when_none():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [], tasks_summary=None)
    system = messages[0]["content"]
    assert "TASK LIST" not in system


def test_build_prompt_tasks_summary_after_groomed_summary():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 10,
    }
    groomed = "## Summary\nBuild auth."
    tasks = "### Layer 0\n- **add-auth** [pending]"
    messages = build_prompt(agent, iteration, [], groomed_summary=groomed, tasks_summary=tasks)
    system = messages[0]["content"]
    assert system.index("GROOMED SCOPE SUMMARY") < system.index("TASK LIST")


def test_build_coach_prompt_injects_tasks_summary():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 10,
    }
    tasks = "### Layer 0\n- **add-auth** [pending]"
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ], tasks_summary=tasks)
    system = messages[0]["content"]
    assert "TASK LIST" in system
    assert "add-auth" in system


def test_build_prompt_includes_pre_code_review_phase_prompt():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "pre-code-review", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "CURRENT PHASE: PRE-CODE-REVIEW" in system


# --- phase-specific coach facilitation ---

def test_build_coach_prompt_uses_grooming_facilitation():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "grooming", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPTS["grooming"] in system


def test_build_coach_prompt_uses_planning_facilitation():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "planning", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPTS["planning"] in system
    assert "requirements from the groomed scope" in system.lower()


def test_build_coach_prompt_uses_pre_code_review_facilitation():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "pre-code-review", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPTS["pre-code-review"] in system
    assert "all layers" in system.lower()


def test_build_coach_prompt_falls_back_to_default_for_unknown_phase():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPT
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "some-future-phase", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPT in system


def test_build_coach_prompt_falls_back_to_default_when_no_phase():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPT
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPT in system


# --- code-review phase + diffs injection ---

def test_build_prompt_includes_code_review_phase_prompt():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "code-review", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "CURRENT PHASE: CODE REVIEW" in system


def test_build_prompt_injects_diffs_summary():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "code-review", "max_turns": 10,
    }
    diffs = "=== agent-1/layer-0 ===\n src/main.py | 5 +++++\n\ndiff --git a/..."
    messages = build_prompt(agent, iteration, [], diffs_summary=diffs)
    system = messages[0]["content"]
    assert "IMPLEMENTATION DIFFS" in system
    assert "agent-1/layer-0" in system


def test_build_prompt_no_diffs_when_none():
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "code-review", "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [], diffs_summary=None)
    system = messages[0]["content"]
    assert "IMPLEMENTATION DIFFS" not in system


def test_build_coach_prompt_injects_diffs_summary():
    from gotg.agent import build_coach_prompt
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "code-review", "max_turns": 10,
    }
    diffs = "=== agent-1/layer-0 ===\n src/main.py | 5 +++++"
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ], diffs_summary=diffs)
    system = messages[0]["content"]
    assert "IMPLEMENTATION DIFFS" in system
    assert "agent-1/layer-0" in system


def test_build_coach_prompt_code_review_facilitation():
    from gotg.agent import build_coach_prompt
    from gotg.scaffold import COACH_FACILITATION_PROMPTS
    coach = {"name": "coach", "role": "Agile Coach"}
    iteration = {"id": "iter-1", "description": "Build a thing.", "status": "in-progress",
                 "phase": "code-review", "max_turns": 10}
    messages = build_coach_prompt(coach, iteration, [
        {"from": "agent-1", "iteration": "iter-1", "content": "hello"},
    ])
    system = messages[0]["content"]
    assert COACH_FACILITATION_PROMPTS["code-review"] in system
    assert "concerns" in system.lower()


# --- writable paths and worktree info ---

class _FakeFileGuard:
    """Minimal stand-in for FileGuard in prompt tests."""
    def __init__(self, writable_paths=None):
        self.writable_paths = writable_paths or []


def test_build_prompt_writable_paths_in_implementation():
    """FILE ACCESS info should appear in implementation phase with fileguard."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10, "current_layer": 0,
    }
    fg = _FakeFileGuard(writable_paths=["src/**", "tests/**"])
    messages = build_prompt(agent, iteration, [], fileguard=fg)
    system = messages[0]["content"]
    assert "FILE ACCESS" in system
    assert "src/**" in system
    assert "tests/**" in system


def test_build_prompt_no_writable_paths_in_grooming():
    """FILE ACCESS should not appear in grooming phase."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "grooming", "max_turns": 10,
    }
    fg = _FakeFileGuard(writable_paths=["src/**"])
    messages = build_prompt(agent, iteration, [], fileguard=fg)
    system = messages[0]["content"]
    assert "FILE ACCESS" not in system


def test_build_prompt_worktree_isolation_warning():
    """WORKTREE warning should appear when agent is in worktree_map."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10, "current_layer": 0,
    }
    worktree_map = {"agent-1": "/some/path", "agent-2": "/other/path"}
    messages = build_prompt(agent, iteration, [], worktree_map=worktree_map)
    system = messages[0]["content"]
    assert "WORKTREE" in system
    assert "isolated" in system.lower()


def test_build_prompt_no_worktree_warning_without_map():
    """WORKTREE warning should not appear without worktree_map."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10, "current_layer": 0,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "WORKTREE" not in system


def test_build_prompt_no_worktree_warning_when_agent_not_in_map():
    """WORKTREE warning should not appear for agents not in the map."""
    agent = {"name": "agent-3", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10, "current_layer": 0,
    }
    worktree_map = {"agent-1": "/some/path", "agent-2": "/other/path"}
    messages = build_prompt(agent, iteration, [], worktree_map=worktree_map)
    system = messages[0]["content"]
    assert "WORKTREE" not in system


# --- current_layer interpolation ---

def test_build_prompt_implementation_includes_current_layer():
    """Implementation phase prompt should interpolate {current_layer}."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10, "current_layer": 2,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "layer 2" in system
    assert "{current_layer}" not in system


def test_build_prompt_implementation_defaults_layer_to_zero():
    """When current_layer is not set, should default to 0."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "phase": "implementation",
        "max_turns": 10,
    }
    messages = build_prompt(agent, iteration, [])
    system = messages[0]["content"]
    assert "layer 0" in system
    assert "{current_layer}" not in system


# --- @mention awareness ---

def test_build_prompt_mention_awareness():
    """@agent-1 in recent message adds 'specifically addressed you' to system."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "my proposal"},
        {"from": "agent-2", "iteration": "iter-1", "content": "@agent-1 what about edge cases?"},
    ]
    messages = build_prompt(agent, iteration, history)
    system = messages[0]["content"]
    assert "specifically addressed you" in system
    assert "agent-2" in system


def test_build_prompt_no_mention_no_note():
    """When no @mention, no mention note appears in system prompt."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    history = [
        {"from": "agent-1", "iteration": "iter-1", "content": "my proposal"},
        {"from": "agent-2", "iteration": "iter-1", "content": "looks good to me"},
    ]
    messages = build_prompt(agent, iteration, history)
    system = messages[0]["content"]
    assert "specifically addressed you" not in system


# --- pass_turn filtering ---

def test_build_prompt_pass_turn_filtered_from_prompt():
    """Messages with pass_turn flag should be excluded from agent prompt."""
    agent = {"name": "agent-1", "system_prompt": "You are an engineer."}
    iteration = {
        "id": "iter-1", "description": "Build a thing.",
        "status": "in-progress", "max_turns": 10,
    }
    history = [
        {"from": "agent-2", "iteration": "iter-1", "content": "my proposal"},
        {"from": "system", "iteration": "iter-1", "content": "(agent-1 passes: agree)", "pass_turn": True},
        {"from": "agent-2", "iteration": "iter-1", "content": "continuing"},
    ]
    messages = build_prompt(agent, iteration, history)
    # pass_turn message should not appear in any message content
    all_content = " ".join(m["content"] for m in messages)
    assert "passes: agree" not in all_content
