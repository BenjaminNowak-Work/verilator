#!/usr/bin/env python3
# DESCRIPTION: Verilator: Verilog Test driver/expect definition
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of either the GNU Lesser General Public License Version 3
# or the Perl Artistic License Version 2.0.
# SPDX-FileCopyrightText: 2026 Wilson Snyder
# SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0

import vltest_bootstrap

from randomize_phase_solver import PhaseCase

test.scenarios('simulator')

if not test.have_solver:
    test.skip("No constraint solver installed")

test.compile()

test.execute()

# The original checks run unchanged above. These Verilator-only rows validate
# attempt-local retained bases with actual solver commands and test-local replies.
if test.vlt_all:
    cases = [
        PhaseCase('empty'),
        PhaseCase('compatible', group='compatible'),
        PhaseCase('priority', group='priority'),
        PhaseCase('soft_unknown', group='compatible', mutation='soft_unknown', setups=3),
        PhaseCase('probe_unknown', group='priority', mutation='probe_unknown', setups=3),
        PhaseCase('late_unknown', group='priority', mutation='late_unknown', setups=3),
        PhaseCase('soft_fail', group='compatible', mutation='soft_fail', setups=3),
        PhaseCase('probe_fail', group='priority', mutation='probe_fail', setups=3),
        PhaseCase('late_fail', group='priority', mutation='late_fail', reject=1, checks=4),
        PhaseCase('incompatible_fail', group='priority', mutation='soft_fail', reject=1, checks=4),
        PhaseCase('xor_unknown', mutation='xor_unknown'),
        PhaseCase('xor_unsat', mutation='xor_unsat'),
        PhaseCase('xor_fail', mutation='xor_fail'),
        PhaseCase('optional_bad', mutation='optional_bad', reject=1, checks=4),
        PhaseCase('optional_fail', mutation='optional_fail', reject=1, checks=4),
        PhaseCase('optional_trunc', mutation='optional_trunc', reject=1, checks=4),
        PhaseCase('mandatory_unknown', mutation='mandatory_unknown', reject=1, checks=5),
        PhaseCase('mandatory_fail', mutation='mandatory_fail', reject=1, checks=5),
        PhaseCase('first_unknown', mutation='mandatory_first_unknown', reject=1, checks=4),
        PhaseCase('final_unknown', mutation='mandatory_final_unknown', reject=1),
        PhaseCase('first_fail', mutation='mandatory_first_fail', reject=1, checks=4),
        PhaseCase('final_fail', mutation='mandatory_final_fail', reject=1),
        PhaseCase('solver_sampler', solver_sampler=True, setups=6),
        PhaseCase('cycle', group='cycle', setups=6, checks=16),
        PhaseCase('cycle_solver', group='cycle', solver_sampler=True, setups=16, checks=16),
        PhaseCase('isolation', group='isolation', setups=4, checks=12),
    ]
    for case in cases:
        trace = test.obj_dir + '/phase_' + case.name + '.jsonl'
        latch = test.obj_dir + '/phase_' + case.name + '.latch'
        test.unlink_ok(trace)
        test.unlink_ok(latch)
        flags = [
            '+PHASE_BASE', '+MODE=' + case.group, '+REJECT=' + str(case.reject),
            '+ALLOW_FALLBACK=' + str(case.allow_fallback)
        ]
        if case.solver_sampler:
            flags.append('+verilator+rand+sampler+solver')
        test.execute(logfile=test.obj_dir + '/sim_' + case.name + '.log',
                     all_run_flags=flags,
                     run_env='VERILATOR_SOLVER="' + test.t_dir + '/randomize_phase_solver.py" ' +
                     'PHASE_MUTATE=' + case.mutation + ' PHASE_TRACE="' + trace + '" ' +
                     'PHASE_LATCH="' + latch + '"')
        case.validate(trace)

test.passes()
