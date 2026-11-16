// DESCRIPTION: Verilator: Verilog Test module
//
// This file ONLY is placed under the Creative Commons Public Domain.
// SPDX-FileCopyrightText: 2026 PlanV GmbH
// SPDX-License-Identifier: CC0-1.0

// verilog_format: off
`define stop $stop
`define checkd(gotv,expv) do if ((gotv) !== (expv)) begin $write("%%Error: %s:%0d:  got=%0d exp=%0d\n", `__FILE__,`__LINE__, (gotv), (expv)); `stop; end while(0);
`define checkh(gotv,expv) do if ((gotv) !== (expv)) begin $write("%%Error: %s:%0d:  got=%0x exp=%0x\n", `__FILE__,`__LINE__, (gotv), (expv)); `stop; end while(0);
// verilog_format: on

// Model and diversity assumption replies
class Packet;
  rand bit [7:0] a;
  rand bit [7:0] b;
  constraint c {
    a > 8'd10;
    b < 8'd200;
    a != b;
  }
endclass

// Soft constraint relaxation replies
class Softy;
  rand bit [7:0] s;
  constraint sc {
    soft s == 8'd42;
    s > 8'd100;
  }
endclass

// Phased solve...before replies
class Phased;
  rand bit [3:0] x;
  rand bit [3:0] y;
  constraint order_c {solve x before y;}
  constraint rel_c {y > x;}
endclass

// Array element replies, which arrive as (select ...) terms
class Arr;
  rand bit [7:0] q[3];
  constraint ac {foreach (q[i]) q[i] > 8'd20;}
endclass

// Unsatisfiable, so the unsat core is queried
class Unsat;
  rand bit [7:0] u;
  constraint uc {
    u > 8'd200;
    u < 8'd100;
  }
endclass

// Diversity pin round replies: the soft constraint keeps this off the UniGen2 sampler,
// and any random target bit differing from the fixed value is a conflicting assumption
class Pinned;
  rand bit [6:0] v;
  constraint pc {
    v == 7'h55;
    soft v[0] == 1'b1;
  }
endclass

// Exact-width model replies span the scalar storage boundaries.
class ExactWidths;
  rand bit [6:0] a;
  rand bit [14:0] b;
  rand bit [30:0] c;
  rand bit [32:0] d;
  rand bit [62:0] e;
  rand bit [64:0] f;
  rand bit [94:0] g;
  bit disabled;
  constraint wc {
    a == 7'h55;
    b == (disabled ? 15'h0 : 15'h5555);
    c == 31'h55555555;
    d == 33'h155555555;
    e == 63'h5555555555555555;
    f == 65'h15555555555555555;
    g == 95'h555555555555555555555555;
  }
endclass

// Different bounds on each axis still name the same solver elements.
class ExactArray;
  rand bit [6:0] q[3:1][0:1];
  constraint qc {foreach (q[i, j]) q[i][j] == 7'(i * 2 + j + 32);}
endclass

// Two requested terms make omissions and duplicate identities observable.
class ExactPhase;
  rand bit [6:0] x;
  rand bit [14:0] z;
  rand bit [30:0] y;
  constraint pc {
    solve x, z before y;
    x == 7'd5;
    z == 15'd6;
    y == 31'd11;
    soft y == 31'd11;
  }
endclass

class ExactTypedArray;
  rand bit [6:0] x;
  rand bit [6:0] za[];
  rand bit [14:0] y;
  constraint tc {
    za.size() == 0;
    solve x, za before y;
    foreach (za[i]) za[i] == 7'd3;
    x == 7'd5;
    y == 15'd6;
    soft x == 7'd5;
  }
endclass

module t;
  task automatic typed_arrays;
    automatic ExactTypedArray p = new;
    automatic bit reject = 0;
    automatic int rc;
    void'($value$plusargs("REJECT=%d", reject));
    p.za = new[0];
    // Array-size solving can commit before this reply; these rows check sorts,
    // not whole-call rollback. Start with values satisfying the hard constraints.
    p.x = 7'd5;
    p.y = 15'd6;
    p.srandom(13);
    rc = p.randomize();
    `checkd(rc, reject ? 0 : 1);
    `checkd(p.x, 7'd5);
    `checkd(p.y, 15'd6);
    `checkd(p.za.size(), 0);
    rc = p.randomize();
    `checkd(rc, 1);
    `checkd(p.x, 7'd5);
    `checkd(p.y, 15'd6);
    `checkd(p.za.size(), 0);
  endtask

  task automatic exact_widths;
    automatic ExactWidths p = new;
    automatic bit reject = 0;
    automatic bit disabled = 0;
    automatic int rc;
    void'($value$plusargs("REJECT=%d", reject));
    void'($value$plusargs("DISABLED=%d", disabled));
    p.disabled = disabled != 0;
    if (disabled) p.b.rand_mode(0);
    p.a = 0;
    p.b = 0;
    p.c = 0;
    p.d = 0;
    p.e = 0;
    p.f = 0;
    p.g = 0;
    rc = p.randomize();
    `checkd(rc, reject ? 0 : 1);
    // A rejected last value must not commit any earlier scalar, including wide ones.
    `checkh(p.a, reject ? 7'h0 : 7'h55);
    `checkh(p.b, (reject || disabled) ? 15'h0 : 15'h5555);
    `checkh(p.c, reject ? 31'h0 : 31'h55555555);
    `checkh(p.d, reject ? 33'h0 : 33'h155555555);
    `checkh(p.e, reject ? 63'h0 : 63'h5555555555555555);
    `checkh(p.f, reject ? 65'h0 : 65'h15555555555555555);
    `checkh(p.g, reject ? 95'h0 : 95'h555555555555555555555555);
    // The following real, untouched model must succeed in the same simulation.
    rc = p.randomize();
    `checkd(rc, 1);
    `checkh(p.a, 7'h55);
    `checkh(p.b, disabled ? 15'h0 : 15'h5555);
    `checkh(p.c, 31'h55555555);
    `checkh(p.d, 33'h155555555);
    `checkh(p.e, 63'h5555555555555555);
    `checkh(p.f, 65'h15555555555555555);
    `checkh(p.g, 95'h555555555555555555555555);
  endtask

  task automatic exact_array;
    automatic ExactArray p = new;
    automatic bit reject = 0;
    automatic int rc;
    void'($value$plusargs("REJECT=%d", reject));
    foreach (p.q[i, j]) p.q[i][j] = 0;
    rc = p.randomize();
    `checkd(rc, reject ? 0 : 1);
    foreach (p.q[i, j]) `checkh(p.q[i][j], reject ? 7'h0 : 7'(i * 2 + j + 32));
    rc = p.randomize();
    `checkd(rc, 1);
    foreach (p.q[i, j]) `checkh(p.q[i][j], 7'(i * 2 + j + 32));
  endtask

  task automatic exact_phase;
    automatic ExactPhase p = new;
    automatic bit reject = 0;
    automatic int seed = 13;
    automatic int rc;
    void'($value$plusargs("REJECT=%d", reject));
    void'($value$plusargs("SEED=%d", seed));
    p.srandom(seed);
    p.x = 0;
    p.z = 0;
    p.y = 0;
    rc = p.randomize();
    `checkd(rc, reject ? 0 : 1);
    `checkd(p.x, reject ? 7'd0 : 7'd5);
    `checkd(p.z, reject ? 15'd0 : 15'd6);
    `checkd(p.y, reject ? 31'd0 : 31'd11);
    rc = p.randomize();
    `checkd(rc, 1);
    `checkd(p.x, 7'd5);
    `checkd(p.z, 15'd6);
    `checkd(p.y, 31'd11);
  endtask

  // t_randomize_solver_reply runs the +MODE=pins rows alone, so the replies their
  // TAMPER_AT counts start at the first Pinned call
  task automatic pin_rounds;
    automatic Pinned pn = new;
    automatic int npass = 0;
    automatic int rc;
    pn.srandom(13);
    for (int i = 0; i < 4; ++i) begin
      rc = pn.randomize();
      if (rc != 0) npass++;
      // A pin round that gives up keeps the base solution
      `checkd(pn.v, 7'h55);
    end
    $write("NPASS=%0d\n", npass);
  endtask

  initial begin : checks
    automatic Packet p = new;
    automatic Softy s = new;
    automatic Phased ph = new;
    automatic Arr ar = new;
    automatic Unsat un = new;
    automatic int npass = 0;
    automatic int rc;
    if ($test$plusargs("MODE=typed_arrays")) begin
      typed_arrays();
      $write("*-* All Finished *-*\n");
      $finish;
      disable checks;
    end
    if ($test$plusargs("MODE=widths")) begin
      exact_widths();
      $write("*-* All Finished *-*\n");
      $finish;
      disable checks;
    end
    if ($test$plusargs("MODE=array")) begin
      exact_array();
      $write("*-* All Finished *-*\n");
      $finish;
      disable checks;
    end
    if ($test$plusargs("MODE=phase")) begin
      exact_phase();
      $write("*-* All Finished *-*\n");
      $finish;
      disable checks;
    end
    if ($test$plusargs("MODE=pins")) begin
      pin_rounds();
      $write("*-* All Finished *-*\n");
      $finish;
      // $finish ends the run only after this process stops, so leave before the checks
      disable checks;
    end
    for (int i = 0; i < 4; ++i) begin
      // Below the constraint, so any model the runtime applies overwrites it
      p.a = 8'd5;
      rc = p.randomize();
      // A randomize that failed must leave the variable alone
      if (rc != 0) npass++;
      else `checkd(p.a, 8'd5);
      rc = s.randomize();
      if (rc != 0) npass++;
      rc = ph.randomize();
      if (rc != 0) npass++;
      ar.q[0] = 8'd7;
      rc = ar.randomize();
      if (rc != 0) npass++;
      else `checkd(ar.q[0], 8'd7);
      rc = un.randomize();
      `checkd(rc, 0);  // zero-ok: constraints are unsatisfiable
    end
    $write("NPASS=%0d\n", npass);
    $write("*-* All Finished *-*\n");
    $finish;
  end
endmodule
