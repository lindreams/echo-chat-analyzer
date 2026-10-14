"""Protocol tests with fictional witnesses; no OS attestation or installation."""
import importlib
from dataclasses import replace

import pytest


@pytest.fixture
def core():
    name = 'qq_chat_analyzer.application.setup_update_broker'
    assert importlib.util.find_spec(name) is not None, 'P2 broker protocol is not implemented'
    return importlib.import_module(name)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Witnesses:
    """Mutable external observations, not a mock of broker admission."""
    def __init__(self, core, clock):
        self.core, self.clock = core, clock
        self.identity = core.ProcessIdentity(101, 9001, 'fictional/current/Echo.exe')
        self.owner = core.OwnerWitness(self.identity, object())
        self.installation = core.InstallationIdentity(
            'fictional', 'FictionalEcho', 'test', '0.2.0', 'a' * 64)
        self.package = core.PackageIdentity(
            'FictionalEcho', 'test', '0.2.1', 'fictional/packages/update.nupkg', 42, 'b' * 64)
        self.evidence = core.AdmissionEvidence(
            self.installation, self.package, core.Verification.VERIFIED,
            core.Verification.VERIFIED, core.Verification.VERIFIED, core.LeaseStatus.PREPARED)
        self.permit = core.ExitPermit(self.identity, 'fictional-grant', core.PermitStatus.ACTIVE)
        self.exit = core.OwnerExit(self.owner, core.WaitStatus.EXITED, 0)
        self.calls = []
        self.fail = None
        self.missing = None
        self.hook = None

    def observed(self, name, deadline):
        self.calls.append((name, deadline))
        if self.hook:
            self.hook(name)
        if self.fail == name:
            raise OSError('fictional private detail must not escape')
        return self.missing != name

    def capture_owner(self, expected, deadline):
        assert expected == self.identity
        return self.owner if self.observed('owner', deadline) else None

    def inspect(self, phase, deadline):
        if not self.observed(phase, deadline):
            return None
        return replace(self.evidence, lease=self.core.LeaseStatus.HELD) if phase == 'final' else self.evidence

    def exit_permit(self, deadline):
        return self.permit if self.observed('permit', deadline) else None

    def wait_owner(self, owner, deadline):
        assert owner is self.owner
        return self.exit if self.observed('wait', deadline) else None


@pytest.fixture
def setup(core):
    clock = Clock()
    witnesses = Witnesses(core, clock)
    grant = core.HandoffAuthorization('fictional-grant')
    calls = []
    broker = core.UpdateBroker(
        owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10.0, clock=clock, apply_recorder=lambda package: calls.append(package))
    return core, broker, witnesses, clock, grant, calls


def arm(setup):
    core, broker, *_ = setup
    assert broker.ready() is core.BrokerState.READY
    assert broker.go('fictional-grant') is core.BrokerState.GO
    assert broker.arm() is core.BrokerState.ARMED


def rejected(setup):
    core, broker, witnesses, _, grant, calls = setup
    assert broker.state is core.BrokerState.REJECTED
    assert broker.reason
    assert not grant.available
    assert calls == []
    before = list(witnesses.calls)
    # Late responses and valid-looking tokens never revive a rejected exchange.
    for invoke in (broker.ready, lambda: broker.go('fictional-grant'), broker.arm, broker.approve):
        assert invoke() is core.BrokerState.REJECTED
    assert witnesses.calls == before
    assert calls == []


def test_normal_exchange_observes_every_stage_before_one_apply(setup):
    core, broker, witnesses, _, grant, calls = setup
    arm(setup)
    assert calls == []
    assert broker.approve() is core.BrokerState.APPLY_APPROVED
    assert calls == [witnesses.package]
    assert not grant.available
    assert witnesses.calls == [
        ('owner', 10.0), ('initial', 10.0),
        ('armed', 10.0), ('permit', 10.0),
        ('wait', 10.0), ('final', 10.0), ('permit', 10.0)]
    assert broker.approve() is core.BrokerState.REJECTED
    assert calls == [witnesses.package]


@pytest.mark.parametrize('sequence', [
    ('go',), ('arm',), ('approve',), ('ready', 'ready'),
    ('ready', 'arm'), ('ready', 'approve'), ('ready', 'go', 'go'),
    ('ready', 'go', 'approve'), ('ready', 'go', 'arm', 'arm'),
    ('ready', 'go', 'arm', 'ready')])
