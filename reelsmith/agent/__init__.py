"""The api engine of `reelsmith run`: a provider-neutral agent loop over the OpenAI-compatible Chat Completions API.

tools.py turns the reelsmith tools, guarded file tools and web search into function tools; client.py talks to the
endpoint; loop.py drives the conversation; providers.py says who serves it (OpenRouter, DeepSeek, OpenAI or any
compatible server) and what it costs.
"""
