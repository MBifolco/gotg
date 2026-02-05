def build_prompt(
    agent_config: dict,
    iteration: dict,
    history: list[dict],
) -> list[dict]:
    agent_name = agent_config["name"]
    task = iteration["description"]

    system_content = f"{agent_config['system_prompt']}\n\nCurrent task: {task}"
    messages = [{"role": "system", "content": system_content}]

    if not history:
        messages.append({
            "role": "user",
            "content": f"The task is: {task}. What are your initial thoughts?",
        })
    else:
        for msg in history:
            role = "assistant" if msg["from"] == agent_name else "user"
            messages.append({"role": role, "content": msg["content"]})

    return messages
