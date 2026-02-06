from gotg.scaffold import DEFAULT_SYSTEM_PROMPT


def build_prompt(
    agent_config: dict,
    iteration: dict,
    history: list[dict],
    all_participants: list[dict] | None = None,
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

    system_parts.append(
        "You may get messages from more than one teammate at a time. "
        'You\'ll know because a teammate\'s message will be prefixed by '
        '"[teammate-name] add the following to the conversation:"'
    )

    system_parts.append(f"Current task: {task}")
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
