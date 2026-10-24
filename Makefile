# wavelens — demo flow: Verilator VCD -> vcd2wavedrom.py -> WaveDrom JSON -> docs/demo_waves.js (loaded by docs/index.html)
# Build products live under BUILD (default out/ in the repository, git-ignored: the cargo target, the example dumps and
# pages, the smoke shots). On a slow mount (the repository on /mnt/c under WSL) make BUILD=/tmp/wavelens … builds faster.
# make dist: the prebuilt sva CLI under bin/ (Linux committed: a clone works without Rust; Windows needs mingw-w64).
# make check is the gate before a commit: the engine's tests, the unit tests, everything smoke needs, smoke --strict,
# the screenshots made again (a broken one fails).
# Converter settings (signals, enums, groups, markers, colours, sorting …) come from a JSON config file.
BUILD ?= out
B     := $(abspath $(BUILD))
OBJ   ?= $(B)/obj
VCD   ?= $(B)/demo.vcd
PY    := python3 -I
PW    := PYTHONDONTWRITEBYTECODE=1 python3   # playwright scripts: not -I (a user-site install), no __pycache__
DEMO_CONFIG := examples/demo/demo.config.json
DEMO_TB     := examples/demo/demo_tb.sv
DEMO_JS     := docs/demo_waves.js
APB_JS      := docs/apb_waves.js
V2W := $(PY) tools/vcd2wavedrom.py --config $(DEMO_CONFIG) --waves $(VCD)

# Any dump, starting from the VCD alone (keep your own under work/: dumps and pages are git-ignored there):
#   make config WAVES=work/x.vcd -> work/x.config.json: every signal under its full path, one line each (show, radix,
#                                   color, style …), settings from $(BASE). Run it again after the dump changed: new
#                                   signals are added, gone ones dropped, your edits kept.
#   make html WAVES=work/x.vcd   -> work/x.html (makes work/x.config.json first if it does not exist yet, updates it
#                                   when work/x.types.json is newer: the design's types by path, svtypes.py)
#   make html WAVES=x.vcd SVA="checks/*.sv" BIND="a_req_ack@tb.dut,apb_*@tb.u_apb"   assertions bound and evaluated
#   make config WAVES=x.vcd SVA="checks/*.sv"   the config gets "sva" and a "bind" line per matching instance
#   WAVES may be a VCD or an FST (read by GTKWave's fst2vcd, else by the sva CLI of bin/: the same text, enums too).
#   FSM state names: an FST brings its enum tables; for a VCD work/x.types.json beside it (tools/svtypes.py: Questa's
#   describe or Verilator), else SV="rtl/*.sv" (typedef enum in the sources, by the variable's name).
# make html: one self-contained page (wavelens.css/js + data inlined) from every view of CONFIG.
#   make html                                demo dump -> $(BUILD)/demo.html
#   make html CONFIG=work/dump.config.json   a hand-written config -> work/dump.html (or HTML=…)
BASE ?= tools/base.config.json
ifdef WAVES
$(if $(wildcard $(WAVES)),,$(error no dump WAVES=$(WAVES)))
CONFIG ?= $(basename $(WAVES)).config.json
HTML   ?= $(basename $(WAVES)).html
endif
CONFIG ?= $(DEMO_CONFIG)
HTML   ?= $(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(B)/demo.html,$(patsubst %.json,%,$(patsubst %.config.json,%,$(CONFIG))).html)
HTML_WAVES = $(or $(WAVES),$(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(VCD)))

