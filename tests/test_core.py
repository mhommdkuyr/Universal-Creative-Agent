from ucoa import UniversalCreativeAgent
from ucoa.action_protocol import encode_android_action
from ucoa.models import Action

def test_replication_route():
    r=UniversalCreativeAgent().run('انسخ أسلوب هذا الفيديو في CapCut',target='CapCut',reference_url='https://example.com/ref.mp4',media_type='video',project_id='20')
    assert r['route']=='creative_replication'
    assert r['blueprint']['fidelity']=='high'
    types=[e.action.type for e in r['events']]
    assert types[-1]=='render_final'

def test_android_protocol():
    assert '"action": "tap"' in encode_android_action(Action('tap',args={'x':1,'y':2}))

def test_browser_route():
    assert UniversalCreativeAgent().run('افتح المتصفح وابحث عن الصفحة',target='chrome')['route']=='browser_automation'

def test_coding_route():
    assert UniversalCreativeAgent().run('برمج تطبيقًا ثم شغّل الاختبارات',target='VS Code')['route']=='software_engineering'
