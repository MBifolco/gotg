from gotg.scaffold import DEFAULT_SYSTEM_PROMPT, PHASE_PROMPTS, COACH_FACILITATION_PROMPT


def build_prompt(
    agent_config: dict,
    iteration: dict,
    history: list[dict],
    all_participants: list[dict] | None = None,
    groomed_summary: str | None = None,
    tasks_summary: str | None = None,
) -> list[dict]:
    agent_name = agent_config["name"]
    task = iteration["description"]

    # Build system message — use agent's custom prompt if set, otherwise the default
    system_prompt = agent_config.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
    system_parts = [system_prompt]

    system_parts.append(f"Your name is {agent_name}.")

    if all_participants:
        teammates = [p for p in all_participants if p["name"] != agent_name]
        if teammates:
            teammate_list = ", ".join(
                f"{p['name']} ({p['role']})" for p in teammates
            )
            system_parts.append(f"Your teammates are: {teammate_list}.")

        # Coach awareness: tell engineers how to interact with the coach
        if any(p.get("role") == "Agile Coach" for p in teammates):
            system_parts.append(
                "Your team has an Agile Coach who facilitates the conversation. "
                "The coach will periodically summarize agreements, track unresolved "
                "items, and suggest what to discuss next. You can make suggestions "
                "to the coach, point out omissions in their summaries, and push back "
                "on their conclusions — but generally allow the coach to take the "
                "lead in organizing the group. Focus your energy on the substance "
                "of the discussion, not on process management."
            )

    system_parts.append(
        "You may get messages from more than one teammate at a time. "
        'You\'ll know because a teammate\'s message will be prefixed by '
        '"[teammate-name] add the following to the conversation:"'
    )

    system_parts.append(
        "When addressing a specific teammate, use @name. "
        f"Watch for messages directed at you with @{agent_name}."
    )

    system_parts.append(f"Current task: {task}")

    phase = iteration.get("phase")
    if phase:
        phase_prompt = PHASE_PROMPTS.get(phase)
        if phase_prompt:
            system_parts.append(phase_prompt)

    if groomed_summary:
        system_parts.append("GROOMED SCOPE SUMMARY:\n\n" + groomed_summary)

    if tasks_summary:
        system_parts.append("TASK LIST:\n\n" + tasks_summary)

    system_content = "\n\n".join(system_parts)

    messages = [{"role": "system", "content": system_content}]

    if not history:
        messages.append({
            "role": "user",
            "content": f"The task is: {task}. What are your initial thoughts?",
        })
    else:
        # Consolidate consecutive non-self messages into a single user message
        pending_parts = []
        for msg in history:
            if msg["from"] == agent_name:
                # Flush any pending user parts first
                if pending_parts:
                    messages.append({
                        "role": "user",
                        "content": "\n\n".join(pending_parts),
                    })
                    pending_parts = []
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                prefixed = (
                    f"[{msg['from']}] add the following to the conversation:\n"
                    f"{msg['content']}"
                )
                pending_parts.append(prefixed)

        # Flush remaining user parts
        if pending_parts:
            messages.append({
                "role": "user",
                "content": "\n\n".join(pending_parts),
            })

    return messages


def build_coach_prompt(
    coach_config: dict,
    iteration: dict,
    history: list[dict],
    all_participants: list[dict] | None = None,
    groomed_summary: str | None = None,
    tasks_summary: str | None = None,
) -> list[dict]:
    """Build prompt for the coach facilitator during conversation."""
    coach_name = coach_config["name"]
    task = iteration["description"]

    system_parts = [COACH_FACILITATION_PROMPT]
    system_parts.append(f"Your name is {coach_name}.")

    if all_participants:
        teammates = [p for p in all_participants if p["name"] != coach_name]
        if teammates:
            teammate_list = ", ".join(
                f"{p['name']} ({p['role']})" for p in teammates
            )
            system_parts.append(f"The team members are: {teammate_list}.")

    system_parts.append(f"Current task: {task}")

    if groomed_summary:
        system_parts.append("GROOMED SCOPE SUMMARY:\n\n" + groomed_summary)

    if tasks_summary:
        system_parts.append("TASK LIST:\n\n" + tasks_summary)

    system_content = "\n\n".join(system_parts)
    messages = [{"role": "system", "content": system_content}]

    if not history:
        messages.append({
            "role": "user",
            "content": f"The team is about to discuss: {task}. Introduce yourself briefly.",
        })
    else:
        pending_parts = []
        for msg in history:
            if msg["from"] == coach_name:
                if pending_parts:
                    messages.append({
                        "role": "user",
                        "content": "\n\n".join(pending_parts),
                    })
                    pending_parts = []
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                prefixed = (
                    f"[{msg['from']}] add the following to the conversation:\n"
                    f"{msg['content']}"
                )
                pending_parts.append(prefixed)

        if pending_parts:
            messages.append({
                "role": "user",
                "content": "\n\n".join(pending_parts),
            })

    return messages