def test_out_of_order_exchange_rejects_and_invalidates_grant(setup, sequence):
    _, broker, *_ = setup
    for operation in sequence:
        getattr(broker, operation)('fictional-grant') if operation == 'go' else getattr(broker, operation)()
    rejected(setup)


@pytest.mark.parametrize('token', ['wrong', '', None, True])
def test_wrong_token_cannot_be_retried(setup, token):
    _, broker, *_ = setup
    broker.ready()
    broker.go(token)
    rejected(setup)


def test_consumed_grant_cannot_authorize_another_exchange(setup):
    core, broker, witnesses, clock, grant, calls = setup
    broker.ready()
    broker.go('fictional-grant')
    second = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=calls.append)
    assert second.ready() is core.BrokerState.REJECTED
    assert calls == []


@pytest.mark.parametrize('change', ['absent', 'pid', 'creation', 'image', 'handle'])
def test_owner_capture_requires_exact_identity_and_handle(setup, change):
    _, broker, witnesses, *_ = setup
    if change == 'absent':
        witnesses.missing = 'owner'
    elif change == 'handle':
        witnesses.owner = replace(witnesses.owner, handle=None)
    else:
        field, value = {'pid': ('pid', 202), 'creation': ('created_at', 9002),
                        'image': ('image', 'another/Echo.exe')}[change]
        witnesses.owner = replace(witnesses.owner, identity=replace(witnesses.identity, **{field: value}))
    broker.ready()
    rejected(setup)


@pytest.mark.parametrize('change', ['failed', 'timeout', 'missing', 'code', 'bool_code', 'identity', 'handle'])
def test_exit_requires_same_process_witness_and_zero_native_code(setup, change):
    core, broker, witnesses, *_ = setup
    arm(setup)
    if change == 'failed':
        witnesses.exit = replace(witnesses.exit, status=core.WaitStatus.FAILED)
    elif change == 'timeout':
        witnesses.exit = replace(witnesses.exit, status=core.WaitStatus.TIMED_OUT)
    elif change == 'missing':
        witnesses.missing = 'wait'
    elif change in ('code', 'bool_code'):
        witnesses.exit = replace(witnesses.exit, exit_code=7 if change == 'code' else False)
    else:
        owner = replace(witnesses.owner, identity=replace(witnesses.identity, created_at=9002)) if change == 'identity' else replace(witnesses.owner, handle=object())
        witnesses.exit = replace(witnesses.exit, owner=owner)
    broker.approve()
    rejected(setup)


@pytest.mark.parametrize('stage', ['armed', 'final'])
@pytest.mark.parametrize('change', ['revoked', 'missing', 'owner', 'grant', 'boolean'])
def test_exit_permission_is_bound_and_rechecked(setup, stage, change):
    core, broker, witnesses, *_ = setup
    broker.ready()
    broker.go('fictional-grant')
    if stage == 'final':
        broker.arm()
    if change == 'revoked':
        witnesses.permit = replace(witnesses.permit, status=core.PermitStatus.REVOKED)
    elif change == 'missing':
        witnesses.missing = 'permit'
    elif change == 'owner':
        witnesses.permit = replace(witnesses.permit, owner=replace(witnesses.identity, created_at=9002))
    elif change == 'grant':
        witnesses.permit = replace(witnesses.permit, authorization='another-grant')
    else:
        witnesses.permit = True
    broker.arm() if stage == 'armed' else broker.approve()
    rejected(setup)


@pytest.mark.parametrize('stage', ['initial', 'armed', 'final'])
@pytest.mark.parametrize('field', ['installation', 'package', 'plain_paths', 'package_guard', 'conflicts', 'lease'])
def test_each_admission_witness_is_required_at_each_stage(setup, stage, field):
    core, broker, witnesses, *_ = setup
    if stage != 'initial':
        broker.ready()
        broker.go('fictional-grant')
    if stage == 'final':
        broker.arm()
    original = witnesses.inspect
    def inspect(phase, deadline):
        evidence = original(phase, deadline)
        return replace(evidence, **{field: None}) if phase == stage else evidence
    witnesses.inspect = inspect
    {'initial': broker.ready, 'armed': broker.arm, 'final': broker.approve}[stage]()
    rejected(setup)


