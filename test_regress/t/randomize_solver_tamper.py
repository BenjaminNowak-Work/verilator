#!/usr/bin/env python3
# DESCRIPTION: Verilator: real SMT solver reply wrapper for resilience tests
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of either the GNU Lesser General Public License Version 3,
# or the Perl Artistic License Version 2.0.
# SPDX-FileCopyrightText: 2026 Wilson Snyder
# SPDX-License-Identifier: LGPL-3.0-only OR Artistic-2.0
#
# Forwards the SMT-LIB conversation to a real solver, tampering the replies.
#
# Input arguments from environment variables:
# TAMPER: bad_base | bad_digits | bad_index | bad_value | bare_hash | binary
#         | core_junk | crlf | die_at | die_status_at | diversity_model
#         | dup_model | err_assume | err_core | err_multiline | err_once
#         | err_phase | err_reply | err_trunc | err_unbal | err_unbal_cont
#         | garbage_assume | garbage_at | garbage_model | garbage_status
#         | high_digit | indent | low_digit | model_trunc | multiline | mute_at
#         | no_digits | none | octal | oor_assume | phase_model | phase_trunc
#         | short_model | stale_assume | success | unknown_once | unknown_twice
#         | unknown_var | unsat_recheck | unsupported_once | upper_hex
#   bad_base         - replace the Nth model reply with a base character that is not b, o, x or h
#   bad_digits       - replace the Nth model reply with one value holding digits outside its base
#   bad_index        - replace the first array model reply with a bad select index
#   bad_value        - replace the Nth model reply with one well-formed value lacking a base
#   bare_hash        - replace the Nth model reply with one value that is only "#"
#   binary           - replace the Nth model reply with binary values
#   core_junk        - prepend garbage to the core reply and close the pipe
#   crlf             - end every line with CRLF
#   die_at           - kill the solver at the Nth model reply and exit, closing every pipe end
#   die_status_at    - kill the solver at the Nth status line and exit, closing every pipe end
#   diversity_model  - replace the Nth array model reply with one holding an unusable value
#   dup_model        - replace the Nth model reply with one answering a variable twice
#   err_assume       - replace the first unsat-assumptions reply with (error ...)
#   err_core         - replace the first unsat-core reply with (error ...)
#   err_multiline    - answer the Nth status with an (error ...) split over two lines
#   err_once         - answer the Nth status with one (error ...) line
#   err_phase        - replace the first phase value reply with (error ...)
#   err_reply        - replace the Nth S-expression reply with (error ...)
#   err_trunc        - answer the Nth status with an unterminated (error and close the pipe
#   err_unbal        - answer the Nth status with an error closing an extra paren
#   err_unbal_cont   - answer the Nth status with an error, the extra paren on a continuation line
#   garbage_assume   - answer the unsat assumptions with a non-S-expression word
#   garbage_at       - replace every Nth model reply with a non-S-expression line
#   garbage_model    - replace the Nth model reply with a partly valid one
#   garbage_status   - replace the Nth status with a word that is not a status
#   high_digit       - replace the Nth model reply with a digit valid only in a wider base
#   indent           - prepend whitespace to every reply line
#   low_digit        - replace the Nth model reply with a character below any digit or letter
#   model_trunc      - answer the Nth model with an unterminated reply and close the pipe
#   multiline        - split every S-expression reply one token per line
#   mute_at          - close the reply pipe at the Nth model reply but keep this wrapper running
#   no_digits        - replace the Nth model reply with a value whose base has no digits
#   none             - forward every reply unchanged
#   octal            - replace the Nth model reply with octal values
#   oor_assume       - answer the unsat assumptions with an out-of-range literal
#   phase_model      - replace the final phased model reply with (error ...)
#   phase_trunc      - answer an unterminated phase value reply and close the pipe
#   short_model      - replace the Nth model reply with one omitting a requested variable
#   stale_assume     - answer every unsat assumptions reply from the Nth with the literal __Va0
#   success          - echo a print-success line before every reply
#   unknown_once     - answer the Nth status with unknown
#   unknown_twice    - answer two statuses with unknown
#   unknown_var      - replace the Nth model reply with one naming a variable never requested
#   unsat_recheck    - answer the status that follows an unsat with sat
#   unsupported_once - answer the Nth status with unsupported
#   upper_hex        - replace the Nth model reply with uppercase hex digits
# TAMPER_AT: reply index to act on (default 3)
# TAMPER_ONCE: file marking that the tamper already acted. The runtime restarts
#   a solver that died, which starts this wrapper again, so without the file a
#   mode acts once per solver rather than once per simulation.