help:
	@echo 'make demo       Verilator VCD of examples/demo -> $(DEMO_JS), the APB example with its checks -> docs/apb_waves.js (docs/index.html)'
	@echo 'make demo-fst   the same testbench as FST -> $$(BUILD)/demo_fst.config.json + demo_fst.html (FSM names from the dump)'
	@echo 'make examples   every example (apb axi_lite fsm): VCD + FST, pages in $$(BUILD)/examples/<ex>/'
	@echo 'make example    EX=apb|axi_lite|fsm: one of them'
	@echo 'make questa     EX=fsm: the example in QuestaSim (vsim on PATH): VCD + its types (tools/questa/wavelens_types.tcl) + page in $$(BUILD)/questa/<ex>/'
	@echo 'make types-fixture  tests/unit/types in QuestaSim again: questa.vcd, questa.types.json (another Questa version: read the diff)'
	@echo 'make shots      the README screenshots in docs/img/ and the visual regression'"'"'s tests/visual (after make examples)'
	@echo 'make shots-check  both made again into $$(BUILD), compared pixel by pixel with the committed ones (tests/pngdiff.py): a change fails'
	@echo 'make guide-shots  the pictures of the guides in docs/guides/img (after make examples; ONLY=gaps,sva: those guides)'
	@echo 'make html       one self-contained page: the demo, CONFIG=work/x.config.json, or WAVES=work/x.vcd (config made if missing);'
	@echo '                SVA="checks/*.sv" BIND="name@scope,…": assertions bound, evaluated, an Assertions section'
	@echo 'make config     WAVES=work/x.vcd: write or update work/x.config.json (every signal, your edits kept); SVA=…: "bind" lines'
	@echo 'make wavelens   wavelens/wavelens.js from wavelens/src/*.js (the page needs one file: run it after editing the sources)'
	@echo 'make sva-build  the SVA engine (sva/, Rust): native CLI $$(BUILD)/sva-target/release/sva + sva_wasm.wasm -> wavelens/sva.wasm.js'
	@echo 'make dist       the prebuilt sva CLI: dist-linux (bin/linux-x86_64/sva, static, committed) and dist-windows'
	@echo 'make dist-linux    bin/linux-x86_64/sva (musl, static)'
	@echo 'make dist-windows  bin/windows-x86_64/sva.exe (needs mingw-w64: sudo apt install mingw-w64)'
	@echo 'make sva-test   cargo test of the SVA engine: unit tests, the corpus tests/sva (third_party too), the schema, the CLI'
	@echo 'make sva-bless  rewrite tests/sva/golden/*.txt after a reviewed change of the parser output'
	@echo 'make sva-examples  sva parse + sva eval of the assertion files of examples/ (apb, axi_lite, fsm; after make examples)'
	@echo 'make sva-verify the checkers of the examples in Verilator --assert against sva eval (after make examples; skipped without verilator)'
	@echo 'make sva-eval   WAVES=dump.vcd|fst SVA="pkg.sv checks.sva" SCOPE=tb.dut [OUT=results.json] [ARGS=...]: sva eval'
	@echo 'make sva-spike  the spike page $$(BUILD)/sva/spike.html (the WebAssembly build and wavelens/sva.js in a page)'
	@echo 'make vsix       the VS Code extension (vscode/) -> $$(BUILD)/wavelens.vsix and its copy wavelens-<version>.vsix (kept'
	@echo '                side by side): the viewer and the static sva, for the Linux host of Remote-SSH / WSL (nothing else'
	@echo '                installed there; code --install-extension FILE there)'
	@echo 'make vscode-e2e the extension (vscode/) in a real VS Code (tests/vscode_e2e.py; WSL: the VS Code of Windows, Remote - WSL)'
	@echo 'make mcp-bench  the MCP server for AI agents (tools/wavemcp.py) on the benchmark tasks by a script: answers checked, bytes'
	@echo '                returned (no agent); AGENT=claude|codex [MODEL=sonnet] [REPS=2] [TASKS=a1,b3]: agents with and without'
	@echo '                it, tokens counted (costs tokens; tests/mcp_bench.py, the runs in $$(BUILD)/mcp_bench/runs.jsonl)'
	@echo 'make smoke      headless Chromium checks of docs/index.html, tests/conformance.html and the built pages (needs'
	@echo '                make examples demo demo-fst sva-build sva-spike html first; what is missing is reported as SKIPPED);'
	@echo '                STRICT=1: a skip fails; ONLY=sec1,sec2: those sections only (smoke.py --list)'
	@echo 'make unit       the Python unit tests of the tools (tests/unit: unittest, standard library, a few seconds)'
	@echo 'make unit-shuffle the unit tests one by one in the order of a seed (SEED=n: that order again): a test that needs another first fails'
	@echo 'make unit-bless the goldens of tests/unit/golden (the bytes of wavejson.py, vcd2wavedrom.py over the fixtures) written anew: read the diff'
	@echo 'make check      the gate before a commit: sva.wasm.js the build of sva/, the pages smoke needs, sva-test and unit (no skips), sva-verify, mcp-bench, smoke STRICT=1, shots-check'
	@echo 'make fmt        verible-verilog-format of the project SystemVerilog (docs/SV_STYLE.md), when installed'
	@echo 'make lint       verilator --lint-only -Wall on the example testbenches'
	@echo 'make clean      remove the build products under $$(BUILD) (the cargo target stays: make clean-all)'
	@echo 'make clean-all  remove $$(BUILD) entirely, the cargo target included'
	@echo 'variables       BUILD=$(BUILD)  WAVES=dump.vcd|fst  CONFIG  HTML  BASE=$(BASE)  TYPES=x.types.json (default: beside WAVES)  SV="rtl/*.sv"'
	@echo '                SVA="checks/*.sv"  BIND="name@scope,…"  EX=apb|axi_lite|fsm  SCOPE=tb.dut  OUT=results.json  ARGS=…'
	@echo '                FST=$$(BUILD)/demo_fst.fst  STRICT=1  ONLY=sec,…  AGENT=claude|codex  MODEL  REPS  TASKS'

