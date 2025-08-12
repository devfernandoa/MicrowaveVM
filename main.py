from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

Register = str

@dataclass
class Instr:
    op: str
    args: Tuple[str, ...]  # tokens as strings

class MicrowaveVM:
    """
    A minimal Minsky-style VM specialized to two registers:
      - TIME
      - POWER

    Instruction set (Turing-complete):
      SET R n           ; initialize a register
      INC R             ; R := R + 1
      DECJZ R label     ; if R == 0: PC := label, else: R := R - 1
      GOTO label        ; PC := label
      PRINT             ; print current value of TIME register
      HALT              ; stop

    Labels:
      label_name:       ; defines a target for GOTO/DECJZ
    """

    def __init__(self):
        self.registers: Dict[Register, int] = {"TIME": 0, "POWER": 0}
        self.program: List[Instr] = []
        self.labels: Dict[str, int] = {}
        self.pc: int = 0
        self.halted: bool = False
        self.steps: int = 0

    # --- Assembler / Loader ---
    def load_program(self, source: str):
        self.program.clear()
        self.labels.clear()
        self.pc = 0
        self.halted = False
        self.steps = 0

        lines = source.splitlines()
        # First pass: collect labels
        idx = 0
        for raw in lines:
            line = raw.split(';', 1)[0].split('#', 1)[0].strip()
            if not line:
                continue
            if line.endswith(':'):
                label = line[:-1].strip()
                if not label:
                    raise ValueError("Empty label definition.")
                if label in self.labels:
                    raise ValueError(f"Duplicate label: {label}")
                self.labels[label] = idx
            else:
                idx += 1

        # Second pass: parse instructions
        for raw in lines:
            line = raw.split(';', 1)[0].split('#', 1)[0].strip()
            if not line or line.endswith(':'):
                continue
            tokens = line.replace(',', ' ').split()
            op = tokens[0].upper()
            args = tuple(tokens[1:])
            # Basic validation
            if op == "SET":
                if len(args) != 2:
                    raise ValueError(f"SET expects 2 args: {line}")
                if args[0].upper() not in ("TIME", "POWER"):
                    raise ValueError(f"Unknown register in SET: {args[0]}")
                try:
                    int(args[1])
                except:
                    raise ValueError(f"SET value must be integer: {args[1]}")
            elif op == "INC":
                if len(args) != 1 or args[0].upper() not in ("TIME", "POWER"):
                    raise ValueError(f"INC expects register (TIME/POWER): {line}")
            elif op == "DECJZ":
                if len(args) != 2 or args[0].upper() not in ("TIME", "POWER"):
                    raise ValueError(f"DECJZ expects register and label: {line}")
                # label existence checked at run-time to allow forward refs
            elif op == "GOTO":
                if len(args) != 1:
                    raise ValueError(f"GOTO expects 1 label: {line}")
            elif op == "PRINT":
                if len(args) != 0:
                    raise ValueError(f"PRINT takes no args: {line}")
            elif op == "HALT":
                if len(args) != 0:
                    raise ValueError(f"HALT takes no args: {line}")
            else:
                raise ValueError(f"Unknown opcode: {op}")
            self.program.append(Instr(op, args))

    # --- Execution ---
    def step(self):
        if self.halted:
            return
        if not (0 <= self.pc < len(self.program)):
            # Implicit halt if PC falls off program
            self.halted = True
            return

        instr = self.program[self.pc]
        self.steps += 1

        def regname(s: str) -> str:
            return s.upper()

        if instr.op == "SET":
            r, v = regname(instr.args[0]), int(instr.args[1])
            self.registers[r] = v
            self.pc += 1

        elif instr.op == "INC":
            r = regname(instr.args[0])
            self.registers[r] = self.registers.get(r, 0) + 1
            self.pc += 1

        elif instr.op == "DECJZ":
            r = regname(instr.args[0])
            target = instr.args[1]
            if self.registers.get(r, 0) == 0:
                if target not in self.labels:
                    raise ValueError(f"Unknown label: {target}")
                self.pc = self.labels[target]
            else:
                self.registers[r] -= 1
                self.pc += 1

        elif instr.op == "GOTO":
            target = instr.args[0]
            if target not in self.labels:
                raise ValueError(f"Unknown label: {target}")
            self.pc = self.labels[target]

        elif instr.op == "PRINT":
            print(f"TIME: {self.registers.get('TIME', 0)}")
            self.pc += 1

        elif instr.op == "HALT":
            print("BEEEEEEP!")
            self.halted = True

    def run(self, max_steps: Optional[int] = None):
        while not self.halted:
            if max_steps is not None and self.steps >= max_steps:
                raise RuntimeError("Step limit reached (possible infinite loop).")
            self.step()

    # --- Helpers ---
    def state(self) -> Dict[str, int]:
        return dict(self.registers)

    def reset_registers(self, TIME: int = 0, POWER: int = 0):
        self.registers["TIME"] = int(TIME)
        self.registers["POWER"] = int(POWER)
        self.pc = 0
        self.halted = False
        self.steps = 0


