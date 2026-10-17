# wavefw — demo flow: Verilator VCD -> wavepeek -> WaveDrom JSON -> demo_waves.js (loaded by example.html)
# Build products live under /tmp (the project sits on /mnt/c, which is slow under WSL).
# Converter settings (signals, enums, groups, markers, colours, sorting …) come from a JSON config file.
OBJ ?= /tmp/wavefw_obj
VCD ?= /tmp/wavefw_demo.vcd
PY  := python3 -I
READER ?=          # builtin (default: one pass in Python) | wavepeek
DEMO_CONFIG := tools/demo/demo.config.json
V2W := $(PY) tools/vcd2wavedrom.py --config $(DEMO_CONFIG) --waves $(VCD) $(if $(READER),--reader $(READER))

# Any dump, starting from the VCD alone:
#   make config WAVES=x.vcd   -> x.config.json: every signal under its full path, one line each (show, radix, color,
#                                style …), settings from $(BASE). Run it again after the dump changed: new signals
#                                are added, gone ones dropped, your edits kept.
#   make html WAVES=x.vcd     -> x.html (makes x.config.json first if it does not exist yet)
#   WAVES may be a VCD or an FST (FST needs GTKWave's fst2vcd for order / change counts / enum labels).
#   FSM state names: an FST brings its enum tables; for a VCD add SV="rtl/*.sv" (typedef enum in the sources).
# make html: one self-contained page (wavefw.css/js + data inlined) from every view of CONFIG.
#   make html                                         demo dump -> /tmp/wavefw_demo.html
#   make html CONFIG=dump.config.json HTML=dump.html  a hand-written config
BASE ?= wavefw.base.json
ifdef WAVES
CONFIG ?= $(basename $(WAVES)).config.json
HTML   ?= $(basename $(WAVES)).html
endif
CONFIG ?= $(DEMO_CONFIG)
HTML   ?= /tmp/wavefw_demo.html
HTML_WAVES = $(or $(WAVES),$(if $(filter $(DEMO_CONFIG),$(CONFIG)),$(VCD)))

demo: demo_waves.js

# The same testbench dumped as FST (Verilator --trace-fst): FSM enum labels come from the dump itself.
#   make demo-fst  -> /tmp/wavefw_demo_fst.config.json (mkconfig) + /tmp/wavefw_demo_fst.html
FST ?= /tmp/wavefw_demo_fst.fst
$(OBJ)_fst/Vdemo_tb: tools/demo/demo_tb.sv
	verilator --binary --timing -Wno-fatal --trace-fst --top-module demo_tb -Mdir $(OBJ)_fst tools/demo/demo_tb.sv

$(FST): $(OBJ)_fst/Vdemo_tb
	cd $(OBJ)_fst && ./Vdemo_tb +trace +dump=$(FST)

demo-fst: $(FST)
	$(MAKE) config html WAVES=$(FST)

$(OBJ)/Vdemo_tb: tools/demo/demo_tb.sv
	verilator --binary --timing -Wno-fatal --trace --top-module demo_tb -Mdir $(OBJ) tools/demo/demo_tb.sv

$(VCD): $(OBJ)/Vdemo_tb
	cd $(OBJ) && ./Vdemo_tb +trace && mv demo.vcd $(VCD)

# Two views of one dump (see $(DEMO_CONFIG)): clock-sampled (real WaveDrom wave strings) and exact transitions ("tv").
demo_waves.js: $(VCD) $(DEMO_CONFIG) tools/vcd2wavedrom.py tools/wavejson.py tools/embed.py
	$(V2W) --view cycle --out /tmp/wavefw_cyc.json
	$(V2W) --view exact --out /tmp/wavefw_exact.json
	$(PY) tools/embed.py --var DEMO_WAVES cycle=/tmp/wavefw_cyc.json exact=/tmp/wavefw_exact.json --out $@

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
	python3 tools/smoke.py   # not -I: playwright lives in the user site-packages

clean:
	rm -rf $(OBJ) $(VCD) /tmp/wavefw_cyc.json /tmp/wavefw_exact.json /tmp/wavefw_demo.html
	rm -rf $(OBJ)_fst $(FST) $(basename $(FST)).config.json $(basename $(FST)).html

.PHONY: demo demo-fst html config smoke clean
