#!/usr/bin/env python3
# DESCRIPTION: Verilator: test-local phase solver conversation and reply mutations
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of either the GNU Lesser General Public License Version 3,
# or the Perl Artistic License Version 2.0.
# SPDX-FileCopyrightText: 2026 Wilson Snyder
# SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0
"""Forward actual queries to a real solver; mutate explicitly selected test replies."""

from dataclasses import dataclass, field
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Optional, TextIO


@dataclass
class SExpression:
    """Collect complete fixture expressions, respecting quoted delimiters."""

    parts: list[str] = field(default_factory=list)
    depth: int = 0
    quote: str = ''

    def append(self, line: str) -> bool:
        """Return whether the expression has reached its closing delimiter."""
        self.parts.append(line.strip())
        for char in line:
            if self.quote:
                if char == self.quote:
                    self.quote = ''
            elif char in ('"', '|'):
                self.quote = char
            elif char == '(':
                self.depth += 1
            elif char == ')':
                self.depth -= 1
        return self.depth == 0 and not self.quote

    @property
    def text(self) -> str:
        """Normalize whitespace only between collected lines."""
        return ' '.join(self.parts)


def expressions(stream: TextIO):
    """Yield complete fixture commands without changing their tokens."""
    expression = SExpression()
    for line in stream:
        if not expression.parts and (not line.strip() or line.lstrip().startswith(';')):
            continue
        if expression.append(line):
            yield expression.text
            expression = SExpression()
    if expression.parts:
        raise ValueError('Unterminated test solver command')


def read_reply(stream: TextIO) -> str:
    """Read a real status or balanced reply, skipping harmless echoes."""
    expression = SExpression()
    while line := stream.readline():
        if not expression.parts and (not line.strip() or line.strip() == 'success'):
            continue
        if expression.append(line):
            return expression.text
    raise EOFError('Real solver closed its reply stream')


@dataclass
class SolverFrame:
    """Assertions owned by one actual SMT push frame."""

    role: str = 'candidate'
    pins: dict[str, str] = field(default_factory=dict)
    softs: list[str] = field(default_factory=list)


@dataclass
class PhaseProtocol:
    """Track actual stack operands and registered fixture scalar pins."""

    setup: int = 0
    frames: list[SolverFrame] = field(default_factory=lambda: [SolverFrame('base')])
    pending: str = 'startup'
    soft_checks: int = 0
    model_kind: str = 'baseline'
    optional_pending: bool = False

    @property
    def pins(self) -> dict[str, str]:
        """Return pins still active in the solver's actual scope stack."""
        return {name: value for frame in self.frames for name, value in frame.pins.items()}

    @property
    def phase(self) -> int:
        """Boundary label; the oracle separately checks the expected query sequence."""
        return 3 if 'y' in self.pins else 2 if 'x' in self.pins else 1

    def snapshot(self) -> dict:
        """Record independent state receipts before and after each command."""
        return {
            'depth': len(self.frames) - 1,
            'pins': self.pins,
            'roles': [frame.role for frame in self.frames],
            'softs': [soft for frame in self.frames for soft in frame.softs]
        }

    def change_scope(self, action: str, command: str) -> None:
        """Honor the actual push/pop arity; never assume a one-frame operation."""
        match = re.fullmatch(r'\((push|pop) ([0-9]+)\)', command)
        assert match, 'Invalid fixture scope command'
        count = int(match[2])
        if action == 'push':
            self.frames.extend(SolverFrame() for _ in range(count))
        else:
            assert count < len(self.frames), 'Pop below solver root'
            if count:
                del self.frames[-count:]

    def observe(self, command: str) -> str:
        """Classify replies while recording commands and real scope transitions."""
        action = command.split()[0][1:].rstrip(')')
        if action == 'reset':
            self.frames = [SolverFrame('base')]
            self.pending = 'startup'
            self.optional_pending = False
        elif command.startswith('(set-option :produce-models'):
            self.setup += 1
            self.pending = 'base'
            self.soft_checks = 0
        elif action in ('push', 'pop'):
            self.change_scope(action, command)
        elif action == 'assert':
            self.observe_assert(command)
        elif action == 'get-value':
            kind = 'model_' + self.model_kind
            self.optional_pending = self.model_kind == 'baseline' and 'z' not in command
            return kind
        elif action.startswith('check-sat'):
            return self.observe_check()
        return action

    def observe_check(self) -> str:
        """A consumed check labels only its following model, not later phases."""
        kind = self.pending
        if kind == 'soft':
            self.soft_checks += 1
        self.model_kind = 'xor' if kind == 'xor' else 'baseline'
        self.pending = 'base'
        return kind

    def observe_assert(self, command: str) -> None:
        """Lock fixture shapes and distinguish optional sampling from narrowing."""
        frame = self.frames[-1]
        pin = re.fullmatch(r'\(assert \(= (x|y|z) (.+)\)\)', command)
        if pin:
            frame.pins[pin[1]] = pin[2]
            self.pending = 'base'
        elif self.optional_pending or '(_ extract ' in command:
            assert '(_ extract ' in command or command == '(assert (= #b1 #b1))'
            self.pending = 'xor'
            self.optional_pending = False
            if frame.role == 'candidate':
                frame.role = 'xor'
        elif frame.role in ('candidate', 'soft'):
            assert command.startswith('(assert (= #b1 '), 'Unexpected soft assertion shape'
            frame.role = 'soft'
            frame.softs.append(command)
            self.pending = 'soft'
        else:
            self.pending = 'base'