@pytest.mark.parametrize('change', ['package_hash', 'package_path', 'package_size', 'target',
                                   'updater', 'root', 'installed_version', 'channel', 'package_id',
                                   'reparse', 'guard', 'second_instance', 'helper', 'lease', 'boolean'])
def test_final_changed_or_unverified_evidence_cannot_apply(setup, change):
    core, broker, witnesses, *_ = setup
    arm(setup)
    fields = {
        'package_hash': ('package', 'sha256', 'c' * 64),
        'package_path': ('package', 'path', 'another/update.nupkg'),
        'package_size': ('package', 'size', 43), 'target': ('package', 'version', '0.2.2'),
        'updater': ('installation', 'updater_sha256', 'c' * 64),
        'root': ('installation', 'root', 'another'),
        'installed_version': ('installation', 'version', '0.1.0'),
        'channel': ('installation', 'channel', 'other'),
        'package_id': ('installation', 'package_id', 'OtherEcho')}
    if change in fields:
        outer, inner, value = fields[change]
        witnesses.evidence = replace(witnesses.evidence,
            **{outer: replace(getattr(witnesses.evidence, outer), **{inner: value})})
    elif change == 'boolean':
        witnesses.evidence = replace(witnesses.evidence, package_guard=True)
    else:
        field = {'reparse': 'plain_paths', 'guard': 'package_guard',
                 'second_instance': 'conflicts', 'helper': 'conflicts', 'lease': 'lease'}[change]
        original = witnesses.inspect
        def inspect(phase, deadline):
            evidence = original(phase, deadline)
            return replace(evidence, **{field: core.LeaseStatus.PREPARED if field == 'lease' else core.Verification.FAILED})
        witnesses.inspect = inspect
    broker.approve()
    rejected(setup)


@pytest.mark.parametrize('operation', ['owner', 'initial', 'armed', 'permit', 'wait', 'final'])
@pytest.mark.parametrize('failure', ['exception', 'eof'])
def test_witness_errors_and_eof_are_terminal_without_retry(setup, operation, failure):
    _, broker, witnesses, *_ = setup
    witnesses.fail = operation if failure == 'exception' else None
    witnesses.missing = operation if failure == 'eof' else None
    for invoke in (broker.ready, lambda: broker.go('fictional-grant'), broker.arm, broker.approve):
        invoke()
    rejected(setup)
    assert 'private' not in broker.reason


@pytest.mark.parametrize('operation', ['owner', 'initial', 'armed', 'permit', 'wait', 'final'])
def test_late_success_does_not_extend_absolute_deadline(setup, operation):
    _, broker, witnesses, clock, *_ = setup
    witnesses.hook = lambda name: setattr(clock, 'now', 10.0) if name == operation else None
    for invoke in (broker.ready, lambda: broker.go('fictional-grant'), broker.arm, broker.approve):
        invoke()
    rejected(setup)
    assert all(deadline == 10.0 for _, deadline in witnesses.calls)


def test_time_spent_between_stages_is_not_a_fresh_budget(setup):
    _, broker, _, clock, *_ = setup
    clock.now = 3
    broker.ready()
    clock.now = 6
    broker.go('fictional-grant')
    clock.now = 9
    broker.arm()
    clock.now = 10
    broker.approve()
    rejected(setup)


@pytest.mark.parametrize('time', [float('nan'), float('inf'), -1, True])
def test_invalid_or_backwards_clock_fails_closed(setup, time):
    _, broker, _, clock, *_ = setup
    broker.ready()
    clock.now = time
    broker.go('fictional-grant')
    rejected(setup)


def test_recorder_exception_is_not_success_and_never_retried(setup):
    core, _, witnesses, clock, grant, calls = setup
    def recorder(package):
        calls.append(package)
        raise OSError('fictional apply failure')
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=recorder)
    for invoke in (broker.ready, lambda: broker.go('fictional-grant'), broker.arm, broker.approve):
        invoke()
    assert broker.state is core.BrokerState.REJECTED
    assert not grant.available
    assert calls == [witnesses.package]
    assert broker.approve() is core.BrokerState.REJECTED
    assert calls == [witnesses.package]


