"""Prepare fixed arithmetic controls; no model/EDA or production changes."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT.parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p, text):
    p.write_text(text, encoding="utf-8", newline="\n")


def boundary(width):
    maximum, high = (1 << width) - 1, 1 << (width - 1)
    values = {0, 1, 2, 3, maximum, maximum - 1, high, high - 1, high + 1,
              int("55" * (width // 8), 16), int("aa" * (width // 8), 16)}
    for bit in (7, 8, 15, 16, 24):
        if bit < width:
            values.update(((1 << bit) - 1, 1 << bit, ((1 << bit) - 1) << (width - bit)))
    return sorted(values)


def adder_tb(task, width, cin):
    values = boundary(width)
    counts = len(values) ** 2 * (2 if cin else 1) + 2 * 65536 * (2 if cin else 1) + width * 2 * (2 if cin else 1) + 4096 * (2 if cin else 1)
    if cin:
        declarations = "reg [15:0] a,b; reg Cin; wire [15:0] y; wire Co; TopModule dut(.a(a),.b(b),.Cin(Cin),.y(y),.Co(Co));"
        operand_a, operand_b, observed, expected = "a", "b", "{Co,y}", "{1'b0,a}+{1'b0,b}+Cin"
        check = "for(ci=0;ci<2;ci=ci+1)begin Cin=ci;check_now;end"
        seed = "1badb002"
    else:
        declarations = "reg [32:1] A,B; wire [32:1] S; wire C32; TopModule dut(.A(A),.B(B),.S(S),.C32(C32));"
        operand_a, operand_b, observed, expected = "A", "B", "{C32,S}", "{1'b0,A}+{1'b0,B}"
        check, seed = "check_now;", "c001d00d"
    cases = "\n".join(f"{i}:boundary={width}'h{v:x};" for i, v in enumerate(values))
    replica = int("01" * (width // 8), 16)
    text = f"""`timescale 1ns/1ps
module R2Probe;
{declarations}
integer ai,bi,ci,domain,bit_index,iteration; integer checks=0,mismatches=0; reg [31:0] rng=32'h{seed};
function [{width-1}:0] boundary(input integer index); begin case(index)
{cases}
default:boundary=0;endcase end endfunction
task step_rng; begin rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);end endtask
task check_now;reg [{width}:0] expected;begin #1;expected={expected};checks=checks+1;
if({observed}!==expected)begin if(mismatches==0)$display("FIRST_MISMATCH a=%h b=%h observed=%h expected=%h",{operand_a},{operand_b},{observed},expected);mismatches=mismatches+1;end end endtask
initial begin
for(ai=0;ai<{len(values)};ai=ai+1)for(bi=0;bi<{len(values)};bi=bi+1)begin {operand_a}=boundary(ai);{operand_b}=boundary(bi);{check} end
for(domain=0;domain<2;domain=domain+1)for(ai=0;ai<256;ai=ai+1)for(bi=0;bi<256;bi=bi+1)begin
if(domain==0)begin {operand_a}=ai;{operand_b}=bi;end else begin {operand_a}=ai*{width}'h{replica:x};{operand_b}=bi*{width}'h{replica:x};end
{check} end
for(bit_index=0;bit_index<{width};bit_index=bit_index+1)begin
{operand_a}=({width}'h1<<bit_index)-{width}'h1;{operand_b}=1;{check}
{operand_a}=1;{operand_b}=({width}'h1<<bit_index)-{width}'h1;{check} end
for(iteration=0;iteration<4096;iteration=iteration+1)begin step_rng;{operand_a}=rng;step_rng;{operand_b}=rng;{check} end
$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",checks,mismatches);
if(checks!={counts})$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
"""
    return text, dict(checks=counts, boundary_values=values, boundaries=len(values)**2*(2 if cin else 1),
        exhaustive_low_byte_and_repeated_byte_subdomains=2*65536*(2 if cin else 1),
        carry_chain_cases=width*2*(2 if cin else 1), pseudo_random_pairs=4096,
        pseudo_random_checks=4096*(2 if cin else 1), seed_hex=seed, full_input_domain_exhaustive=False,
        duplicate_vectors_across_phases_possible=True, expected_output_bits=width+1)


POS16_TOP = """module TopModule(input [15:0] a,b,input Cin,output [15:0] y,output Co);
wire c8;
Add8 lo(.a(a[7:0]),.b(b[7:0]),.cin(Cin),.y(y[7:0]),.co(c8));
Add8 hi(.a(a[15:8]),.b(b[15:8]),.cin(c8),.y(y[15:8]),.co(Co));
endmodule
"""
POS16_HELPER = """module Add8(input [7:0] a,b,input cin,output [7:0] y,output co);
wire [8:0] c;assign c[0]=cin;
for(genvar i=0;i<8;i=i+1)begin:bit_add
assign y[i]=a[i]^b[i]^c[i];assign c[i+1]=(a[i]&b[i])|(c[i]&(a[i]^b[i]));end
assign co=c[8];
endmodule
"""


def positive32():
    top = """module TopModule(input [32:1] A,B,output [32:1] S,output C32);
wire c16;
CLA16 lo(.a(A[16:1]),.b(B[16:1]),.cin(1'b0),.s(S[16:1]),.cout(c16));
CLA16 hi(.a(A[32:17]),.b(B[32:17]),.cin(c16),.s(S[32:17]),.cout(C32));
endmodule
"""
    helper = """module CLA16(input [15:0] a,b,input cin,output [15:0] s,output cout);
wire [15:0] p,g,c;wire [3:0] P,G;wire [4:0] gc;
assign p=a^b;assign g=a&b;assign gc[0]=cin;
for(genvar block_i=0;block_i<4;block_i=block_i+1)begin:groups
localparam K=block_i*4;
assign P[block_i]=&p[K+:4];
assign G[block_i]=g[K+3]|(p[K+3]&g[K+2])|(p[K+3]&p[K+2]&g[K+1])|(p[K+3]&p[K+2]&p[K+1]&g[K]);
assign c[K]=gc[block_i];
assign c[K+1]=g[K]|(p[K]&gc[block_i]);
assign c[K+2]=g[K+1]|(p[K+1]&g[K])|(p[K+1]&p[K]&gc[block_i]);
assign c[K+3]=g[K+2]|(p[K+2]&g[K+1])|(p[K+2]&p[K+1]&g[K])|(p[K+2]&p[K+1]&p[K]&gc[block_i]);
end
"""
    for n in range(1, 5):
        terms = []
        for k in range(n-1, -1, -1):
            terms.append("(" + "&".join([f"P[{j}]" for j in range(n-1, k, -1)] + [f"G[{k}]"]) + ")")
        terms.append("(" + "&".join([f"P[{j}]" for j in range(n-1, -1, -1)] + ["cin"]) + ")")
        helper += f"assign gc[{n}]=" + "|".join(terms) + ";\n"
    helper += "assign s=p^c;assign cout=gc[4];\nendmodule\n"
    return top + "\n" + helper


POS_SHIFT = """module TopModule(input [7:0] in,input [2:0] ctrl,output [7:0] out);
wire [7:0] s4,s2;
mux2X1 #(.WIDTH(8)) m4(.d0(in),.d1({4'b0,in[7:4]}),.sel(ctrl[2]),.y(s4));
mux2X1 #(.WIDTH(8)) m2(.d0(s4),.d1({2'b0,s4[7:2]}),.sel(ctrl[1]),.y(s2));
mux2X1 #(.WIDTH(8)) m1(.d0(s2),.d1({1'b0,s2[7:1]}),.sel(ctrl[0]),.y(out));
endmodule

module mux2X1 #(parameter WIDTH=8)(input [WIDTH-1:0] d0,d1,input sel,output [WIDTH-1:0] y);
assign y=sel?d1:d0;
endmodule
"""


def main():
    assert not (ROOT / "inputs").exists()
    contracts, provenance = [], {}
    tasks = ["adder_16bit", "adder_32bit", "barrel_shifter"]
    corpus = ANALYSIS / "compiler_inventory_20261004/corpus"
    pairs = json.loads((corpus / "PAIR_MANIFEST.json").read_text(encoding="utf-8"))["pairs"]
    for task in tasks:
        dest = ROOT / "inputs" / task
        dest.mkdir(parents=True)
        pair = next(p for p in pairs if p["dataset"] == "rtllm_g2" and p["side"] == "agent" and p["task"] == task)
        src = corpus / pair["prompt"]
        assert sha(src) == pair["prompt_sha256"]
        original = src.read_bytes()
        (dest / "prompt.original.txt").write_bytes(original)
        text = original.decode("utf-8")
        pat = re.compile(r"(?m)^Module name:[ \t]*(?:\r?\n[ \t]*)?(TopModule|adder_16bit|adder_32bit)[ \t]*(?:\r?\n|$)")
        matches = list(pat.finditer(text))
        assert len(matches) == (1 if task == "barrel_shifter" else 2)
        if len(matches) == 2:
            corrected = text[:matches[0].start()] + "Module name: TopModule\n" + text[matches[0].end():matches[1].start()] + text[matches[1].end():]
            write(dest / "prompt.txt", corrected)
        else:
            (dest / "prompt.txt").write_bytes(original)
        if task == "adder_16bit":
            positive = POS16_TOP + "\n" + POS16_HELPER
            negatives = dict(ignore_cin="module TopModule(input [15:0] a,b,input Cin,output [15:0] y,output Co);assign {Co,y}={1'b0,a}+{1'b0,b};endmodule\n",
                drop_carry="module TopModule(input [15:0] a,b,input Cin,output [15:0] y,output Co);assign y=a+b+Cin;assign Co=1'b0;endmodule\n")
            tb, domain = adder_tb(task, 16, True)
        elif task == "adder_32bit":
            positive = positive32()
            negatives = dict(drop_carry="module TopModule(input [32:1] A,B,output [32:1] S,output C32);assign S=A+B;assign C32=1'b0;endmodule\n",
                subtract="module TopModule(input [32:1] A,B,output [32:1] S,output C32);assign {C32,S}={1'b0,A}-{1'b0,B};endmodule\n")
            tb, domain = adder_tb(task, 32, False)
        else:
            positive = POS_SHIFT
            negatives = dict(left_shift="module TopModule(input [7:0] in,input [2:0] ctrl,output [7:0] out);assign out=in<<ctrl;endmodule\n",
                rotate="module TopModule(input [7:0] in,input [2:0] ctrl,output [7:0] out);assign out=(in>>ctrl)|(in<<(8-ctrl));endmodule\n")
            domain = dict(checks=2048, full_input_domain_exhaustive=True, expected_output_bits=8, duplicate_vectors_across_phases_possible=False)
            tb = """`timescale 1ns/1ps