# pylint: disable=C0103,C0114,consider-using-with

import os
import re
import shutil
import subprocess
import sys
import time

mode = os.environ.get("TAMPER", "none")
at = int(os.environ.get("TAMPER_AT", "3"))
once = os.environ.get("TAMPER_ONCE", "")

# Modes acting on the TAMPER_AT'th status line rather than the Nth model reply
STATUS_MODES = ("die_status_at", "err_multiline", "err_once", "err_trunc", "err_unbal",
                "err_unbal_cont", "garbage_status", "unknown_once", "unknown_twice",
                "unsupported_once")
# Modes acting on the TAMPER_AT'th S-expression reply of any kind
REPLY_MODES = ("err_reply", )
# Modes acting on an array model reply, which arrives as (select ...) terms
SELECT_MODES = ("bad_index", "diversity_model")
# Modes acting on the status the solver sends after answering unsat
RECHECK_MODES = ("unsat_recheck", )
# phase_model acts on the final phased model; the others on any phase value reply
PHASE_MODES = ("err_phase", "phase_model", "phase_trunc")
# Modes acting on an unsat-assumptions reply, which lists __Va<N> literals
ASSUME_MODES = ("err_assume", "garbage_assume", "oor_assume", "stale_assume")
# Modes acting on an unsat-core reply, which lists __Vcons<N> names
CORE_MODES = ("core_junk", "err_core")
# Modes rewriting every line, so they never consume the index
STREAM_MODES = ("crlf", "indent", "indexed_literals", "multiline", "success")


def real_solver():
    """Return argv for the first SMT solver found in PATH"""
    for cmd in (["z3", "-in"], ["cvc5", "--incremental"], ["cvc4", "--lang=smt2",
                                                           "--incremental"]):
        if shutil.which(cmd[0]):
            return cmd
    sys.exit("randomize_solver_tamper.py: no SMT solver found")


proc = subprocess.Popen(real_solver(), stdin=sys.stdin, stdout=subprocess.PIPE, text=True)


def emit(text):
    """Write one reply line downstream, unbuffered"""
    sys.stdout.write(text + ("\r\n" if mode == "crlf" else "\n"))
    sys.stdout.flush()


def forward(text, at_start):
    """Pass a real reply through, applying the whole-stream rewrites"""
    # Solvers echo success per command, so never inside a wrapped S-expression
    if mode == "success" and at_start:
        emit("success")
    if mode == "indexed_literals":
        text = re.sub(LITERAL_PATTERN, indexed_literal, text)
    if mode == "multiline" and text.startswith("(") and not text.startswith("(error"):
        for tok in text.split():
            emit(tok)
    elif mode == "indent":
        emit(" \t" + text)
    else:
        emit(text)


def scan_depth(text, left, in_string):
    """Paren depth, ignoring delimiters inside SMT strings and quoted symbols."""
    for char in text:
        if in_string:
            in_string = False if char == in_string else in_string
        elif char in ('"', '|'):
            in_string = char
        elif char == "(":
            left += 1
        elif char == ")":
            left -= 1
    return left, in_string


def read_full(first):
    """Return the complete S-expression reply that starts at first"""
    chunks = [first]
    left, in_string = scan_depth(first, 0, False)
    while left > 0:
        cont = proc.stdout.readline()
        if not cont:
            break
        chunks.append(cont.rstrip("\n"))
        left, in_string = scan_depth(cont, left, in_string)
    return chunks


def swallow(first):
    """Drop the rest of a real S-expression reply that was replaced"""
    read_full(first)