demo: $(DEMO_JS) $(APB_JS)

# docs/index.html's assertion example: the APB view "transfers" with the example's checks bound (results of sva eval)
$(APB_JS): examples/apb/apb.config.json examples/apb/apb.sva examples/apb/apb_tb.sv tools/vcd2wavedrom.py tools/svabuild.py tools/embed.py
	$(MAKE) example EX=apb
	$(PY) tools/vcd2wavedrom.py --config examples/apb/apb.config.json --view transfers --waves $(B)/examples/apb/apb.fst $(SVA_OPT) --out $(B)/apb_transfers.json
	$(PY) tools/embed.py --var APB_WAVES transfers=$(B)/apb_transfers.json --out $@

# The same testbench dumped as FST (Verilator --trace-fst): FSM enum labels come from the dump itself.
#   make demo-fst  -> $(BUILD)/demo_fst.config.json (mkconfig) + $(BUILD)/demo_fst.html
FST ?= $(B)/demo_fst.fst
$(OBJ)_fst/Vdemo_tb: $(DEMO_TB)
	mkdir -p $(B)   # verilator -Mdir makes only the last level
	verilator --binary --timing -Wno-fatal --trace-fst --top-module demo_tb -Mdir $(OBJ)_fst $(DEMO_TB)

$(FST): $(OBJ)_fst/Vdemo_tb
	cd $(OBJ)_fst && ./Vdemo_tb +trace +dump=$(FST)

demo-fst: $(FST)
	$(MAKE) config html WAVES=$(FST)

$(OBJ)/Vdemo_tb: $(DEMO_TB)
	mkdir -p $(B)
	verilator --binary --timing -Wno-fatal --trace --top-module demo_tb -Mdir $(OBJ) $(DEMO_TB)

$(VCD): $(OBJ)/Vdemo_tb
	cd $(OBJ) && ./Vdemo_tb +trace && mv demo.vcd $(VCD)