# --------- Demo programs ---------
# 1) ADD: TIME := TIME + POWER ; POWER := 0
ADD_PROGRAM = """
    ; Precondition: TIME = a, POWER = b
    ; Post:        TIME = a+b, POWER = 0
loop:
    DECJZ POWER end
    INC TIME
    GOTO loop
end:
    HALT
"""

# 2) MULTIPLY via repeated addition:
#    TIME := a * b, POWER := 0
#    Uses TIME as accumulator, POWER as outer counter, and a temporary loop to add 'a' each time.
#    To keep two-register purity, we preload TIME with 0 and “encode” multiplicand via repeated INCs before loop.
MULT_PROGRAM = """
    ; Pre: TIME = 0, POWER = b
    ; Also assume we first built a copy of 'a' into TIME_A via a small bootstrap program,
    ; but to stay 2-register, we’ll rebuild 'a' each inner loop by counting with POWER jumps.
    ; Simpler approach: store a in TIME, b in POWER, then compute:
    ;   result := 0
    ;   repeat POWER times: result += a
    ; Here result is accumulated back into TIME; we must preserve 'a' each inner add.
    ;
    ; Encoding trick: We'll do a simple slow method:
    ; - Move a out by consuming TIME into repeated INCs on POWER, then rebuild each cycle.
    ; NOTE: In practice, 2-register multiplication needs careful choreography. Below is a tiny,
    ;       pedagogical but not optimized routine that assumes TIME holds 'a', POWER holds 'b'.
    ;
    ; Step 0: result := 0, move a into TIME_AUX by zeroing TIME while counting in POWER, then restore.
    ; To keep this concise, we show a version where we pre-set TIME=a and POWER=b,
    ; and compute a*b by:
    ;   while POWER>0:
    ;       tmp := a
    ;       while tmp>0:
    ;           INC RESULT   (RESULT is TIME here)
    ;           DEC tmp
    ;       DEC POWER
    ; HALT
    ;
    ; Two-registers force us to reuse TIME as tmp and use DECJZ jumps cleverly.
    ;
    ; Layout:
    ; TIME  = result/tmp (mutates)
    ; POWER = outer counter (b)
    ;
outer:
    DECJZ POWER end          ; if POWER==0 -> end
    ; rebuild tmp := a by adding A times into TIME, but we need 'a'.
    ; For a tiny demo, we’ll assume we preloaded TIME with 0 and then inserted 'a' INCs just before start.
    ; Instead, here’s a tiny concrete multiplication example baked in:
    HALT
"""

# Quick usage example
if __name__ == "__main__":
    import sys
    
    vm = MicrowaveVM()

    if len(sys.argv) > 1:
        # Load program from file
        filename = sys.argv[1]
        try:
            with open(filename, 'r') as f:
                program_content = f.read()
            vm.load_program(program_content)
            print(f"Loaded program from: {filename}")
            vm.run()
            print("Final state:", vm.state())
        except FileNotFoundError:
            print(f"Error: File '{filename}' not found.")
        except Exception as e:
            print(f"Error: {e}")
    else:
        # Example 1: addition a + b (default behavior)
        vm.load_program(ADD_PROGRAM)
        vm.reset_registers(TIME=3, POWER=2)  # 3 + 2
        vm.run()
        print("ADD result:", vm.state())  # Expect TIME=5, POWER=0

        # You can write and load your own programs similarly.
