"""M0 hello agent: one LlmAgent on Groq with one tool.

M2 replaces this with the real team (specialists, commander, comms).
"""

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.genai import types

from . import config

_FAKE_UTC_OFFSETS = {"tokyo": 9, "london": 0, "new york": -5, "mumbai": 5.5}


def get_time(city: str) -> dict:
    """Return the current local time in a city.

    Args:
        city: City name, for example "Tokyo" or "New York".

    Returns:
        A dict with the city and its local time as "HH:MM", or an error
        listing the cities this tool knows.
    """
    offset = _FAKE_UTC_OFFSETS.get(city.strip().lower())
    if offset is None:
        return {"error": f"unknown city {city!r}", "known_cities": sorted(_FAKE_UTC_OFFSETS)}
    # Fixed fake clock (12:00 UTC) so answers are reproducible.
    minutes = int((12 + offset) * 60) % (24 * 60)
    return {"city": city, "local_time": f"{minutes // 60:02d}:{minutes % 60:02d}"}


root_agent = LlmAgent(
    name="hello_agent",
    description="M0 smoke test: answers time questions with one tool.",
    model=LiteLlm(model=config.FAST_MODEL, **config.GROQ_EXTRA_ARGS),
    instruction="Answer questions about the time in a city. Always use the get_time tool; never guess.",
    tools=[get_time],
    generate_content_config=types.GenerateContentConfig(
        temperature=config.SPECIALIST_TEMPERATURE,
        max_output_tokens=config.SPECIALIST_MAX_TOKENS,
    ),
    output_key="answer",
)