# Examples (examples/<ex>/: testbench, hand-written <ex>.config.json, README.md). make example EX=apb builds into
# $(BUILD)/examples/<ex>/: the dump as VCD and as FST, <ex>.types.json (the design's types by path: svtypes.py
# verilator), <ex>.html from the example config, and <ex>_all.html from a config that mkconfig.py makes from the VCD (the
# whole hierarchy; the types beside it give the state names and struct fields). The FSM page reads the FST (state names
# and structs from the dump: fst2vcd, else the sva CLI); the others read the VCD.
EXAMPLES := apb axi_lite fsm
EX  ?= apb
EXD := examples/$(EX)
EXB := $(B)/examples/$(EX)
EX_SRC  = $(wildcard $(EXD)/*_pkg.sv) $(filter-out %_pkg.sv,$(wildcard $(EXD)/*.sv))
EX_DUMP = $(if $(filter fsm,$(EX)),fst,vcd)

$(EXB)/obj/V$(EX)_tb: $(EX_SRC)
	mkdir -p $(EXB)
	verilator --binary --timing -Wno-fatal --trace --top-module $(EX)_tb -Mdir $(EXB)/obj $(EX_SRC)

$(EXB)/obj_fst/V$(EX)_tb: $(EX_SRC)
	mkdir -p $(EXB)
	verilator --binary --timing -Wno-fatal --trace-fst --trace-structs --top-module $(EX)_tb -Mdir $(EXB)/obj_fst $(EX_SRC)

$(EXB)/$(EX).vcd: $(EXB)/obj/V$(EX)_tb
	cd $(EXB)/obj && ./V$(EX)_tb +trace +dump=$@

$(EXB)/$(EX).fst: $(EXB)/obj_fst/V$(EX)_tb
	cd $(EXB)/obj_fst && ./V$(EX)_tb +trace +dump=$@

$(EXB)/$(EX).types.json: $(EX_SRC) tools/svtypes.py
	$(PY) tools/svtypes.py verilator --top $(EX)_tb --out $@ -- $(EX_SRC)

example: wavelens/wavelens.js $(EXB)/$(EX).vcd $(EXB)/$(EX).fst $(EXB)/$(EX).types.json
	$(PY) tools/mkhtml.py --config $(EXD)/$(EX).config.json --waves $(EXB)/$(EX).$(EX_DUMP) $(SVA_OPT) --out $(EXB)/$(EX).html
	$(PY) tools/mkconfig.py $(EXB)/$(EX).vcd --base $(BASE) --out $(EXB)/$(EX)_all.config.json --force
	$(PY) tools/mkhtml.py --config $(EXB)/$(EX)_all.config.json --out $(EXB)/$(EX)_all.html

examples:
	@for ex in $(EXAMPLES); do $(MAKE) --no-print-directory example EX=$$ex || exit 1; done

# An example in QuestaSim (vlog, vsim on PATH): $(BUILD)/questa/<ex>/ gets Questa's VCD, its types
# (tools/questa/wavelens_types.tcl: describe of every signal) and <ex>.html made from them, as for a design of your own.
# types-fixture: the corpus of tests/unit/types in Questa again (questa.vcd, questa.types.json; another Questa version:
# read the diff)
QB = $(B)/questa/$(EX)
VSIM_TYPES = source $(abspath tools/questa/wavelens_types.tcl); wavelens_types $(1).types.json; run -all; quit -f
questa: wavelens/wavelens.js
	@command -v vsim >/dev/null || { echo 'questa: vsim is not on PATH (QuestaSim)'; exit 1; }
	mkdir -p $(QB)
	cd $(QB) && vlog -sv -quiet $(abspath $(EX_SRC)) && vsim -c -quiet -voptargs=+acc $(EX)_tb +trace +dump=$(EX).vcd \
	  -do "$(call VSIM_TYPES,$(EX))"
	$(PY) tools/svtypes.py check $(QB)/$(EX).types.json $(QB)/$(EX).vcd
	$(PY) tools/mkconfig.py $(QB)/$(EX).vcd --base $(BASE) --out $(QB)/$(EX).config.json --force
	$(PY) tools/mkhtml.py --config $(QB)/$(EX).config.json --out $(QB)/$(EX).html
TF = tests/unit/types
types-fixture:
	@command -v vsim >/dev/null || { echo 'types-fixture: vsim is not on PATH (QuestaSim)'; exit 1; }
	mkdir -p $(B)/questa/types
	cd $(B)/questa/types && vlog -sv -quiet +incdir+$(abspath $(TF)) $(abspath $(TF)/types_pkg.sv $(TF)/types_tb.sv) && \
	  vsim -c -quiet -voptargs=+acc types_tb +trace +dump=questa.vcd -do "$(call VSIM_TYPES,questa)"
	sed 's/"date": "[^"]*"/"date": "2026-10-24T13:30:00"/' $(B)/questa/types/questa.types.json > $(TF)/questa.types.json
	sed '/^\$$date/{n;s/.*/\tSat Oct 24 13:30:00 2026/}' $(B)/questa/types/questa.vcd > $(TF)/questa.vcd
	$(PY) tools/svtypes.py check $(TF)/questa.types.json $(TF)/questa.vcd

shots:
	$(PW) tests/shots.py --build $(B) $(if $(ONLY),--only $(ONLY))
	$(PW) tests/shots.py --build $(B) --set visual $(if $(ONLY),--only $(ONLY))

