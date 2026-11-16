#!/usr/bin/env python3
# DESCRIPTION: Verilator: Verilog Test driver/expect definition
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of either the GNU Lesser General Public License Version 3
# or the Perl Artistic License Version 2.0
# SPDX-FileCopyrightText: 2026 Wilson Snyder
# SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0

import vltest_bootstrap

test.scenarios('vlt')

if not test.have_solver:
    test.skip("No constraint solver installed")

test.compile()

# Each exact-reply case mutates one real get-value reply, checks whether it is
# accepted, then checks an untouched randomize() in the same simulation. The
# mutation record proves that a negative case reached the intended boundary.
exact_runs = [
    ('widths', None, 0, 0, None),
    ('widths', 'width_indexed', 0, 0, None),
    ('widths', 'width_quoted', 0, 0, None),
    ('widths', 'width_long', 1, 0, 'invalid value'),
    ('widths', 'width_short', 1, 0, 'invalid value'),
    ('widths', 'width_scalar_select', 1, 0, 'invalid array index'),
    ('widths', 'width_disabled', 1, 1, 'invalid value'),
    ('array', None, 0, 0, None),
    ('array', 'array_binary', 0, 0, None),
    ('array', 'array_duplicate', 1, 0, 'repeated variable'),
    ('array', 'array_index_width', 1, 0, 'invalid array index'),
    ('array', 'array_scalar', 1, 0, 'invalid array index'),
    ('array', 'array_unknown_index', 1, 0, 'invalid array index'),
    ('array', 'array_value_width', 1, 0, 'invalid value'),
    ('typed_arrays', None, 0, 0, None),
    ('typed_arrays', 'phase_typed_const', 0, 0, None),
    ('typed_arrays', 'phase_typed_store', 0, 0, None),
    ('typed_arrays', 'phase_typed_let', 0, 0, None),
    ('typed_arrays', 'phase_typed_bad_sort', 1, 0, 'invalid phase model'),
    ('typed_arrays', 'phase_typed_bad_leaf', 1, 0, 'invalid phase model'),
    ('typed_arrays', 'phase_typed_bad_index', 1, 0, 'invalid phase model'),
    ('phase', None, 0, 0, None),
    ('phase', 'phase_let', 0, 0, None),
    ('phase', 'phase_indexed', 0, 0, None),
    ('phase', 'phase_indexed_let', 0, 0, None),
    ('phase', 'phase_quoted_paren', 0, 0, None),
    ('phase', 'phase_let_nested', 0, 0, None),
    ('phase', 'phase_huge_sort', 1, 0, 'invalid phase model'),
    ('phase', 'phase_noncanonical', 1, 0, 'invalid phase model'),
    ('phase', 'phase_indexed_wrong_width', 1, 0, 'invalid phase model'),
    ('phase', 'phase_reordered', 0, 0, None),
    ('phase', 'phase_indexed_overflow', 1, 0, 'invalid phase model'),
    ('phase', 'phase_array', 1, 0, 'invalid phase model'),
    ('phase', 'phase_duplicate', 1, 0, 'invalid phase model'),
    ('phase', 'phase_empty', 1, 0, 'invalid phase model'),
    ('phase', 'phase_extra', 1, 0, 'invalid phase model'),
    ('phase', 'phase_let_duplicate', 1, 0, 'invalid phase model'),
    ('phase', 'phase_let_reserved', 1, 0, 'invalid phase model'),
    ('phase', 'phase_let_simultaneous', 1, 0, 'invalid phase model'),
    ('phase', 'phase_missing', 1, 0, 'invalid phase model'),
    ('phase', 'phase_unknown', 1, 0, 'invalid phase model'),
    ('phase', 'phase_width', 1, 0, 'invalid phase model'),
]

