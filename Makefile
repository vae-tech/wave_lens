# wavefw — demo flow: Verilator VCD -> vcd2wavedrom.py -> WaveDrom JSON -> docs/demo_waves.js (loaded by docs/index.html)
# Build products live under BUILD (default /tmp/wavefw: the project sits on /mnt/c, which is slow under WSL);
# make BUILD=build … puts them under the repository (build/ is git-ignored).
# Converter settings (signals, enums, groups, markers, colours, sorting …) come from a JSON config file.
BUILD ?= /tmp/wavefw
B     := $(abspath $(BUILD))
OBJ   ?= $(B)/obj
VCD   ?= $(B)/demo.vcd
PY    := python3 -I
READER ?=          # builtin (default: one pass in Python) | wavepeek
DEMO_CONFIG := examples/demo/demo.config.json
DEMO_TB     := examples/demo/demo_tb.sv
DEMO_JS     := docs/demo_waves.js
V2W := $(PY) tools/vcd2wavedrom.py --config $(DEMO_CONFIG) --waves $(VCD) $(if $(READER),--reader $(READER))

# Any dump, starting from the VCD alone (keep your own under work/: dumps and pages are git-ignored there):
#   make config WAVES=work/x.vcd -> work/x.config.json: every signal under its full path, one line each (show, radix,
#                                   color, style …), settings from $(BASE). Run it again after the dump changed: new
#                                   signals are added, gone ones dropped, your edits kept.
#   make html WAVES=work/x.vcd   -> work/x.html (makes work/x.config.json first if it does not exist yet)
#   WAVES may be a VCD or an FST (FST needs GTKWave's fst2vcd for order / change counts / enum labels).
#   FSM state names: an FST brings its enum tables; for a VCD add SV="rtl/*.sv" (typedef enum in the sources).
# make html: one self-contained page (wavefw.css/js + data inlined) from every view of CONFIG.
#   make html                                demo dump -> $(BUILD)/demo.html
#   make html CONFIG=work/dump.config.json   a hand-written config -> work/dump.html (or HTML=…)
BASE ?= tools/base.config.json
ifdef WAVES
CONFIG ?= $(basename $(WAVES)).config.json
HTML   ?= $(basename $(WAVES)).html
endif
CONFIG ?= $(DEMO_CONFIG)
HTML   ?= $(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(B)/demo.html,$(patsubst %.json,%,$(patsubst %.config.json,%,$(CONFIG))).html)
HTML_WAVES = $(or $(WAVES),$(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(VCD)))

help:
	@echo 'make demo       Verilator VCD of examples/demo -> $(DEMO_JS) (the data of docs/index.html)'
	@echo 'make demo-fst   the same testbench as FST -> $$(BUILD)/demo_fst.config.json + demo_fst.html (FSM names from the dump)'
	@echo 'make examples   every example (apb axi_lite fsm): VCD + FST, pages in $$(BUILD)/examples/<ex>/'
	@echo 'make example    EX=apb|axi_lite|fsm: one of them'
	@echo 'make shots      the README screenshots in docs/img/ (after make examples)'
	@echo 'make html       one self-contained page: the demo, CONFIG=work/x.config.json, or WAVES=work/x.vcd (config made if missing)'
	@echo 'make config     WAVES=work/x.vcd: write or update work/x.config.json (every signal, your edits kept)'
	@echo 'make smoke      headless Chromium checks of docs/index.html, tests/conformance.html and the built pages'
	@echo 'make clean      remove the build products under $$(BUILD)'
	@echo 'variables       BUILD=$(BUILD)  WAVES  CONFIG  HTML  BASE=$(BASE)  SV  READER=builtin|wavepeek'