module R2Probe;
reg [7:0] in;reg [2:0] ctrl;wire [7:0] out;TopModule dut(.in(in),.ctrl(ctrl),.out(out));
integer value,shift;integer checks=0,mismatches=0;reg [7:0] expected;
initial begin for(value=0;value<256;value=value+1)for(shift=0;shift<8;shift=shift+1)begin in=value;ctrl=shift;#1;expected=value>>shift;checks=checks+1;
if(out!==expected)begin if(mismatches==0)$display("FIRST_MISMATCH value=%h shift=%d observed=%h expected=%h",in,ctrl,out,expected);mismatches=mismatches+1;end end
$display("R2_PROBE_RESULT task=barrel_shifter checks=%0d mismatches=%0d",checks,mismatches);
if(checks!=2048)$fatal(1,"CHECK_COUNT_INVALID");$finish;end
initial begin #1000000;$fatal(1,"WATCHDOG_EXPIRED");end
endmodule
"""
        write(dest / "positive.sv", positive)
        write(dest / "tb.sv", tb)
        for name, source in negatives.items():
            write(dest / (name + ".sv"), source)
        contracts.append(dict(task=task, checks=domain["checks"], negative_controls=list(negatives), domain=domain))
        provenance[task] = dict(original_prompt_sha256=sha(dest / "prompt.original.txt"), corrected_prompt_sha256=sha(dest / "prompt.txt"), normalization="collapse_two_Module_name_headers_to_TopModule" if len(matches) == 2 else "unchanged", all_non_header_text_retained=True)
    for name in ("extract_bundle.py", "guard_wrapper.py", "lexical_mask.py"):
        shutil.copyfile(ANALYSIS / "module_bundle_20261004" / name, ROOT / name)
    assert sha(ROOT / "extract_bundle.py") == "8a7ab290e1e15d4248fd166b9c587b5fea7fb2958265853aeffe50e335de6414"
    (ROOT / "CONTRACTS.json").write_text(json.dumps(dict(contracts=contracts, prompt_provenance=provenance), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(tasks=tasks, comparisons_per_three_task_set=sum(c["checks"] for c in contracts), domains={c["task"]:c["domain"] for c in contracts})))


if __name__ == "__main__":
    main()
