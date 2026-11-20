import hashlib, json
from datetime import datetime, timezone
from app.config import RULE_VERSION

def digest(raw, context, mapping_version):
    return hashlib.sha256(raw + json.dumps(context,ensure_ascii=False,sort_keys=True).encode() + RULE_VERSION.encode() + mapping_version.encode()).hexdigest()

def make_manifest(source_digest, source, elapsed, mapping_version):
    return {'run_id':source_digest[:16], 'sha256':source_digest, 'rule_version':RULE_VERSION,
            'mapping_version':mapping_version,
            'source':source, 'generated_at':datetime.now(timezone.utc).isoformat(),
            'elapsed_ms':round(elapsed*1000,3), 'timezone':'Asia/Shanghai'}