# the pictures of the guides (docs/guides/*.html): docs/guides/img/*.png; the gaps guide's dump is made in BUILD/guides
guide-shots:
	$(PW) tests/guide_shots.py --build $(B) $(if $(ONLY),--only $(ONLY))

# every shot made again: a shot that no longer builds fails, and so does a picture that changed (the look changed: make
# shots and commit the PNGs with the change); the pictures made again and compared with the committed ones, docs/img and the visual regression's tests/visual
# (tests/pngdiff.py: a picture that changed fails; the differences in BUILD/img/diff, BUILD/visual/diff)
shots-check:
	@rm -rf $(B)/img $(B)/visual   # every picture made by this run: none left from an earlier one
	$(PW) tests/shots.py --build $(B) --out $(B)/img > /dev/null
	$(PW) tests/shots.py --build $(B) --set visual --out $(B)/visual > /dev/null
	@s=0; $(PY) tests/pngdiff.py docs/img $(B)/img || s=1; $(PY) tests/pngdiff.py tests/visual $(B)/visual || s=1; exit $$s

# Two views of one dump (see $(DEMO_CONFIG)): clock-sampled (real WaveDrom wave strings) and exact transitions ("tv").
$(DEMO_JS): $(VCD) $(DEMO_CONFIG) tools/vcd2wavedrom.py tools/wavejson.py tools/embed.py
	$(V2W) --view cycle --out $(B)/cyc.json
	$(V2W) --view exact --out $(B)/exact.json
	$(PY) tools/embed.py --var DEMO_WAVES cycle=$(B)/cyc.json exact=$(B)/exact.json --out $@

comma := ,
# SVA="checks/*.sv" (a typo is an error, not a page without checks); BIND="a@tb.dut,b_*@tb" (quoted: no shell globbing)
SVA_GLOB = $(if $(SVA),$(or $(wildcard $(SVA)),$(error no file matches SVA=$(SVA))))
SVA_FILES = $(foreach f,$(SVA_GLOB),--sva $(f))
SVA_BINDS = $(foreach b,$(subst $(comma), ,$(BIND)),--bind '$(b)')
html: wavelens/wavelens.js $(CONFIG) $(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(VCD))
	$(PY) tools/mkhtml.py --config $(CONFIG) $(if $(HTML_WAVES),--waves $(HTML_WAVES)) $(SVA_OPT) $(SVA_FILES) $(SVA_BINDS) --out $(HTML)

config:
	$(if $(WAVES),,$(error make config needs WAVES=dump.vcd))
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $(CONFIG) --update $(if $(TYPES),--types $(TYPES)) $(if $(SV),--sv $(SV)) $(if $(SVA),$(SVA_FILES) $(if $(wildcard $(SVA_BIN)),--sva-bin $(SVA_BIN)))

ifdef WAVES
# missing: made; older than the types file (x.types.json beside the dump, or TYPES=): updated from it, every edit kept
TYPES_OF = $(or $(TYPES),$(wildcard $(basename $(WAVES)).types.json))
$(CONFIG): $(TYPES_OF) | $(WAVES)
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $@ $(if $(wildcard $@),--update) $(if $(TYPES),--types $(TYPES)) $(if $(SV),--sv $(SV))
endif

# SVA engine (docs/sva/STACK.md): one Rust library, a native CLI over VCD / FST (wellen) and a WebAssembly module for
# the page. Cargo builds under BUILD. Needs cargo and `rustup target add wasm32-unknown-unknown`.
CARGO := CARGO_TARGET_DIR=$(B)/sva-target cargo
SVA_BIN  = $(B)/sva-target/release/sva
SVA_WASM = $(B)/sva-target/wasm32-unknown-unknown/wasm/sva_wasm.wasm
SVA_OPT  = $(if $(wildcard $(SVA_BIN)),--sva-bin $(SVA_BIN))   # mkhtml: "sva" / "bind" of a config through the CLI when built

sva-build:
	cd sva && $(CARGO) build --release -p sva-cli
	cd sva && $(CARGO) build --profile wasm -p sva-wasm --target wasm32-unknown-unknown
	$(PY) sva/wasm/pack.py $(SVA_WASM) wavelens/sva.wasm.js
	@ls -l $(SVA_BIN) $(SVA_WASM) wavelens/sva.wasm.js

