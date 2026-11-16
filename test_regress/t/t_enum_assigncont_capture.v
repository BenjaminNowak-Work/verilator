// DESCRIPTION: Verilator: Verilog Test module
//
// This file ONLY is placed under the Creative Commons Public Domain.
// SPDX-FileCopyrightText: 2026 Wilson Snyder
// SPDX-License-Identifier: CC0-1.0

// verilog_format: off
`define stop $stop
`define checks(gotv,expv) do if ((gotv) != (expv)) begin $write("%%Error: %s:%0d: got='%s' exp='%s'\n", `__FILE__, `__LINE__, (gotv), (expv)); `stop; end while(0);
// verilog_format: on

module t;
  typedef enum bit {IDLE, BUSY} state_t;
  bit selected;
  string text;

  function automatic state_t current_state();
    return selected ? BUSY : IDLE;
  endfunction

  initial begin
    selected = $test$plusargs("BUSY");
    // verilator lint_off IEEEMAYDEPRECATE
    assign text = $sformatf("%p", current_state());
    // verilator lint_on IEEEMAYDEPRECATE
    #1;
    `checks(text, (selected ? "BUSY" : "IDLE"));
    // verilator lint_off IEEEMAYDEPRECATE
    deassign text;
    // verilator lint_on IEEEMAYDEPRECATE
    $write("*-* All Finished *-*\n");
    $finish;
  end
endmodule