# Explicit test-local mutations for the exact-width and phased reply cases.
# These replace one real get-value reply; the solver still evaluates every query.
PHASE_REPLIES = {
    "phase_typed_const":
    "((x (_ bv5 7)) (za ((as const (Array (_ BitVec 32) (_ BitVec 7))) (_ bv0 7))))",
    "phase_typed_store":
    "((x (_ bv5 7)) (za (store ((as const (Array (_ BitVec 32) (_ BitVec 7)))"
    " (_ bv0 7)) (_ bv1 32) (_ bv3 7))))",
    "phase_typed_let":
    "((x (_ bv5 7)) (za (let ((|a)| ((as const (Array (_ BitVec 32) (_ BitVec 7)))"
    " (_ bv0 7)))) (store |a)| (_ bv1 32) (_ bv3 7)))))",
    "phase_typed_bad_sort":
    "((x (_ bv5 7)) (za ((as const (Array (_ BitVec 31) (_ BitVec 7))) (_ bv0 7))))",
    "phase_typed_bad_leaf":
    "((x (_ bv5 7)) (za ((as const (Array (_ BitVec 32) (_ BitVec 7))) (_ bv0 8))))",
    "phase_typed_bad_index":
    "((x (_ bv5 7)) (za (store ((as const (Array (_ BitVec 32) (_ BitVec 7)))"
    " (_ bv0 7)) (_ bv1 31) (_ bv3 7))))",
    "phase_indexed_let":
    "((x (let ((|v| (_ bv5 7))) v)) (z (_ bv6 15)))",
    "phase_quoted_paren":
    "((x (let ((|v)| #b0000101)) |v)|)) (z #b000000000000110))",
    "phase_let_nested":
    "((x (let ((v #b0000101)) (let ((v #b0000000) (|w| v)) w)))"
    " (z #b000000000000110))",
    "phase_huge_sort":
    "((x (_ bv0 1048576)) (z #b000000000000110))",
    "phase_noncanonical":
    "((x (_ bv05 7)) (z #b000000000000110))",
    "phase_indexed_wrong_width":
    "((x (_ bv5 8)) (z #b000000000000110))",
    "phase_indexed":
    "((x (_ bv5 7)) (z (_ bv6 15)))",
    "phase_indexed_overflow":
    "((x (_ bv128 7)) (z (_ bv6 15)))",
    "phase_reordered":
    "((z #b000000000000110) (|x| #b0000101))",
    "phase_array":
    "((x ((as const (Array (_ BitVec 32) (_ BitVec 7))) #b0000101))"
    " (z #b000000000000110))",
    "phase_duplicate":
    "((x #b0000101) (|x| #b0000101))",
    "phase_empty":
    "()",
    "phase_extra":
    "((x #b0000101) (z #b000000000000110) (other #b0))",
    "phase_let":
    "((|x| (let ((|v| #b0000101)) v)) (z #b000000000000110))",
    "phase_let_duplicate":
    "((x (let ((v #b0000101) (|v| #b0000101)) v))"
    " (z #b000000000000110))",
    "phase_let_reserved":
    "((x (let ((let #b0000101)) let)) (z #b000000000000110))",
    "phase_let_simultaneous":
    "((x (let ((v #b0000101) (w v)) w))"
    " (z #b000000000000110))",
    "phase_missing":
    "((x #b0000101))",
    "phase_unknown":
    "((other #b0000101) (z #b000000000000110))",
    "phase_width":
    "((x #b00000101) (z #b000000000000110))",
}

LITERAL_PATTERN = r"(?:#[bx][0-9a-fA-F]+|\(\s*_\s+bv[0-9]+\s+[0-9]+\s*\))"


def literal_value(text):
    """Read width/value from a real binary, hexadecimal or indexed SMT literal."""
    if text.startswith('#'):
        digits = text[2:]
        return len(digits) * (1 if text[1] == 'b' else 4), int(digits, 2 if text[1] == 'b' else 16)
    match = re.fullmatch(r"\(\s*_\s+bv([0-9]+)\s+([0-9]+)\s*\)", text)
    assert match, "Expected one valid real bit-vector literal"
    return int(match[2]), int(match[1])


def literal_binary(text):
    """Preserve value and width when spelling a real literal in binary."""
    width, value = literal_value(text)
    return '#b' + format(value, '0' + str(width) + 'b')