# The prebuilt CLI for a clone without Rust, committed and rebuilt in the commit of an engine change (as
# wavelens/sva.wasm.js): Linux static (musl: any distribution), Windows through mingw-w64. The tools find it by
# themselves (tools/svabuild.py: --sva-bin, $$WAVELENS_SVA, out/sva-target, bin/<os>-x86_64, sva on PATH).
# Needs rustup target add x86_64-unknown-linux-musl x86_64-pc-windows-gnu, and x86_64-w64-mingw32-gcc for Windows
# (Ubuntu: sudo apt install mingw-w64).
DIST_LINUX := bin/linux-x86_64/sva
DIST_WIN   := bin/windows-x86_64/sva.exe
MINGW_CC   := x86_64-w64-mingw32-gcc
dist: dist-linux dist-windows
dist-linux:
	cd sva && $(CARGO) build --release -p sva-cli --target x86_64-unknown-linux-musl
	mkdir -p $(dir $(DIST_LINUX)) && cp $(B)/sva-target/x86_64-unknown-linux-musl/release/sva $(DIST_LINUX)
	$(DIST_LINUX) parse examples/axi_lite/axi_lite.sva > /dev/null && ls -l $(DIST_LINUX)
dist-windows:
	@command -v $(MINGW_CC) >/dev/null || { echo 'dist-windows: $(MINGW_CC) is not installed (Ubuntu: sudo apt install mingw-w64)'; exit 1; }
	cd sva && CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER=$(MINGW_CC) $(CARGO) build --release -p sva-cli --target x86_64-pc-windows-gnu
	mkdir -p $(dir $(DIST_WIN)) && cp $(B)/sva-target/x86_64-pc-windows-gnu/release/sva.exe $(DIST_WIN)
	@ls -l $(DIST_WIN)

# unit tests (lexer, preprocessor, parser, expansion, evaluator), the corpus tests/sva/*.sv against its annotations
# and golden files, docs/sva/ast.schema.json against the output, the sva binary end to end
sva-test:
	cd sva && BUILD=$(B) $(if $(WAVELENS_STRICT),WAVELENS_STRICT=1) $(CARGO) test

sva-bless:
	cd sva && SVA_BLESS=1 BUILD=$(B) $(CARGO) test --test corpus --test cli
	git diff --stat -- tests/sva/golden

# the assertion files of the examples, each after the file that declares its package; then over the dumps of make
# examples (each has one deliberately wrong assertion: sva eval exits 1), results in $(BUILD)/sva/<ex>.results.json
SVA_EX_apb      := --scope apb_tb --sva examples/apb/apb_tb.sv --sva examples/apb/apb.sva
SVA_EX_axi_lite := --scope axi_lite_tb.u_slave --sva examples/axi_lite/axi_lite.sva
SVA_EX_fsm      := --scope fsm_tb.u_rx --sva examples/fsm/uart_pkg.sv --sva examples/fsm/fsm.sva
# the reference: the examples' checkers built with the testbenches by Verilator --assert, the failures compared with
# sva eval's on the dumps (the assertions Verilator does not take are listed, not compared)
sva-verify: sva-build
	$(PY) tools/svaverify.py --build $(B) --sva-bin $(SVA_BIN)

sva-examples: sva-build
	$(SVA_BIN) parse examples/apb/apb_tb.sv examples/apb/apb.sva
	$(SVA_BIN) parse examples/axi_lite/axi_lite.sva
	$(SVA_BIN) parse examples/fsm/uart_pkg.sv examples/fsm/fsm.sva
	mkdir -p $(B)/sva
	@for ex in apb axi_lite fsm; do d=$(B)/examples/$$ex/$$ex.fst; \
	  if [ -f $$d ]; then echo "== $$ex"; $(SVA_BIN) eval --waves $$d $(SVA_EX_$$ex) --out $(B)/sva/$$ex.results.json; \
	  else echo "== $$ex: no $$d (make examples)"; fi; done; true