def test_reentrant_witness_cannot_overwrite_rejection(setup):
    _, broker, witnesses, *_ = setup
    witnesses.hook = lambda name: broker.go('fictional-grant') if name == 'initial' else None
    broker.ready()
    rejected(setup)


@pytest.mark.parametrize('change', ['pid', 'creation', 'image', 'root', 'updater_hash',
                                   'package_hash', 'size', 'bool_size', 'path', 'package_id',
                                   'channel', 'same_version', 'downgrade', 'bad_version'])
def test_invalid_expected_identity_is_not_self_attesting(setup, change):
    core, _, witnesses, clock, grant, calls = setup
    owner, installation, package = witnesses.identity, witnesses.installation, witnesses.package
    if change in ('pid', 'creation', 'image'):
        owner = replace(owner, **{'pid': 0} if change == 'pid' else
                        {'created_at': True} if change == 'creation' else {'image': ''})
        witnesses.identity = owner
        witnesses.owner = replace(witnesses.owner, identity=owner)
    elif change in ('root', 'updater_hash'):
        installation = replace(installation, **({'root': ''} if change == 'root' else {'updater_sha256': 'not-a-hash'}))
    else:
        values = {'package_hash': {'sha256': ''}, 'size': {'size': 0}, 'bool_size': {'size': True},
                  'path': {'path': ''}, 'package_id': {'package_id': 'OtherEcho'},
                  'channel': {'channel': 'other'}, 'same_version': {'version': '0.2.0'},
                  'downgrade': {'version': '0.1.0'}, 'bad_version': {'version': 'invalid'}}
        package = replace(package, **values[change])
    witnesses.evidence = replace(witnesses.evidence, installation=installation, package=package)
    broker = core.UpdateBroker(owner=owner, installation=installation, package=package,
        authorization=grant, witnesses=witnesses, deadline=10, clock=clock, apply_recorder=calls.append)
    broker.ready()
    rejected((core, broker, witnesses, clock, grant, calls))


@pytest.mark.parametrize('deadline', [0, -1, True, None, float('nan'), float('inf')])
def test_invalid_deadline_cannot_reach_ready(setup, deadline):
    core, _, witnesses, clock, grant, calls = setup
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=deadline, clock=clock, apply_recorder=calls.append)
    broker.ready()
    rejected((core, broker, witnesses, clock, grant, calls))


def test_revoke_during_wait_is_observed_before_apply(setup):
    core, broker, witnesses, *_ = setup
    arm(setup)
    def revoke(name):
        if name == 'wait':
            witnesses.permit = replace(witnesses.permit, status=core.PermitStatus.REVOKED)
    witnesses.hook = revoke
    broker.approve()
    rejected(setup)


def test_reentrant_recorder_is_attempted_once_and_cannot_restore_success(setup):
    core, _, witnesses, clock, grant, calls = setup
    def recorder(package):
        calls.append(package)
        broker.approve()
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=recorder)
    for invoke in (broker.ready, lambda: broker.go('fictional-grant'), broker.arm, broker.approve):
        invoke()
    assert broker.state is core.BrokerState.REJECTED
    assert calls == [witnesses.package]
    assert not grant.available


def test_clock_callback_cannot_restore_a_rejected_transition(setup):
    core, _, witnesses, _, grant, calls = setup
    clock = Clock()
    def reentrant_clock():
        if broker.state is core.BrokerState.GO:
            broker.ready()
        return clock()
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=reentrant_clock, apply_recorder=calls.append)
    broker.ready()
    broker.go('fictional-grant')
    before = list(witnesses.calls)
    broker.arm()
    assert broker.state is core.BrokerState.REJECTED
    assert witnesses.calls == before
    assert calls == []
    assert not grant.available


def test_build_metadata_alone_is_not_a_new_version(setup):
    core, _, witnesses, clock, grant, calls = setup
    package = replace(witnesses.package, version='0.2.0+fictional')
    witnesses.evidence = replace(witnesses.evidence, package=package)
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=calls.append)
    broker.ready()
    rejected((core, broker, witnesses, clock, grant, calls))