def binary_literal(match):
    """Rewrite one matched real literal without changing its value or width."""
    return literal_binary(match.group(0))


def indexed_literal(match):
    """Spell one real bit-vector literal in indexed SMT-LIB notation."""
    width, value = literal_value(match.group(0))
    return '(_ bv' + str(value) + ' ' + str(width) + ')'


def select_scalar(reply):
    """Answer exactly one real scalar as a select, including a quoted scalar name."""
    rewritten, count = re.subn(r'\((?:a|\|a\|)\s+', '((select a #x00000000) ', reply, count=1)
    assert count == 1 and rewritten != reply, "Expected one real scalar shape mutation"
    return rewritten


def alternate_literal(match):
    """Give the same bits in another supported notation to test canonical identity."""
    width, value = literal_value(match.group(0))
    return ('(_ bv' + str(value) + ' ' + str(width) +
            ')' if match.group(0).startswith('#b') else binary_literal(match))


def rewrite_index(reply, change):
    """Change exactly one real q index, regardless of the solver's literal notation."""
    pattern = r'((?:q|\|q\|)\s+)(' + LITERAL_PATTERN + r')'
    rewritten, count = re.subn(pattern,
                               lambda match: match[1] + change(*literal_value(match[2])),
                               reply,
                               count=1)
    assert count == 1 and rewritten != reply, "Expected one changed real array index"
    return rewritten


def model_pairs(reply):
    """Split a real model into its top-level pairs without splitting select terms."""
    pairs = []
    nesting = 0
    start = 0
    quoted = ''
    for pos, char in enumerate(reply):
        if quoted:
            if char == quoted:
                quoted = ''
        elif char in ('"', '|'):
            quoted = char
        elif char == "(":
            if nesting == 1:
                start = pos
            nesting += 1
        elif char == ")":
            nesting -= 1
            if nesting == 1:
                pairs.append(reply[start:pos + 1])
    assert not quoted and nesting == 0 and pairs, "Expected a complete real model"
    return pairs


def duplicate_element(reply):
    """Answer one array element twice with hex and binary spelling of its index."""
    pairs = model_pairs(reply)
    duplicate = re.sub(LITERAL_PATTERN, alternate_literal, pairs[0])
    return "(" + " ".join(pairs + [duplicate]) + ")"


def extend_array_value(reply):
    """Make the last element invalid after every earlier element has parsed."""
    pairs = model_pairs(reply)
    pairs[-1], count = re.subn(r'(' + LITERAL_PATTERN + r')\s*\)$',
                               lambda match: '#b0' + literal_binary(match[1])[2:] + ')', pairs[-1])
    assert count == 1, "Expected the last real array value in a supported notation"
    return "(" + " ".join(pairs) + ")"


def rewrite_width(reply, name, change):
    """Make exactly one real scalar value the wrong width in a supported notation."""
    pattern = r'\((?:' + name + r'|\|' + name + r'\|)\s+(' + LITERAL_PATTERN + r')\s*\)'
    rewritten, count = re.subn(
        pattern, lambda match: '(' + name + ' #b' + change(literal_binary(match[1])[2:]) + ')',
        reply)
    assert count == 1 and rewritten != reply, "Expected one changed requested scalar"
    return rewritten


EXACT_REWRITES = {
    "array_binary":
    lambda reply: re.sub(LITERAL_PATTERN, binary_literal, reply),
    "array_duplicate":
    duplicate_element,
    "array_index_width":
    lambda reply: rewrite_index(
        reply, lambda width, value: '#b' + format(value, '0' + str(width + 1) + 'b')),
    "array_scalar":
    lambda reply: "((q #b1010101))",
    "array_unknown_index":
    lambda reply: rewrite_index(reply, lambda width, value: '#b' + '1' * width),
    "array_value_width":
    extend_array_value,
    "width_disabled":
    lambda reply: rewrite_width(reply, "b", lambda digits: "0" + digits),
    "width_long":
    lambda reply: rewrite_width(reply, "g", lambda digits: "0" + digits),
    "width_scalar_select":
    select_scalar,
    "width_indexed":
    lambda reply: re.sub(LITERAL_PATTERN, indexed_literal, reply),
    "width_quoted":
    lambda reply: re.sub(r'\(([a-g])\s+', lambda match: '(|' + match[1] + '| ', reply),
    "width_short":
    lambda reply: rewrite_width(reply, "g", lambda digits: digits[1:]),
}