# sva eval over any dump: make sva-eval WAVES=work/x.fst SVA="rtl/pkg.sv checks.sva" SCOPE=tb.dut [OUT=r.json]
sva-eval: sva-build
	$(if $(WAVES),,$(error make sva-eval needs WAVES=dump.vcd|fst))
	$(if $(SVA),,$(error make sva-eval needs SVA=checks.sva (several: SVA="pkg.sv checks.sva")))
	$(SVA_BIN) eval --waves $(WAVES) $(foreach f,$(SVA),--sva $(f)) $(if $(SCOPE),--scope $(SCOPE)) $(if $(OUT),--out $(OUT)) $(ARGS)

sva-spike: sva-build $(VCD)
	mkdir -p $(B)/sva
	$(PY) sva/spike/mkspike.py $(SVA_WASM) $(B)/sva/spike.html
	$(SVA_BIN) eval --waves $(VCD) --scope demo_tb --sva sva/spike/demo.sva || true   # a_start_done fails on purpose

# The VS Code extension (vscode/): one .vsix with the viewer's files and the static sva CLI (tools/mkvsix.py, no node /
# npm; install it into the Remote-SSH / WSL host); vscode-e2e runs it in a real VS Code (tests/vscode_e2e.py: in WSL the
# VS Code of Windows connected to this distribution)
# two files: wavelens.vsix (the last build: the same install line each time) and wavelens-<version>.vsix (kept side by side)
VSIX := $(B)/wavelens.vsix
vsix: $(VSIX)
$(VSIX): VERSION tools/mkvsix.py $(wildcard vscode/*.js vscode/*.json vscode/*.md vscode/media/*.js) $(DIST_LINUX) \
    $(addprefix wavelens/,wavelens.css wavelens.config.js wavelens.js sva.wasm.js bus.js sva.js)
	$(PY) tools/mkvsix.py --out $@
vscode-e2e:
	@test -f $(B)/examples/fsm/fsm.fst || $(MAKE) example EX=fsm
	PYTHONDONTWRITEBYTECODE=1 python3 tests/vscode_e2e.py --build $(B)

# The MCP server (tools/wavemcp.py) and what it saves an agent (tests/mcp_bench.py): a generated dump with known answers
# and the APB / FSM examples; without AGENT the tasks are solved through the tools by a script (make check runs it)
mcp-bench:
	@test -f $(B)/examples/apb/apb.vcd -a -f $(B)/examples/fsm/fsm.fst || { $(MAKE) example EX=apb && $(MAKE) example EX=fsm; }
	$(PY) tests/mcp_bench.py --build $(B) $(if $(AGENT),--agent $(AGENT) $(if $(MODEL),--model $(MODEL)) $(if $(REPS),--reps $(REPS)) \
	  $(if $(TASKS),--tasks $(TASKS)),--scripted)

smoke:
	$(PW) tests/smoke.py --build $(B) --out $(B)/shots $(if $(STRICT),--strict) $(if $(ONLY),--only $(ONLY))

# wavelens/wavelens.js is the concatenation of wavelens/src/*.js (committed: a page needs one file and no build step)
WAVELENS_SRC := $(addprefix wavelens/src/,model.js vcd.js paint.js view.js edit.js diff.js modules.js fsm.js svg.js boot.js)
wavelens: wavelens/wavelens.js
wavelens/wavelens.js: $(WAVELENS_SRC) tools/wavelenscat.py
	$(PY) tools/wavelenscat.py

# Python unit tests of the tools (tests/unit/test_*.py on unittest, no dependencies; the fixtures in tests/unit/vcd).
# The sva CLI of this BUILD when it is built (else svabuild finds one: an older out/ build would test stale code)
# the unit tests one by one in an order of a seed (SEED=n again for the same order): a test that needs another first fails
unit-shuffle:
	BUILD=$(B) $(if $(WAVELENS_SVA),,$(if $(wildcard $(SVA_BIN)),WAVELENS_SVA=$(abspath $(SVA_BIN)))) $(PY) tests/unit/shuffle.py $(SEED)

# the goldens of tests/unit/golden (the bytes wavejson.py and vcd2wavedrom.py write) made anew: read the diff
unit-bless:
	WAVELENS_BLESS=1 $(PY) -m unittest discover -s tests/unit -t . -p 'test_small_tools.py'
	WAVELENS_BLESS=1 $(PY) -m unittest discover -s tests/unit -t . -p 'test_vcd2wavedrom.py'
	git status --short tests/unit/golden

unit:
	BUILD=$(B) $(if $(WAVELENS_STRICT),WAVELENS_STRICT=1) $(if $(WAVELENS_SVA),,$(if $(wildcard $(SVA_BIN)),WAVELENS_SVA=$(abspath $(SVA_BIN)))) \
	  $(PY) -m unittest discover -s tests/unit -t .

# The gate: the committed engine of the page is the build of its sources (wavelens/sva.wasm.js before and after
# sva-build), every page smoke checks and the fixtures (built first: the engine's goldens over the examples' FST and the
# unit tests' FST parity need them), the engine's and the unit tests with what the gate builds required
# (WAVELENS_STRICT: a missing dump fails, not skipped), smoke --strict
check:
	$(PY) tools/wavelenscat.py --check
	@mkdir -p $(B) && cp wavelens/sva.wasm.js $(B)/sva.wasm.js.committed
	$(MAKE) sva-build
	@cmp -s $(B)/sva.wasm.js.committed wavelens/sva.wasm.js || { echo 'check: wavelens/sva.wasm.js is not the build of sva/: commit the one sva-build wrote'; exit 1; }
	$(MAKE) examples demo demo-fst sva-spike html
	$(MAKE) sva-test WAVELENS_STRICT=1
	$(MAKE) unit WAVELENS_STRICT=1
	$(MAKE) sva-verify mcp-bench
	$(MAKE) smoke STRICT=1
	$(MAKE) shots-check

# SystemVerilog of the project (docs/SV_STYLE.md); tests/sva/third_party is other people's code and stays as it is
SV_OWN := $(wildcard examples/*/*.sv examples/*/*.sva sva/bench/*.sva sva/spike/*.sva) $(filter-out tests/sva/err_%,$(wildcard tests/sva/*.sv))
VERIBLE_FMT := verible-verilog-format --indentation_spaces=4 --column_limit=100 --wrap_spaces=4
fmt:
	@if command -v verible-verilog-format >/dev/null; then $(VERIBLE_FMT) --inplace $(SV_OWN); git diff --stat; \
	else echo 'fmt: verible-verilog-format is not installed: download a release from https://github.com/chipsalliance/verible/releases'; \
	  echo '     and put verible-verilog-format on PATH (then: $(VERIBLE_FMT) --inplace FILES)'; fi
	@echo 'fmt: tests/sva/err_*.sv by hand (the column of a //^ caret is the expectation); then make sva-bless and read the diff'

# -Wall on the testbenches; DECLFILENAME off: a testbench file carries its package and its DUT next to the tb module
lint:
	@for ex in demo $(EXAMPLES); do d=examples/$$ex; echo "== $$ex"; \
	  verilator --lint-only -Wall -Wno-DECLFILENAME --timing --top-module $${ex}_tb $$(ls $$d/*_pkg.sv 2>/dev/null) $$(ls $$d/*.sv | grep -v _pkg.sv) || exit 1; done

clean:
	rm -rf $(OBJ) $(OBJ)_fst $(VCD) $(FST) $(B)/cyc.json $(B)/exact.json $(B)/demo.html $(B)/shots $(B)/img $(B)/apb_transfers.json $(B)/smoke
	rm -rf $(basename $(FST)).config.json $(basename $(FST)).html
	rm -rf $(B)/examples $(B)/sva
	rmdir $(B) 2>/dev/null || true

# everything under BUILD, the cargo target (gigabytes) included; refuses a BUILD that is the repository or a home
clean-all:
	$(if $(filter $(B),/ $(CURDIR) $(HOME) $(abspath $(HOME)/..)),$(error clean-all: BUILD=$(B) is not a build directory))
	rm -rf $(B)

.PHONY: unit-bless unit-shuffle vsix vscode-e2e wavelens help demo demo-fst example examples questa types-fixture shots guide-shots html config sva-build dist dist-linux dist-windows sva-test sva-bless sva-examples sva-verify sva-eval sva-spike mcp-bench smoke shots-check unit check fmt lint clean clean-all