@dataclass
class ReplyMutation:
    """Select one protocol boundary per simulation, including solver restarts."""

    mode: str
    latch: str
    injected: bool = False

    def matches(self, kind: str, protocol: PhaseProtocol) -> bool:
        """Use semantic boundaries; the oracle checks the independent receipts."""
        target = self.mode.rsplit('_', 1)[0]
        soft_index = {'soft': 1, 'probe': 2, 'late': 4}.get(target)
        if soft_index:
            return kind == 'soft' and protocol.soft_checks == soft_index
        if target in ('xor', 'optional'):
            return kind == ('xor' if target == 'xor' else 'model_xor') and protocol.phase == 1
        phase = {'mandatory_first': 1, 'mandatory': 2, 'mandatory_final': 3}.get(target)
        return kind == 'base' and protocol.phase == phase

    def apply(self, reply: str, kind: str, protocol: PhaseProtocol) -> str:
        """Never change commands, forge SAT, or intercept ordinary production runs."""
        if self.injected or os.path.exists(self.latch) or not self.matches(kind, protocol):
            return reply
        replacements = {
            'unknown': 'unknown',
            'unsat': 'unsat',
            'fail': '(error "test-local rejected check")',
            'bad': '((x #b0))',
            'trunc': '((x'
        }
        replacement = replacements[self.mode.rsplit('_', 1)[1]]
        self.injected = True
        with open(self.latch, 'w', encoding='utf8') as stream:
            stream.write(self.mode + '\n')
        return replacement


def solver_argv() -> list[str]:
    """Choose an installed real SMT solver, never a substitute executable."""
    candidates = (['z3', '-in'], ['cvc5',
                                  '--incremental'], ['cvc4', '--lang=smt2', '--incremental'])
    for argv in candidates:
        if shutil.which(argv[0]):
            return argv
    raise RuntimeError('No real constraint solver installed')


def transact(solver, command: str, protocol: PhaseProtocol, mutation: ReplyMutation) -> dict:
    """Forward one actual query and retain both real and emitted reply receipts."""
    before = protocol.snapshot()
    kind = protocol.observe(command)
    solver.stdin.write(command + '\n')
    solver.stdin.flush()
    event = {
        'command': command,
        'kind': kind,
        'phase': protocol.phase,
        'setup': protocol.setup,
        'before': before,
        'after': protocol.snapshot(),
        'soft_check': protocol.soft_checks,
        'process': os.getpid()
    }
    if kind in ('startup', 'soft', 'base', 'xor') or kind.startswith('model_'):
        reply = read_reply(solver.stdout)
        if not kind.startswith('model_'):
            assert reply in ('sat', 'unsat', 'unknown'), 'Unexpected real status: ' + reply
        already = mutation.injected
        emitted = mutation.apply(reply, kind, protocol)
        event.update(real=reply,
                     emitted=emitted,
                     injected=mutation.injected and not already,
                     changed=emitted != reply)
        sys.stdout.write(emitted + '\n')
        sys.stdout.flush()
    return event


