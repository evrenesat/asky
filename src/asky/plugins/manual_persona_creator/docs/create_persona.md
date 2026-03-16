+++
title = "Creating a Persona"
summary = "Learn how to create a new persona from scratch with initial offline sources."

[fields]
persona_name = "Unique ID for the persona. Lowercase alphanumeric and dashes only."
behavior_prompt = "Markdown definition of the persona's voice and constraints."
initial_sources = "Ground the persona's knowledge with books or manual files."
+++

# Creating a Persona

Creating a persona allows you to define a specific identity, worldview, and behavior for the terminal assistant. 

## Requirements

To create a persona, you must provide:
- **Persona Name**: A unique identifier. Must be lowercase alphanumeric (with dashes/underscores).
- **Behavior Prompt**: A non-empty markdown file or text block that defines how the persona should act.
- **Initial Sources**: At least one initial offline source (authored book or manual source) is required to ground the persona's knowledge.

## Metadata
An optional **Description** can be added to help identify the persona's purpose in the listing.

## Workflow
1. Choose a unique name that satisfies `^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$`.
2. Define the behavior in a prompt.
3. Stage your initial sources.
4. Submit to create the persona and start the ingestion jobs.