for group, mode, reject, disabled, diagnostic in exact_runs:
    name = mode or group + '_none'
    logfile = test.obj_dir + '/sim_exact_' + name + '.log'
    mutation_log = test.obj_dir + '/mutation_' + name + '.log'
    test.unlink_ok(mutation_log)
    run_env = ''
    if mode:
        run_env = ('VERILATOR_SOLVER="' + test.t_dir + '/randomize_solver_tamper.py" ' +
                   'TAMPER=' + mode + ' TAMPER_AT=1 TAMPER_LOG="' + mutation_log + '"')
    test.execute(
        logfile=logfile,
        all_run_flags=['+MODE=' + group, '+REJECT=' + str(reject), '+DISABLED=' + str(disabled)],
        run_env=run_env)
    if mode:
        test.file_grep(mutation_log, 'MODE=' + mode)
        test.file_grep(mutation_log, r'^CHANGED=1$')
    if diagnostic:
        test.file_grep(logfile, 'Unable to parse solver.s response: ' + diagnostic)

# Seed 2 gives a SAT optional trial on the first call. A malformed trial reply
# must fail that call, rather than silently keeping the earlier complete reply.
for mode, reject in [(None, 0), ('phase_missing', 1)]:
    tag = mode or 'none'
    logfile = test.obj_dir + '/sim_trial_' + tag + '.log'
    solver_log = test.obj_dir + '/solver_trial_' + tag + '.log'
    mutation_log = test.obj_dir + '/mutation_trial_' + tag + '.log'
    test.unlink_ok(mutation_log)
    run_env = ''
    if mode:
        run_env = ('VERILATOR_SOLVER="' + test.t_dir + '/randomize_solver_tamper.py" ' +
                   'TAMPER=' + mode + ' TAMPER_AT=2 TAMPER_LOG="' + mutation_log + '"')
    test.execute(logfile=logfile,
                 all_run_flags=[
                     '+MODE=phase', '+SEED=2', '+REJECT=' + str(reject),
                     '+verilator+solver+file+' + solver_log
                 ],
                 run_env=run_env)
    if mode:
        test.file_grep(mutation_log, r'^CHANGED=1$')
        test.file_grep(logfile, r"Unable to parse solver's response: invalid phase model")
        test.file_grep(
            solver_log, r'^  \(check-sat\)\n< sat\n  \(get-value \(x z \)\)\n'
            r'< \(\(x #b0000101\)\)')

# Normal and indexed replies must still enumerate witnesses, not silently fall back.
for notation in ('none', 'indexed_literals'):
    logfile = test.obj_dir + '/sim_witness_' + notation + '.log'
    solver_log = test.obj_dir + '/solver_witness_' + notation + '.log'
    test.execute(logfile=logfile,
                 all_run_flags=['+verilator+solver+file+' + solver_log],
                 run_env='VERILATOR_SOLVER="' + test.t_dir + '/randomize_solver_tamper.py" ' +
                 'TAMPER=' + notation)
    test.file_grep(logfile, r'NPASS=(\d+)', 16)
    if notation == 'indexed_literals':
        # The solver transcript records the reply the runtime actually consumed.
        test.file_grep(solver_log, r'^< .*\(_ bv[0-9]+ 8\)')
    digits = r'#b[01]+' if notation == 'indexed_literals' else r'#[bx][0-9a-fA-F]+'
    test.file_grep(solver_log, r'^  \(assert \(not \(and .*\(= a +' + digits + r'\)')

