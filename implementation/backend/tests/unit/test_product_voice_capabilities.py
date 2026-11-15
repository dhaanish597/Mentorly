import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.models.api_schemas import CreateSessionRequest, STTRequest, TTSRequest
from backend.app.models.enums import LanguageMode
from backend.app.speech.audio_utils import generate_sine_wav_bytes
from backend.app.speech.gnani_adapter import GnaniSpeechAdapter, GnaniTransportError, build_ws_stt_init_frame
from backend.app.speech.routes import router

def test_product_voice_resolver_rejects_invalid_and_respects_independent_preferences():
    from backend.app.speech.capabilities import resolve_tts_selection, session_tts_selection, speech_capabilities
    for locale in LOCALES:
        result=resolve_tts_selection(locale)
        assert result['language']==locale and result['voice']=='Avinash'
    assert resolve_tts_selection('hi-IN,en-IN')['language']=='auto'
    assert resolve_tts_selection('hi-IN,en-IN',spoken_language='bn-IN',voice='Shivani')['language']=='bn-IN'
    assert resolve_tts_selection('en-IN',spoken_language='auto')['language']=='auto'
    assert session_tts_selection({'language_mode':'ta-IN,en-IN'})['language']=='auto'
    assert session_tts_selection({'language_mode':'hi-IN','spoken_language':'bn-IN','voice':'Shivani'})['voice']=='Shivani'
    assert session_tts_selection({})['language']=='en-IN'
    with pytest.raises(ValueError):
        resolve_tts_selection(model='timbre-v2.5')
    with pytest.raises(ValueError):
        resolve_tts_selection(voice='Nalini')
    assert speech_capabilities()['configured'] is False


LOCALES = ('en-IN', 'hi-IN', 'ta-IN', 'te-IN', 'kn-IN', 'ml-IN', 'bn-IN', 'gu-IN', 'mr-IN', 'pa-IN')
VOICES = ('Avinash', 'Shivani', 'Lakshmi', 'Kalpana', 'Shubham', 'Prakash', 'Devansh', 'Yashraj', 'Chetana', 'Vasudha', 'Riyaa', 'Tarika', 'Harshad')


@pytest.mark.parametrize('locale', LOCALES + ('ta-IN,en-IN', 'hi-IN,en-IN', 'bn-IN,en-IN'))
def test_product_voice_declared_languages(locale):
    req = STTRequest(session_id='test', language_mode=locale)
    form, _ = GnaniSpeechAdapter(api_key='test-only').build_rest_stt_form_fields(req)
    assert form['language_code'] == locale
    assert form['format'] == ('codemix' if ',' in locale else 'transcribe')
    assert build_ws_stt_init_frame(req)['format'] == form['format']


@pytest.mark.parametrize('locale', ['xx-IN', 'te-IN,en-IN', 'auto'])
def test_product_voice_rejects_invented_stt_codes(locale):
    with pytest.raises(ValidationError):
        STTRequest(session_id='test', language_mode=locale)


@pytest.mark.parametrize('voice', VOICES)
def test_product_voice_declared_tts_voices(voice):
    assert TTSRequest(session_id='test', text='Hello', voice=voice).voice == voice


@pytest.mark.parametrize('patch', [{'voice': 'Invented'}, {'model': 'timbre-v2'}, {'language': 'xx-IN'}])
def test_product_voice_rejects_unsupported_tts_configuration(patch):
    with pytest.raises(ValidationError):
        TTSRequest(session_id='test', text='Hello', **patch)


def test_product_voice_optional_session_selection():
    base = dict(exercise_id='ex1_shortest_subarray', spec_version='v1_positive_only')
    assert CreateSessionRequest(**base).language_mode == LanguageMode.EN_IN
    assert CreateSessionRequest(**base, voice='Shivani', spoken_language='bn-IN').spoken_language == 'bn-IN'


def test_product_voice_registry_is_public_configuration_not_live_probe():
    app = FastAPI()
    app.state.settings = Settings(
        gnani_api_key='DO_NOT_EXPOSE',
        groq_api_key=None,
        database_url=None,
        gnani_max_concurrency=8,
        gnani_verified_concurrency=1,
    )
    app.include_router(router, prefix='/api/v1')
    with TestClient(app) as client:
        response = client.get('/api/v1/speech/capabilities')
    assert response.status_code == 200
    body = response.json()
    assert body['live_unverified'] is True
    assert {item['code'] for item in body['languages']} == set(LOCALES)
    assert {item['id'] for item in body['voices']} == set(VOICES)
    assert all(item['documented'] and item['live_unverified'] for item in body['languages'])
    assert all(set(item['compatible_voices']) == set(VOICES) for item in body['languages'])
    assert body['limits']['requested_concurrency'] == 8
    assert body['limits']['effective_concurrency'] == 1
    assert 'DO_NOT_EXPOSE' not in response.text


@pytest.mark.parametrize('body', [{}, {'success': True}, {'result': 'invented fallback'}, {'transcript': None}, {'text': 5}, {'success': False, 'text': 'no'}])
def test_product_voice_stt_requires_declared_transcript_field(body):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
            adapter = GnaniSpeechAdapter(api_key='test-only', http_client=client)
            with pytest.raises(GnaniTransportError):
                await adapter.transcribe_rest(STTRequest(session_id='test'), generate_sine_wav_bytes(duration_sec=.1))
    asyncio.run(scenario())


@pytest.mark.parametrize('body', [{'transcript': ''}, {'text': 'Hello'}, {'transcript': 'বাংলা'}])
def test_product_voice_stt_accepts_silence_and_declared_text_fields(body):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
            result = await GnaniSpeechAdapter(api_key='test-only', http_client=client).transcribe_rest(STTRequest(session_id='test'), generate_sine_wav_bytes(duration_sec=.1))
            assert result.raw_transcript == next(iter(body.values()))
    asyncio.run(scenario())
