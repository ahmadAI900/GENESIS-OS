import os, requests, time
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('OPENROUTER_API_KEY')

# Test Gemma 4 26B
model = "google/gemma-4-26b-a4b-it:free"
print(f"Testing {model}...")

resp = requests.post(
    'https://openrouter.ai/api/v1/chat/completions',
    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
    json={
        'model': model,
        'messages': [{'role': 'user', 'content': 'Say hello in JSON format only.'}],
        'max_tokens': 50,
    },
    timeout=30,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    if 'choices' in data:
        print(f"Response: {data['choices'][0]['message']['content']}")
elif resp.status_code == 429:
    print("Rate limited")
else:
    print(resp.text[:200])