# 16 randomize calls; each entry names the reply the solver mangles
runs = [
    ('bad_base', 1, 15),  # a base character that is not b, o, x or h
    ('bad_digits', 1, 15),  # digits outside the stated base are not a number
    ('bad_index', 1, 15),  # a malformed array select index
    ('bad_value', 1, 15),  # a value with no base must not commit the earlier one
    ('bare_hash', 1, 15),  # a value that is only "#"
    ('binary', 1, 16),  # binary values
    ('core_junk', 1, 16),  # garbage opens the core reply, then the pipe closes
    ('crlf', 1, 16),  # CRLF line endings
    ('diversity_model', 2, 16),  # a diversity round answers with an unusable value
    ('dup_model', 1, 15),  # the same variable answered twice
    ('err_assume', 1, 16),  # error in place of the unsat assumptions
    ('err_core', 1, 16),  # error in place of the unsat core
    ('err_multiline', 2, 15),  # solver rejects a command with an error spanning two lines
    ('err_once', 2, 15),  # solver rejects a command instead of answering
    ('err_phase', 1, 15),  # error in place of an intermediate phase value reply
    ('err_reply', 1, 15),  # error in place of an S-expression reply
    ('err_trunc', 2, 0),  # unterminated error, then the pipe closes
    ('err_unbal', 2, 15),  # a rejection error closing more parens than it opens
    ('err_unbal_cont', 2, 15),  # a rejection error with the extra paren on a continuation line
    ('garbage_assume', 1, 16),  # a bare word in place of the unsat assumptions
    ('garbage_model', 1, 15),  # half-valid model must not reach the variables
    ('garbage_status', 2, 15),  # a word that is not a status
    ('garbage_status', 8, 15),  # a phased check-sat that does not answer with a status
    ('high_digit', 1, 15),  # a digit legal for some base but not the stated one
    ('indent', 1, 16),  # leading whitespace before every reply
    ('low_digit', 1, 15),  # a character below any digit or letter
    ('model_trunc', 1, 0),  # unterminated model, then the pipe closes
    ('multiline', 1, 16),  # S-expression split one token per line
    ('no_digits', 1, 15),  # a base marker with no digits after it
    ('octal', 1, 16),  # octal values
    ('oor_assume', 1, 16),  # unsat assumptions naming only an out-of-range literal
    ('phase_model', 1, 15),  # error in place of the final phased model
    ('phase_trunc', 1, 12),  # unterminated phase value reply, then the pipe closes
    ('short_model', 1, 15),  # a model missing a requested variable is not a model
    ('success', 1, 16),  # print-success echo ahead of every reply
    ('unknown_once', 2, 15),  # unknown answers one check-sat
    ('unknown_twice', 2, 15),  # a second unknown must not warn again
    ('unknown_var', 1, 15),  # a variable that was never requested
    ('unsupported_once', 2, 15),  # command not supported, so no status ever comes
    ('upper_hex', 1, 16),  # uppercase hex digits
]

for mode, at, npass in runs:
    logfile = test.obj_dir + '/sim_' + mode + '_' + str(at) + '.log'
    test.execute(logfile=logfile,
                 run_env='VERILATOR_SOLVER="' + test.t_dir + '/randomize_solver_tamper.py" ' +
                 'TAMPER=' + mode + ' TAMPER_AT=' + str(at))
    test.file_grep(logfile, r'NPASS=(\d+)', npass)

# 4 randomize calls through the diversity pin rounds, alone, from a fixed seed. A round
# the solver leaves unsettled keeps the base solution, so every call still passes; the
# count of check-sat-assuming rounds shows where each call's rounds stopped.
# Status 1 answers the check-sat sent when the session opens; statuses 2 and 3 are the
# soft relaxation and the base check-sat of call 1. To re-derive a TAMPER_AT, log the
# untampered +MODE=pins conversation and count the replies its mode counts.
pin_runs = [
    # Untampered: calls 1 to 4 settle after 4, 7, 5 and 4 rounds
    (None, 0, 20),
    # Status 4: the first pin round of call 1, answered unknown
    ('unknown_once', 4, 17),
    # Unsat-assumptions reply 1: the first pin round of call 1, an error leaving no core
    ('err_assume', 1, 17),
    # Unsat-assumptions reply 1: the first pin round of call 1, naming only literals out of
    # range
    ('oor_assume', 1, 17),
    # Unsat-assumptions reply 1 on: every pin round names the already dropped __Va0, so each
    # call runs out its 8 rounds, one per pin plus one
    ('stale_assume', 1, 32),
]

for mode, at, nrounds in pin_runs:
    logfile = test.obj_dir + '/sim_pins_' + str(mode) + '.log'
    solver_log = test.obj_dir + '/solver_pins_' + str(mode) + '.log'
    test.execute(logfile=logfile,
                 all_run_flags=['+MODE=pins', '+verilator+solver+file+' + solver_log],
                 run_env=('VERILATOR_SOLVER="' + test.t_dir + '/randomize_solver_tamper.py" ' +
                          'TAMPER=' + mode + ' TAMPER_AT=' + str(at)) if mode else '')
    test.file_grep(logfile, r'NPASS=(\d+)', 4)
    test.file_grep_count(solver_log, r'^  \(check-sat-assuming', nrounds)

test.passes()