def run_proxy() -> None:
    """Run only when explicitly invoked with a private trace and latch."""
    trace_path = os.environ['PHASE_TRACE']
    mutation = ReplyMutation(os.environ.get('PHASE_MUTATE', 'none'), os.environ['PHASE_LATCH'])
    protocol = PhaseProtocol()
    with open(trace_path, 'a', encoding='utf8') as trace:
        with subprocess.Popen(solver_argv(),
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              text=True) as solver:
            for command in expressions(sys.stdin):
                event = transact(solver, command, protocol, mutation)
                trace.write(json.dumps(event, sort_keys=True) + '\n')
                trace.flush()
                if event.get('emitted') == '((x':
                    solver.terminate()
                    return
            solver.stdin.close()


def scalar_number(text):
    """Compare actual fixture scalar models and pins without notation assumptions."""
    indexed = re.fullmatch(r'\(_ bv([0-9]+) ([0-9]+)\)', text)
    if indexed:
        return int(indexed[2]), int(indexed[1])
    assert re.fullmatch(r'#[bx][0-9a-fA-F]+', text), 'Unexpected fixture scalar: ' + text
    return (len(text[2:]) * (1 if text[1] == 'b' else 4), int(text[2:],
                                                              2 if text[1] == 'b' else 16))


def model_scalars(reply):
    """Read the fixture's x/y scalar shapes; stage1 owns general reply validation."""
    pairs = re.findall(r'\((x|y) (#[bx][0-9a-fA-F]+|\(_ bv[0-9]+ [0-9]+\))\)', reply)
    return {name: scalar_number(value) for name, value in pairs}


def validate_scopes(events):
    """Require a one-frame XOR pop and unchanged retained soft frames and pins."""
    pending = None
    for event in events:
        if pending:
            if event['kind'] == 'pop':
                assert event['command'] == '(pop 1)', 'Wrong intermediate XOR pop arity'
                assert event['before']['depth'] == pending['after']['depth']
                assert event['after']['depth'] == pending['after']['depth'] - 1
                assert event['before']['roles'][-1] == 'xor'
                assert event['before']['softs'] == event['after']['softs']
                assert event['before']['pins'] == event['after']['pins']
                pending = None
            else:
                assert event['kind'] == 'model_xor', 'XOR survived into ' + event['command']
                if event.get('emitted') == '((x':
                    pending = None  # Dirty transaction discards its process, not its scope.
        if event['kind'] == 'xor' and event['phase'] < 3:
            assert event['after']['roles'][-1:] == ['xor'], 'Missing temporary XOR frame'
            pending = event
    assert pending is None, 'Unclosed intermediate XOR frame'


def validate_layer_pins(events):
    """Check expected layer queries independently of the proxy's phase label."""
    solved = {}
    expected = 'x'
    previous = {}
    for event in events:
        kind = event['kind']
        if kind == 'base':
            required = {} if expected == 'x' else solved
            active = {
                name: scalar_number(value)
                for name, value in event['before']['pins'].items()
            }
            assert active == required, ('Missing or stale mandatory pins', active, required)
            if event['emitted'] != 'sat':
                solved, expected = {}, 'x'
        elif kind == 'model_baseline':
            query = set(re.fullmatch(r'\(get-value \(([^()]*)\)\)', event['command'])[1].split())
            assert previous['kind'] == 'base' and previous['emitted'] == 'sat'
            values = model_scalars(event['emitted'])
            if expected in ('x', 'y'):
                assert query == {expected}, ('Wrong layer query', query, expected)
                solved.update(values)
                expected = 'y' if expected == 'x' else 'final'
            else:
                assert {'x', 'y', 'z'} <= query, 'Missing final model terms'
                solved, expected = {}, 'x'
        elif kind == 'model_xor' and event['phase'] < 3:
            if event['emitted'].startswith('(error') or event['emitted'] in ('((x #b0))', '((x'):
                solved, expected = {}, 'x'
            else:
                solved.update(model_scalars(event['emitted']))
        previous = event


