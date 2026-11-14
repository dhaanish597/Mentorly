"""Public projection of versioned authored scenarios."""
from backend.app.studio.scenario_content import CONTENT
SCENARIOS = {key: {'id': key, 'title': value['title'], 'mode': value['learning_mode'], 'version': value['scenario_version'], 'difficulty': value['difficulty'], 'estimated_minutes': value['estimated_minutes']} for key,value in CONTENT.items()}
