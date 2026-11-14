#!/usr/bin/env python3
# DESCRIPTION: Verilator: Verilog Test driver/expect definition
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of either the GNU Lesser General Public License Version 3
# or the Perl Artistic License Version 2.0.
# SPDX-FileCopyrightText: 2026 Wilson Snyder
# SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0

import vltest_bootstrap

test.scenarios('vlt')

if not test.have_solver:
    test.skip("No constraint solver installed")

test.compile()

# Verilator samples, so results vary
log = test.obj_dir + "/solver.log"
test.execute(all_run_flags=[
    '+verilator+rand+sampler+default', '+check_varied', '+verilator+solver+file+' + log
])
test.file_grep(log, r'; sampler: default')
# UniGen2 excludes each witness found: one equality alone, as SMT-LIB 'and' takes at least
# two operands, or one equality per element under 'and'
test.file_grep(log, r'^  \(assert \(not \(= v +#b[01]+\)\)\)$')
test.file_grep(log, r'^  \(assert \(not \(and \(= a +#b[01]+\) \(= b +#b[01]+\)\)\)\)$')
test.file_grep(
    log, r'^  \(assert \(not \(and \(= \(select q #x00000000\) +#b[01]+\)'
    r' \(= \(select q #x00000001\) +#b[01]+\) \(= \(select q #x00000002\) +#b[01]+\)\)\)\)$')
term = r'\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)'
test.file_grep_not(log, r'\(and +' + term + r'\)')

# A seed under which a UniGen2 hash equation selects no bit of Single's v: the xor of no
# bit is still an application of two operands, as SMT-LIB 'bvxor' takes at least two
log = test.obj_dir + "/solver_seed.log"
test.execute(logfile=test.obj_dir + "/sim_seed.log",
             all_run_flags=[
                 '+verilator+rand+sampler+default', '+verilator+seed+111',
                 '+verilator+solver+file+' + log
             ])
test.file_grep(log, r'\(bvxor #b0 #b0\)')
test.file_grep_not(log, r'\(bvxor +[^ ()]+\)')

test.passes()