def test_approval_is_not_published_before_recorder_completes(setup):
    core, _, witnesses, clock, grant, calls = setup
    def recorder(package):
        assert broker.state is core.BrokerState.ARMED
        calls.append(package)
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=recorder)
    local = (core, broker, witnesses, clock, grant, calls)
    arm(local)
    assert broker.approve() is core.BrokerState.APPLY_APPROVED
    assert calls == [witnesses.package]


@pytest.mark.parametrize('stage', ['ready', 'go', 'arm', 'approve'])
def test_concurrent_rejection_after_validation_cannot_be_overwritten(setup, monkeypatch, stage):
    """Pause after the real validation, before the state/side-effect commit."""
    from threading import Event, Thread
    core, broker, _, _, grant, calls = setup
    if stage != 'ready':
        broker.ready()
    if stage in ('arm', 'approve'):
        broker.go('fictional-grant')
    if stage == 'approve':
        broker.arm()
    entered, resume = Event(), Event()
    name = {'ready': '_admission', 'go': '_consume', 'arm': '_permit',
            'approve': '_checkpoint'}[stage]
    target = grant if stage == 'go' else broker
    original = getattr(target, name)
    checkpoints = 0
    def pause(*args):
        nonlocal checkpoints
        result = original(*args)
        checkpoints += 1
        # Seven checkpoints in approve; pause only after the last one.
        final = stage != 'approve' or checkpoints == 7
        if final:
            entered.set()
            assert resume.wait(5)
        return result
    monkeypatch.setattr(target, name, pause)
    invoke = lambda: broker.go('fictional-grant') if stage == 'go' else getattr(broker, stage)()
    thread = Thread(target=invoke)
    thread.start()
    try:
        assert entered.wait(5)
        assert broker.ready() is core.BrokerState.REJECTED
    finally:
        resume.set()
        thread.join(5)
    assert not thread.is_alive()
    rejected(setup)


@pytest.mark.parametrize('location', ['capture', 'permit', 'exit', 'package'])
def test_equal_but_wrongly_typed_witness_fields_are_rejected(setup, location):
    core, broker, witnesses, *_ = setup
    if location == 'capture':
        witnesses.owner = replace(witnesses.owner,
            identity=replace(witnesses.identity, pid=float(witnesses.identity.pid)))
        broker.ready()
    elif location == 'package':
        witnesses.evidence = replace(witnesses.evidence,
            package=replace(witnesses.package, size=float(witnesses.package.size)))
        broker.ready()
    else:
        arm(setup)
        malformed = replace(witnesses.identity, created_at=float(witnesses.identity.created_at))
        if location == 'permit':
            witnesses.permit = replace(witnesses.permit, owner=malformed)
        else:
            witnesses.exit = replace(witnesses.exit,
                owner=replace(witnesses.owner, identity=malformed))
        broker.approve()
    rejected(setup)


def test_prerelease_target_is_not_a_stable_upgrade(setup):
    core, _, witnesses, clock, grant, calls = setup
    package = replace(witnesses.package, version='0.3.0-alpha')
    witnesses.evidence = replace(witnesses.evidence, package=package)
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=package, authorization=grant, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=calls.append)
    broker.ready()
    rejected((core, broker, witnesses, clock, grant, calls))


def test_revoked_shared_authorization_at_final_checkpoint_cannot_apply(setup, monkeypatch):
    _, broker, _, _, grant, _ = setup
    arm(setup)
    original = broker._checkpoint
    checkpoints = 0
    def revoke(expected):
        nonlocal checkpoints
        original(expected)
        checkpoints += 1
        if checkpoints == 7:
            grant._revoke()
    monkeypatch.setattr(broker, '_checkpoint', revoke)
    broker.approve()
    rejected(setup)


@pytest.mark.parametrize('authorization', [None, True, object()])
def test_invalid_authorization_is_terminal_without_unhandled_exception(setup, authorization):
    core, _, witnesses, clock, _, calls = setup
    broker = core.UpdateBroker(owner=witnesses.identity, installation=witnesses.installation,
        package=witnesses.package, authorization=authorization, witnesses=witnesses,
        deadline=10, clock=clock, apply_recorder=calls.append)
    assert broker.ready() is core.BrokerState.REJECTED
    assert broker.reason == 'invalid_authorization'
    assert broker.approve() is core.BrokerState.REJECTED
    assert witnesses.calls == [] and calls == []