def fixture_softs(group):
    """Lock the real frontend's predicates to the independent SV fixture semantics."""
    predicates = {
        'bare': (),
        'cycle': (),
        'isolation': (),
        'compatible': ('(bvugt w #x64)', '(bvult x #b1011010)'),
        'priority': ('(bvugt w #x64)', '(= x #b0000101)', '(= x #b0000110)', '(bvult w #x96)'),
    }[group]
    return tuple('(assert (= #b1 (__Vbv ' + predicate + ')))' for predicate in predicates)


@dataclass
class SoftSelectionOracle:
    """Certify expected soft candidates, accepted prefixes and exact scope ownership."""

    full: tuple[str, ...]
    selected: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    first: bool = True
    pop_before: Optional[dict] = None
    certificate: bool = True
    roles: list[str] = field(default_factory=lambda: ['base'])

    def fresh(self):
        """A reset starts selection anew; no accepted prefix crosses a rebuild."""
        self.selected = []
        self.queue = list(reversed(self.full))
        self.first = True
        self.pop_before = None
        self.certificate = True
        self.roles = ['base']

    def assertion(self, event):
        """Validate each real soft predicate before it reaches a selection check."""
        candidate = list(self.full) if self.first else self.queue[:1]
        offset = len(event['before']['softs']) - len(self.selected)
        assert 0 <= offset < len(candidate), 'Unexpected soft candidate assertion'
        assert event['command'] == candidate[offset], 'Wrong soft predicate or priority'
        assert event['before']['softs'] == self.selected + candidate[:offset]
        assert event['after']['softs'] == self.selected + candidate[:offset + 1]

    def check(self, event):
        """Apply exact legacy SAT/UNSAT/UNKNOWN/FAIL selection and retain receipts."""
        candidate = list(self.full) if self.first else [self.queue.pop(0)]
        assert candidate and event['before']['softs'] == self.selected + candidate
        assert event['before']['roles'] == self.roles + ['soft']
        status = event['emitted']
        self.certificate = self.certificate and status in ('sat', 'unsat')
        if status == 'sat' or status.startswith('(error'):
            self.selected.extend(candidate)
            self.roles = event['after']['roles']
            if self.first or status.startswith('(error'):
                self.queue = []
        else:
            self.pop_before = event['after']
        self.first = False

    def pop(self, event):
        """A rejected soft pops exactly its candidate, never its accepted prefix."""
        assert event['command'] == '(pop 1)', 'Wrong soft or XOR pop arity'
        if self.pop_before:
            assert event['before'] == self.pop_before
            assert event['after']['depth'] == event['before']['depth'] - 1
            assert event['after']['pins'] == event['before']['pins']
            self.pop_before = None
        self.boundary(event['after'])

    def complete(self, snapshot):
        """Every required priority decision and rejected-candidate pop must finish."""
        assert not self.queue, 'Soft selection skipped remaining candidates'
        assert self.pop_before is None, 'Soft selection left a rejected candidate active'
        self.boundary(snapshot)

    def boundary(self, snapshot):
        """The selected predicates and their frames must survive every base boundary."""
        assert snapshot['softs'] == self.selected, 'Selected soft set changed'
        assert snapshot['roles'] == self.roles, 'Selected soft frame ownership changed'


def validate_retained_base(events, group, solver_sampler):
    """Partition selection reuse, fallback rebuild and exhausted retry by attempt."""
    selection = SoftSelectionOracle(fixture_softs(group))
    selection.fresh()
    needs_fresh = True
    intermediate = False
    for event in events:
        command, kind = event['command'], event['kind']
        if kind == 'reset':
            assert needs_fresh or not intermediate, 'Certified phase base was reset'
            assert event['after'] == {'depth': 0, 'pins': {}, 'roles': ['base'], 'softs': []}
            selection.fresh()
        elif command.startswith('(set-option :produce-models'):
            assert needs_fresh, 'Certified phase setup was redeclared'
            assert event['before'] == {'depth': 0, 'pins': {}, 'roles': ['base'], 'softs': []}
            selection.fresh()
            needs_fresh = False
        elif kind == 'soft':
            selection.check(event)
        elif kind == 'pop':
            selection.pop(event)
        elif event['after']['softs'] != event['before']['softs']:
            selection.assertion(event)
        else:
            needs_fresh, intermediate = validate_attempt_boundary(event, selection, solver_sampler,
                                                                  needs_fresh, intermediate)


