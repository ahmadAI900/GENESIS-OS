import os, requests, time
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('OPENROUTER_API_KEY')

# Try 5 times with 15-second gaps
for attempt in range(5):
    print(f"\nAttempt {attempt+1}/5 (waiting 15s)...")
    time.sleep(15)
    
    resp = requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        json={
            'model': 'google/gemma-4-31b-it:free',
            'messages': [{'role': 'user', 'content': 'Say hello in JSON format only.'}],
            'max_tokens': 50,
        },
        timeout=30,
    )
    
    if resp.status_code == 200:
        data = resp.json()
        if 'choices' in data:
            print(f"  SUCCESS: {data['choices'][0]['message']['content']}")
            break
    elif resp.status_code == 429:
        data = resp.json()
        err = data.get('error', {})
        meta = err.get('metadata', {})
        reset = meta.get('X-RateLimit-Reset', 'unknown')
        print(f"  429 - Rate limited. Reset: {reset}")
    else:
        print(f"  Status {resp.status_code}: {resp.text[:200]}")
