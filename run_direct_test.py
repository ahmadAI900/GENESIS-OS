import os, requests, time
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('OPENROUTER_API_KEY')
print(f'Key: {key[:10]}...' if key else 'No key')

resp = requests.post(
    'https://openrouter.ai/api/v1/chat/completions',
    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
    json={
        'model': 'google/gemma-4-31b-it:free',
        'messages': [{'role': 'user', 'content': 'Say hello in JSON format only. No other text.'}],
        'max_tokens': 50,
    },
    timeout=30,
)
print(f'Status: {resp.status_code}')
data = resp.json()
if 'choices' in data:
    print(f'Response: {data["choices"][0]["message"]["content"]}')
elif 'error' in data:
    print(f'Error: {data["error"]}')
    if 'metadata' in data['error']:
        print(f'Metadata: {data["error"]["metadata"]}')
