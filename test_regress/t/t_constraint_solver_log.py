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

solver_log = test.obj_dir + "/solver.log"

test.execute(all_run_flags=['+verilator+solver+file+' + solver_log])

test.file_grep(solver_log, '# Verilator solver log')
# Without array variables the solver gets QF_BV, which z3 solves incrementally faster
test.file_grep(solver_log, r'\(set-logic QF_BV\)')

# Each command and reply is logged whole, however the pipe split it
longest = 0
entries = []
with open(solver_log, encoding="utf8") as fh:
    for line in fh:
        longest = max(longest, len(line))
        # The solver prints a model of several array elements over lines it indents
        if line.startswith("<  ") and entries and entries[-1].startswith("< (("):
            entries[-1] += line
        else:
            entries.append(line)
for entry in entries:
    if entry.startswith(("  (assert", "< ((")) and entry.count("(") != entry.count(")"):
        test.error("Solver log breaks a line: " + entry[:60])
if longest <= 4096:
    test.error("No logged line is longer than a pipe buffer")

# Each operator over one element is just that element's term, never the operator
# applied to that term alone
term = r'\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)'
test.file_grep_not(solver_log, r'\((?:bvadd|bvand|bvmul|bvor|bvxor) +' + term + r'\)')
# Each collapsed form appears as the bare element term
test.file_grep(solver_log, r'\(assert \(= #b1 +\(__Vbv \(= #b0010001 x\)\)\)\)')
test.file_grep(solver_log, r'\(__Vbv \(not \(__Vbool +\(__Vbv \(= #b0010001 y\)\)\)\)\)')
for name, value in (('sum_a', '0001001'), ('prod_a', '0001010'), ('and_a', '0001011'),
                    ('or_a', '0001100'), ('xor_a', '0001101')):
    test.file_grep(solver_log,
                   r'\(__Vbv \(= +\(select ' + name + r' #x00000000\) #b' + value + r'\)\)')
ite = r'\(ite \(__Vbool sel\) +\(__Vbv \(= '
test.file_grep(solver_log, ite + r'\(select fixed #x00000000\) #b0000101\)\) #b1\)')
test.file_grep(solver_log,
               ite + r'\(select \(select grid #x00000000\) #x00000000\) #b0000110\)\) #b1\)')

test.passes()