def validate_attempt_boundary(event, selection, solver_sampler, needs_fresh, intermediate):
    """Require retained softs even when a mandatory status rejects the attempt."""
    kind = event['kind']
    if kind == 'base':
        assert not needs_fresh, 'Phase skipped a required fresh setup'
        selection.complete(event['before'])
        if event['emitted'] != 'sat':
            return True, False
    elif kind == 'model_baseline':
        intermediate = 'z' not in event['command']
        needs_fresh = not intermediate or solver_sampler or not selection.certificate
    elif kind == 'model_xor' and (event['emitted'].startswith('(error')
                                  or event['emitted'] in ('((x #b0))', '((x')):
        return True, False
    assert event['after']['softs'] == selection.selected, 'Soft set changed between boundaries'
    return needs_fresh, intermediate


def validate_dirty_recovery(events):
    """Unreadable optional replies discard their process before another call."""
    for index, event in enumerate(events):
        if event.get('emitted') == '((x':
            assert all(later['process'] != event['process'] for later in events[index + 1:])
            assert any(later['kind'] == 'startup' for later in events[index + 1:])


def validate_injection(events, mutation):
    """Bind receipts to the chosen real query, independent of global reply indices."""
    injected = [event for event in events if event.get('injected')]
    assert len(injected) == (mutation != 'none'), (mutation, injected)
    if not injected:
        return
    event = injected[0]
    assert event['changed'], 'Mutation consumed a reply without changing it'
    target = mutation.rsplit('_', 1)[0]
    if target in ('soft', 'probe', 'late'):
        assert event['kind'] == 'soft' and event['soft_check'] == {
            'soft': 1,
            'probe': 2,
            'late': 4
        }[target]
    elif target in ('xor', 'optional'):
        assert event['kind'] == ('xor' if target == 'xor' else 'model_xor')
        assert event['phase'] == 1 and event['before']['pins'] == {}
    else:
        assert event['kind'] == 'base'
        assert set(event['before']['pins']) == {
            'mandatory_first': set(),
            'mandatory': {'x'},
            'mandatory_final': {'x', 'y'}
        }[target]


@dataclass(frozen=True)
class PhaseCase:
    """Expected operations for the fixture's three-phase calls and recovery."""

    name: str
    group: str = 'bare'
    mutation: str = 'none'
    reject: int = 0
    setups: int = 2
    checks: int = 6
    solver_sampler: bool = False

    @property
    def allow_fallback(self):
        """A rejected first greedy candidate may leave later softs unselected."""
        return int(self.mutation in ('probe_unknown', 'probe_fail'))

    def validate(self, path):
        """Derive counts and mutation positions from the actual conversation."""
        with open(path, encoding='utf8') as stream:
            events = [json.loads(line) for line in stream]
        setup_count = sum(event['command'].startswith('(set-option :produce-models')
                          for event in events)
        phase_checks = sum(event['kind'] == 'base' for event in events)
        assert setup_count == self.setups, (self.name, 'setups', setup_count, self.setups)
        assert phase_checks == self.checks, (self.name, 'phase checks', phase_checks, self.checks)
        if self.solver_sampler:
            seeds = sum(event['command'].startswith('(set-option :random-seed')
                        for event in events)
            assert seeds == self.setups, (self.name, 'seeds', seeds)
            assert not any(event['kind'] == 'xor' for event in events)
        if self.group == 'cycle':
            assert sum(event['kind'] == 'base' and event.get('real') == 'unsat'
                       for event in events) == 1, 'Missing exhausted randc attempt'
            assert any(event['command'].startswith('(assert (not (= c ') for event in events)
        validate_scopes(events)
        validate_layer_pins(events)
        validate_retained_base(events, self.group, self.solver_sampler)
        validate_dirty_recovery(events)
        validate_injection(events, self.mutation)


if __name__ == '__main__':
    run_proxy()
