from ollama import Client

# NOTE: Figure this out

client = Client()

messages = [
  {
    'role': 'user',
    'content': 'Why is the sky blue?',
  },
]

for part in client.chat('qwen3:8b', messages=messages, stream=True):
  print(part.message.content, end='', flush=True)
