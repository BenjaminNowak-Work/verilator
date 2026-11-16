// DESCRIPTION: Verilator: Verilog Test module
//
// This file ONLY is placed under the Creative Commons Public Domain.
// SPDX-FileCopyrightText: 2026 PlanV GmbH
// SPDX-License-Identifier: CC0-1.0

// verilog_format: off
`define stop $stop
`define checkd(gotv,expv) do if ((gotv) !== (expv)) begin $write("%%Error: %s:%0d:  got=%0d exp=%0d\n", `__FILE__,`__LINE__, (gotv), (expv)); `stop; end while(0);
// verilog_format: on

class solve_before_soft_c;
  rand bit sel;
  rand int unsigned m;
  rand int unsigned x;
  constraint m_soft {soft m == 7;}
  constraint sb_cons {
    solve sel before x;
    if (sel)
    x == 0;
    else
    x inside {[1 : 100]};
  }
endclass

class conflicting_soft_c;
  rand bit sel;
  rand int unsigned a;
  rand int unsigned b;
  constraint a_soft3 {soft a == 3;}
  constraint a_soft9 {soft a == 9;}
  constraint sb_cons {
    solve sel before b;
    if (sel)
    b == 0;
    else
    b inside {[1 : 100]};
  }
endclass

// Three layers make retained setup, intermediate cleanup and final pins observable.
class PhaseBase;
  rand bit [6:0] x;
  rand bit [14:0] y;
  rand bit [30:0] z;
  rand bit [7:0] w;
  bit [6:0] lo = 1;
  bit [6:0] hi = 99;
  constraint order_c {
    solve x before y;
    solve y before z;
  }
  constraint hard_c {
    w < 8'd200;
    x inside {[lo : hi]};
    y == 15'(x) + 15'd1;
    z == 31'(y) + 31'd1;
  }
endclass

class CompatibleBase extends PhaseBase;
  constraint soft_c {
    soft w > 8'd100;
    soft x < 7'd90;
  }
endclass

// Priority decisions involve the first layer, not just a later free variable.
class PriorityBase extends PhaseBase;
  constraint soft_c {
    soft w > 8'd100;
    soft x == 7'd5;
    soft x == 7'd6;
    soft w < 8'd150;
  }
endclass

class CyclicBase;
  randc bit [1:0] c;
  rand bit [6:0] x;
  rand bit [14:0] y;
  rand bit [30:0] z;
  constraint cycle_c {
    solve x before y;
    solve y before z;
    c < 2'd3;
    x inside {[7'd1 : 7'd99]};
    y == 15'(x) + 15'd1;
    z == 31'(y) + 31'd1;
  }
endclass

module t;
  task automatic check_values(PhaseBase p);
    `checkd(p.w < 8'd200, 1);
    `checkd(p.x >= p.lo && p.x <= p.hi, 1);
    `checkd(p.y, 15'(p.x) + 15'd1);
    `checkd(p.z, 31'(p.y) + 31'd1);
  endtask

  task automatic check_soft_values(PhaseBase p);
    if ($test$plusargs("MODE=compatible")) begin
      `checkd(p.x < 7'd90, 1);
      `checkd(p.w > 8'd100, 1);
    end
    if ($test$plusargs("MODE=priority")) begin
      `checkd(p.x, 6);
      `checkd(p.w > 8'd100 && p.w < 8'd150, 1);
    end
  endtask

  task automatic phase_calls;
    automatic PhaseBase p;
    automatic bit reject = 0;
    automatic bit allow_fallback = 0;
    automatic int rc;
    if ($test$plusargs("MODE=compatible")) begin
      automatic CompatibleBase compatible = new;
      p = compatible;
    end
    else if ($test$plusargs("MODE=priority")) begin
      automatic PriorityBase priority_base = new;
      p = priority_base;
    end
    else begin
      p = new;
    end
    void'($value$plusargs("REJECT=%d", reject));
    void'($value$plusargs("ALLOW_FALLBACK=%d", allow_fallback));
    p.srandom(13);
    p.w = 0;
    p.x = 0;
    p.y = 0;
    p.z = 0;
    rc = p.randomize();
    `checkd(rc, reject ? 0 : 1);
    if (reject) begin
      `checkd(p.w, 0);
      `checkd(p.x, 0);
      `checkd(p.y, 0);
      `checkd(p.z, 0);
    end
    else begin
      check_values(p);
      if (!allow_fallback) check_soft_values(p);
    end
    // The same randomizer must start a new base, even after a failed phase.
    rc = p.randomize();
    `checkd(rc, 1);
    check_values(p);
    check_soft_values(p);
  endtask

  task automatic isolation_calls;
    automatic PhaseBase first = new;
    automatic PhaseBase second = new;
    automatic int rc;
    first.srandom(13);
    second.srandom(19);
    second.lo = 101;
    second.hi = 110;
    for (int iteration = 0; iteration < 2; ++iteration) begin
      rc = first.randomize();
      `checkd(rc, 1);
      check_values(first);
      rc = second.randomize();
      `checkd(rc, 1);
      check_values(second);
      // Change this object's hard set between calls with identical solver names.
      first.lo = 70;
      first.hi = 79;
    end
  endtask

  task automatic cycle_calls;
    automatic CyclicBase p = new;
    automatic bit [3:0] used = 0;
    automatic int rc;
    p.srandom(13);
    for (int iteration = 0; iteration < 5; ++iteration) begin
      rc = p.randomize();
      `checkd(rc, 1);
      `checkd(p.c < 2'd3, 1);
      `checkd(p.x >= 7'd1 && p.x <= 7'd99, 1);
      `checkd(p.y, 15'(p.x) + 15'd1);
      `checkd(p.z, 31'(p.y) + 31'd1);
      if (iteration < 3) begin
        `checkd(used[p.c], 0);
        used[p.c] = 1;
      end
    end
    `checkd(used, 4'b0111);
  endtask

  initial begin : ordinary_checks
    static solve_before_soft_c o1 = new();
    static conflicting_soft_c o2 = new();
    int randomize_result;
    if ($test$plusargs("PHASE_BASE")) disable ordinary_checks;
    repeat (20) begin
      randomize_result = o1.randomize();
      `checkd(randomize_result, 1);
      `checkd(o1.m, 32'd7);
    end
    repeat (20) begin
      randomize_result = o2.randomize();
      `checkd(randomize_result, 1);
      `checkd(o2.a, 32'd9);
    end
    $write("*-* All Finished *-*\n");
    $finish;
  end

  initial begin
    if ($test$plusargs("PHASE_BASE")) begin
      if ($test$plusargs("MODE=cycle")) cycle_calls();
      else if ($test$plusargs("MODE=isolation")) isolation_calls();
      else phase_calls();
      $write("*-* All Finished *-*\n");
      $finish;
    end
  end
endmodule
