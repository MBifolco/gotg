def build_prompt(
    agent_config: dict,
    iteration: dict,
    history: list[dict],
    all_participants: list[dict] | None = None,
) -> list[dict]:
    agent_name = agent_config["name"]
    task = iteration["description"]

    # Build system message
    system_parts = [agent_config["system_prompt"]]

    if all_participants:
        teammates = [p for p in all_participants if p["name"] != agent_name]
        if teammates:
            teammate_list = ", ".join(
                f"{p['name']} ({p['role']})" for p in teammates
            )
            system_parts.append(f"Your teammates: {teammate_list}")

    system_parts.append(f"Current task: {task}")
    system_content = "\n\n".join(system_parts)

    messages = [{"role": "system", "content": system_content}]

    if not history:
        messages.append({
            "role": "user",
            "content": f"The task is: {task}. What are your initial thoughts?",
        })
    else:
        for msg in history:
            if msg["from"] == agent_name:
                messages.append({"role": "assistant", "content": msg["content"]})
            else:
                prefixed = f"[{msg['from']}]: {msg['content']}"
                messages.append({"role": "user", "content": prefixed})

    return messages
