"""List all registered capabilities grouped by category."""
import sys
sys.path.insert(0, '.')
from genesis_os.capability_registry import CapabilityRegistry

caps = {}
for cap in CapabilityRegistry.all():
    cat = cap.category.value if hasattr(cap.category, 'value') else str(cap.category)
    if cat not in caps:
        caps[cat] = []
    meta = cap.metadata or {}
    dangerous = meta.get("dangerous", False)
    caps[cat].append(f"  {cap.capability_id}  dangerous={dangerous}")

for cat in sorted(caps.keys()):
    print(f"\n{cat}:")
    for c in sorted(caps[cat]):
        print(c)
