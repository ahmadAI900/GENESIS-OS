import os, requests
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('OPENROUTER_API_KEY')

resp = requests.get(
    'https://openrouter.ai/api/v1/models',
    headers={'Authorization': f'Bearer {key}'},
    timeout=30,
)
data = resp.json()
models = data.get('data', [])
free = [m for m in models if ':free' in m.get('id', '')]
print(f"Total models: {len(models)}")
print(f"Free models: {len(free)}")
for m in free[:20]:
    print(f"  {m['id']}")
