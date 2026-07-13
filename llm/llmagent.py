from ollama import Client

# NOTE: Figure this out, make sure responses are limited and not streamed
# NOTE: For more robust work configure a job manager which spawns a couple of agents to do this work, and add an agents field to config.py. Then let the user pick how many agents they want.

client = Client()

messages = [
  {
    'role': 'user',
    'content': 'Why is the sky blue?',
  },
]

for part in client.chat('qwen3:8b', messages=messages, stream=True):
  print(part.message.content, end='', flush=True)
