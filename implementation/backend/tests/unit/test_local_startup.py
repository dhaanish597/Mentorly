"""Local launch environment rejects accidental credential inheritance."""
from scripts.start_local import preview_environment


def test_preview_removes_aliases_file_opt_in_and_private_secrets():
    source={'VCC_GNANI_API_KEY':'test-only','GNANI_API_KEY':'test-only','GNANI_API_KEY_ID':'test-only',
            'VCC_ENV_FILE':'private.env','VCC_OPERATIONS_TOKEN':'test-only','VCC_INTERNAL_WORKER_SECRET':'test-only',
            'VCC_ALLOW_PUBLIC_CUSTOM_CODE':'true','PATH':'safe-path'}
    result=preview_environment(source)
    assert result['VCC_GNANI_API_KEY']==''
    assert 'GNANI_API_KEY' not in result and 'VCC_ENV_FILE' not in result
    assert result['VCC_OPERATIONS_TOKEN']==''
    assert result['VCC_ALLOW_PUBLIC_CUSTOM_CODE']=='false'
    assert result['VCC_LLM_PROVIDER']=='deterministic'
    assert result['PATH']=='safe-path'
    assert source['VCC_GNANI_API_KEY']=='test-only'
