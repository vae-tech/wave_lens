# wavefw — demo flow: Verilator VCD -> wavepeek -> WaveDrom JSON -> demo_waves.js (loaded by example.html)
# Build products live under /tmp (the project sits on /mnt/c, which is slow under WSL).
# Converter settings (signals, enums, groups, markers, colours, sorting …) come from a JSON config file.
OBJ ?= /tmp/wavefw_obj
VCD ?= /tmp/wavefw_demo.vcd
PY  := python3 -I
DEMO_CONFIG := tools/demo/demo.config.json
V2W := $(PY) tools/vcd2wavedrom.py --config $(DEMO_CONFIG) --waves $(VCD)

# Any dump, starting from the VCD alone:
#   make config WAVES=x.vcd   -> x.config.json: every signal under its full path, one line each (show, radix, color,
#                                style …), settings from $(BASE). Run it again after the dump changed: new signals
#                                are added, gone ones dropped, your edits kept.
#   make html WAVES=x.vcd     -> x.html (makes x.config.json first if it does not exist yet)
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
	$(PY) tools/mkhtml.py --config $(CONFIG) $(if $(HTML_WAVES),--waves $(HTML_WAVES)) --out $(HTML)

config:
	$(if $(WAVES),,$(error make config needs WAVES=dump.vcd))
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $(CONFIG) --update

ifdef WAVES
$(CONFIG): | $(WAVES)   # only when missing: never overwrites an edited config
	$(PY) tools/mkconfig.py $(WAVES) --base $(BASE) --out $@
endif

smoke:
	python3 tools/smoke.py   # not -I: playwright lives in the user site-packages

clean:
	rm -rf $(OBJ) $(VCD) /tmp/wavefw_cyc.json /tmp/wavefw_exact.json /tmp/wavefw_demo.html

.PHONY: demo html config smoke clean
