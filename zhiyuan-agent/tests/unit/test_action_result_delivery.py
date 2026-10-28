import asyncio
import json
import logging

import pytest

from app.gateway.event_store import EventTooLarge
from app.gateway.session_runtime import ConnectionChannel
from app.gateway.ui_events import SessionKey, UiEvent
from app.server import _action_result_payload, _native_event_frame

KEY = SessionKey('1', '3')

class BoundedStore:
    def __init__(self):
        self.events = []

    async def append(self, key, event):
        if len(json.dumps(event, ensure_ascii=False).encode()) + 64 > 16384:
            raise EventTooLarge('private-result-body-must-not-be-logged')
        numbered = UiEvent.model_validate({**event, 'protocolVersion':1, 'sessionId':key.session_id,
                           'streamEpoch':'epoch-real', 'sequence':len(self.events)+1})
        self.events.append(numbered)
        return numbered

    async def watermark(self, key):
        return len(self.events)

    async def current_epoch(self, key):
        return 'epoch-real'

@pytest.mark.asyncio
async def test_large_business_receipt_stays_a_replayable_v1_action_result():
    store = BoundedStore()
    delivered = asyncio.Queue()
    channel = ConnectionChannel(delivered.put, store=store, frame_builder=_native_event_frame)
    channel.bind_session(KEY)
    channel.bind_turn('confirm-turn')
    channel.start()
    action = {
        'actionStatus': 'applied', 'proposalRef': 'server-pending', 'newStateVersion': 5,
        'origin': 'user', 'actionType': 'move_units', 'scope': 'plan', 'code': '0', 'message': '已生效',
        'reviewState': {'checks': [{'details': '详细审查'*5000}]},
        'actualChanges': [{'detail': '详细差异'*5000}],
        'receipt': {'operationId': 'server-operation', 'reorderedCount': 1,
                    'postconditionSatisfied': True, 'internalDetail': 'private'*5000},
    }
    payload = _action_result_payload({'snapshotVersion':5}, action)
    await channel.emit({'type':'conversationAction.result', 'payload':payload})
    frame = await asyncio.wait_for(delivered.get(), 1)
    await channel.close()
    assert frame['type'] == 'conversationAction.result'
    assert frame['protocolVersion'] == 1 and frame['sequence'] == 1
    assert len(store.events) == 1
    assert frame['payload']['actionStatus'] == 'applied'
    assert frame['payload']['proposalRef'] == 'server-pending'
    assert frame['payload']['newStateVersion'] == 5
    assert frame['payload']['requiresWorkspaceReload'] is True
    assert frame['payload']['receipt'] == {
        'operationId':'server-operation','reorderedCount':1,'postconditionSatisfied':True}
    assert 'reviewState' not in frame['payload'] and 'actualChanges' not in frame['payload']
    assert len(json.dumps(frame, ensure_ascii=False).encode()) < 4096

@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable', [False, True])
async def test_any_store_failure_emits_explicit_v1_resync_without_legacy_or_private_logs(caplog, unavailable):
    store = BoundedStore()
    if unavailable:
        async def fail(*args):
            raise RuntimeError('private-result-body-must-not-be-logged')
        store.append = fail
        store.current_epoch = fail
        store.watermark = fail
    delivered = asyncio.Queue()
    channel = ConnectionChannel(delivered.put, store=store, frame_builder=_native_event_frame)
    channel.bind_session(KEY)
    channel.bind_turn('turn-x')
    channel.start()
    with caplog.at_level(logging.ERROR):
        await channel.emit({'type':'tool.progress','payload':{'label':'private-result-body-must-not-be-logged'*1000}})
        frame = await asyncio.wait_for(delivered.get(),1)
    await channel.close()
    assert frame['type']=='session.resync'
    assert frame['protocolVersion']==1 and frame['sequence']==0
    assert frame['sessionId']=='3' and frame['turnId']=='turn-x'
    assert frame['payload']['baseline']['reason']=='event_store_append_failed'
    assert frame['payload']['baseline']['lastSequence']==0
    assert len(store.events)==0
    assert 'event_store_append_failed' in caplog.text
    assert 'private-result-body-must-not-be-logged' not in caplog.text
    assert frame['streamEpoch']==('' if unavailable else 'epoch-real')

def test_action_result_strings_are_bounded_and_unknown_receipt_fields_omitted():
    payload = _action_result_payload({}, {'actionStatus':'failed','proposalRef':'p',
        'message':'长'*50000,'reviewState':{'huge':'x'*50000},'receipt':{'operationId':'op','rawResponse':'private'*5000}})
    assert len(json.dumps(payload,ensure_ascii=False).encode())<4096
    assert payload['message'].endswith('…')
    assert payload['receipt']=={'operationId':'op'}


@pytest.mark.asyncio
async def test_store_outage_preserves_action_identity_in_resync_baseline(caplog):
    store = BoundedStore()
    async def fail(*args):
        raise RuntimeError('private-claim-value')
    store.append = fail
    delivered = asyncio.Queue()
    channel = ConnectionChannel(delivered.put, store=store, frame_builder=_native_event_frame)
    channel.bind_session(KEY)
    channel.bind_turn('confirm-turn')
    channel.start()
    with caplog.at_level(logging.ERROR):
        await channel.emit({'type':'conversationAction.result','payload':{
            'proposalRef':'actual-server-pending','actionStatus':'applied','newStateVersion':5,
            'reviewState':{'raw':'private-claim-value'}}})
        frame = await asyncio.wait_for(delivered.get(),1)
    await channel.close()
    assert frame['type']=='session.resync' and frame['sequence']==0
    assert frame['payload']['baseline']['actionResult']=={
        'proposalRef':'actual-server-pending','actionStatus':'applied','newStateVersion':5}
    assert 'private-claim-value' not in json.dumps(frame) and 'private-claim-value' not in caplog.text
