import os, requests, time
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('OPENROUTER_API_KEY')

# Try a few free models
models = [
    "meta-llama/llama-3.3-8b-instruct:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
    "qwen/qwen3-8b:free",
    "google/gemma-3-12b-it:free",
]

for model in models:
    print(f"\nTrying {model}...")
    try:
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
        if resp.status_code == 200:
            data = resp.json()
            if 'choices' in data:
                print(f"  OK: {data['choices'][0]['message']['content'][:100]}")
            else:
                print(f"  200 but no choices: {data}")
        elif resp.status_code == 429:
            print(f"  429 rate limited")
        else:
            print(f"  Status {resp.status_code}")
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(2)