demo: $(DEMO_JS)

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
# $(BUILD)/examples/<ex>/: the dump as VCD and as FST, <ex>.html from the example config, and <ex>_all.html from a
# config that mkconfig.py makes from the VCD (the whole hierarchy; --sv gives enum names). The FSM page reads the FST
# (state names from the dump) when fst2vcd is there; the others read the VCD.
EXAMPLES := apb axi_lite fsm
EX  ?= apb
EXD := examples/$(EX)
EXB := $(B)/examples/$(EX)
EX_SRC  = $(wildcard $(EXD)/*_pkg.sv) $(filter-out %_pkg.sv,$(wildcard $(EXD)/*.sv))
EX_DUMP = $(if $(and $(filter fsm,$(EX)),$(shell command -v fst2vcd)),fst,vcd)

$(EXB)/obj/V$(EX)_tb: $(EX_SRC)
	mkdir -p $(EXB)
	verilator --binary --timing -Wno-fatal --trace --top-module $(EX)_tb -Mdir $(EXB)/obj $(EX_SRC)

$(EXB)/obj_fst/V$(EX)_tb: $(EX_SRC)
	mkdir -p $(EXB)
	verilator --binary --timing -Wno-fatal --trace-fst --top-module $(EX)_tb -Mdir $(EXB)/obj_fst $(EX_SRC)

$(EXB)/$(EX).vcd: $(EXB)/obj/V$(EX)_tb
	cd $(EXB)/obj && ./V$(EX)_tb +trace +dump=$@

$(EXB)/$(EX).fst: $(EXB)/obj_fst/V$(EX)_tb
	cd $(EXB)/obj_fst && ./V$(EX)_tb +trace +dump=$@

example: $(EXB)/$(EX).vcd $(EXB)/$(EX).fst
	$(PY) tools/mkhtml.py --config $(EXD)/$(EX).config.json --waves $(EXB)/$(EX).$(EX_DUMP) --out $(EXB)/$(EX).html
	$(PY) tools/mkconfig.py $(EXB)/$(EX).vcd --base $(BASE) --sv $(EX_SRC) --out $(EXB)/$(EX)_all.config.json --force
	$(PY) tools/mkhtml.py --config $(EXB)/$(EX)_all.config.json --out $(EXB)/$(EX)_all.html

examples:
	@for ex in $(EXAMPLES); do $(MAKE) --no-print-directory example EX=$$ex || exit 1; done

shots:
	python3 tests/shots.py --build $(B)   # not -I: playwright

# Two views of one dump (see $(DEMO_CONFIG)): clock-sampled (real WaveDrom wave strings) and exact transitions ("tv").
$(DEMO_JS): $(VCD) $(DEMO_CONFIG) tools/vcd2wavedrom.py tools/wavejson.py tools/embed.py
	$(V2W) --view cycle --out $(B)/cyc.json
	$(V2W) --view exact --out $(B)/exact.json
	$(PY) tools/embed.py --var DEMO_WAVES cycle=$(B)/cyc.json exact=$(B)/exact.json --out $@

html: $(CONFIG) $(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(VCD))
	$(PY) tools/mkhtml.py --config $(CONFIG) $(if $(HTML_WAVES),--waves $(HTML_WAVES)) $(if $(READER),--reader $(READER)) --out $(HTML)

config:
	$(if $(WAVES),,$(error make config needs WAVES=dump.vcd))
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $(CONFIG) --update $(if $(SV),--sv $(SV)) $(if $(READER),--reader $(READER))

ifdef WAVES
$(CONFIG): | $(WAVES)   # only when missing: never overwrites an edited config
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $@ $(if $(SV),--sv $(SV)) $(if $(READER),--reader $(READER))
endif

smoke:
	python3 tests/smoke.py --build $(B) --out $(B)/shots   # not -I: playwright lives in the user site-packages

clean:
	rm -rf $(OBJ) $(OBJ)_fst $(VCD) $(FST) $(B)/cyc.json $(B)/exact.json $(B)/demo.html $(B)/shots
	rm -rf $(basename $(FST)).config.json $(basename $(FST)).html
	rm -rf $(B)/examples
	rmdir $(B) 2>/dev/null || true

.PHONY: help demo demo-fst example examples shots html config smoke clean