def record_mutation(original_reply, mutated_reply):
    """Keep test-local evidence that the intended real reply was replaced."""
    assert original_reply != mutated_reply, "Reply mutation must change the real response"
    record = os.environ.get("TAMPER_LOG", "")
    if record:
        with open(record, "a", encoding="utf-8") as mutation_log:
            mutation_log.write("MODE=" + mode + "\nCHANGED=1\nREAL=" + original_reply +
                               "\nREPLY=" + mutated_reply + "\n")


replies = 0
seen_unsat = False
done = bool(once) and os.path.exists(once)
depth = 0  # Paren depth of the reply being forwarded, so wrapped ones stay intact
inside = False  # Inside an SMT string literal, where parens do not nest

for line in proc.stdout:
    line = line.rstrip("\n")
    at_reply_start = depth == 0
    depth, inside = scan_depth(line, depth, inside)
    is_status = line in ("sat", "unsat", "unknown")
    if mode in STATUS_MODES:
        counted = is_status
    elif mode in REPLY_MODES:
        # Only a first line opens a reply; a wrapped continuation is not a new one
        counted = at_reply_start and line.startswith("(")
    elif mode in SELECT_MODES:
        counted = at_reply_start and line.startswith("(((select")
    elif mode in RECHECK_MODES:
        counted = is_status and seen_unsat
    elif mode in PHASE_MODES or mode in PHASE_REPLIES:
        counted = at_reply_start and re.match(
            r'^\s*\(\s*\(\s*(?:x|y|z|za|\|x\||\|y\||\|z\||\|za\|)\s', line) is not None
    elif mode in ASSUME_MODES:
        counted = at_reply_start and re.match(r"\(__Va\d", line) is not None
    elif mode in CORE_MODES:
        counted = at_reply_start and line.startswith("(__Vcons")
    else:
        counted = at_reply_start and line.startswith("((")
    if line == "unsat":
        seen_unsat = True
    if counted:
        replies += 1
    acting = counted and replies >= at and not done and mode not in STREAM_MODES
    if not acting:
        forward(line, at_reply_start)
        continue
    if once:
        with open(once, "w", encoding="utf-8"):
            pass

    done = True

    if mode in EXACT_REWRITES or mode in PHASE_REPLIES:
        original = " ".join(read_full(line))
        replacement = (PHASE_REPLIES[mode]
                       if mode in PHASE_REPLIES else EXACT_REWRITES[mode](original))
        if replacement == original:
            assert mode in ('array_binary', 'width_indexed', 'width_quoted', 'phase_indexed',
                            'phase_reordered', 'phase_let', 'phase_indexed_let',
                            'phase_quoted_paren', 'phase_let_nested', 'phase_typed_const',
                            'phase_typed_store',
                            'phase_typed_let'), "Fault mutation unexpectedly unchanged"
            # A solver already using this valid notation still exercises reply framing.
            replacement = ' ' + replacement + ' '
        record_mutation(original, replacement)
        emit(replacement)
        depth = 0
        inside = False
        continue

    if mode == "bad_base":
        emit("((a #z01) (b #x12))")
        swallow(line)
        continue
    if mode == "bad_digits":
        emit("((a #x0b) (b #xgg))")
        swallow(line)
        continue
    if mode == "bad_index":
        emit("(((select q #xgg) #x15) ((select q #x00000001) #x15)"
             " ((select q #x00000002) #x15))")
        swallow(line)
        continue
    # A well-formed reply whose second value is unusable: the first must not
    # reach the variable either
    if mode == "bad_value":
        emit("((a #x0b) (b bogus))")
        swallow(line)
        continue
    if mode == "bare_hash":
        emit("((a #x0b) (b #))")
        swallow(line)
        continue
    if mode == "binary":
        emit("((a #b00001011) (b #b00010010))")
        swallow(line)
        continue
    if mode == "core_junk":
        emit("junk((__Vcons0))")
        proc.kill()
        proc.wait()
        sys.exit(0)
    # The base model comes first, so a later one belongs to a diversity round
    if mode == "diversity_model":
        emit("(((select q #x00000000) bogus))")
        swallow(line)
        continue
    if mode == "dup_model":
        emit("((a #x0b) (a #x0c) (b #x05))")
        swallow(line)
        continue
    if mode == "err_assume":
        emit('(error "injected assumptions error")')
        swallow(line)
        continue
    if mode == "err_core":
        emit('(error "injected core error")')
        swallow(line)
        continue
    if mode == "err_multiline":
        emit('(error "injected')
        emit('multiline error")')
        continue
    if mode == "err_once":
        emit('(error "injected command rejected")')
        continue
    # The first phase value reply always precedes the final phased model
    if mode == "err_phase":
        emit('(error "injected phase value error")')
        swallow(line)
        continue
    if mode == "err_reply":
        emit('(error "injected reply error")')
        swallow(line)
        continue
    if mode == "err_trunc":
        emit('(error "unterminated')
        proc.kill()
        proc.wait()
        sys.exit(0)
    if mode == "err_unbal":
        emit('(error "unbalanced"))')
        continue
    if mode == "err_unbal_cont":
        emit('(error "unbalanced"')
        emit('))')
        continue
    if mode == "garbage_assume":
        emit("junk")
        swallow(line)
        continue
    # garbage_at repeats, so it re-arms instead of latching
    if mode == "garbage_at":
        replies = 0
        done = False
        emit("junk")
        continue
    if mode == "garbage_model":
        emit("((a #x0b) junk)")
        swallow(line)
        continue
    if mode == "garbage_status":
        emit("flurble")
        continue
    if mode == "high_digit":
        emit("((a #x0b) (b #b2))")
        swallow(line)
        continue
    if mode == "low_digit":
        emit("((a #x0b) (b #x!))")
        swallow(line)
        continue
    if mode == "model_trunc":
        emit("((a #x0b)")
        proc.kill()
        proc.wait()
        sys.exit(0)
    if mode == "no_digits":
        emit("((a #x0b) (b #x))")
        swallow(line)
        continue
    if mode == "octal":
        emit("((a #o13) (b #o12))")
        swallow(line)
        continue
    if mode == "oor_assume":
        emit("(__Va99999999999999)")
        swallow(line)
        continue
    # Only the final phase queries every variable, so only that reply names y
    if mode == "phase_model":
        replies = 0  # Re-arm until the final phase is seen
        done = False
        parts = read_full(line)
        if "(y " in " ".join(parts):
            emit('(error "injected phased model error")')
        else:
            for part in parts:
                forward(part, part is parts[0])
        continue
    if mode == "phase_trunc":
        emit("((x")
        proc.kill()
        proc.wait()
        sys.exit(0)
    if mode == "short_model":
        emit("((a #x0b))")
        swallow(line)
        continue
    # Naming the already dropped __Va0 leaves the real conflict in place, so every round
    # stays unsat up to the round limit; it keeps acting instead of latching
    if mode == "stale_assume":
        done = False
        emit("(__Va0)")
        swallow(line)
        continue
    if mode == "unknown_once":
        record_mutation(line, "unknown")
        emit("unknown")
        continue
    if mode == "unknown_twice":
        emit("unknown")
        done = replies >= at + 1
        continue
    if mode == "unknown_var":
        emit("((zzz #x01) (b #x12))")
        swallow(line)
        continue
    # Every re-solve answers the same way, so this re-arms instead of latching
    if mode == "unsat_recheck":
        replies = 0
        seen_unsat = False
        done = False
        emit("sat")
        continue
    if mode == "unsupported_once":
        emit("unsupported")
        continue
    if mode == "upper_hex":
        emit("((a #xAB) (b #x12))")
        swallow(line)
        continue
    forward(line, at_reply_start)

    if mode in ("die_at", "die_status_at"):
        proc.kill()
        proc.wait()
        sys.exit(0)
    if mode == "mute_at":
        os.close(1)
        proc.kill()
        proc.wait()
        parent = os.getppid()
        while os.getppid() == parent:
            time.sleep(0.05)
        sys.exit(0)
