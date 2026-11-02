"""test_apb.py — five cocotb tests of an APB3 register slave, marked up on the waves by wavelens_cocotb.

The decorator writes each test's number into the testbench's TEST_CASE, wl.phase its phase's into TEST_STEP. The last one finds
the slave's deliberate bug: it is expected to fail, so the regression stays green and the page shows a red test.
"""
import contextlib

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

try:
    from wavelens_cocotb import Marks
except ImportError:
    class Marks:
        """No WaveLens here: the same calls, the test runs as it is. A check still checks."""

        def __init__(self, *args, **kw):
            pass

        def test(self, *args, **kw):
            return cocotb.test(*args, **kw)

        def phase(self, *args, **kw):
            return contextlib.nullcontext()

        def note(self, *args, **kw):
            pass

        def check(self, got, expected, text='', **kw):
            assert got == expected, f'{text}: got {got}, expected {expected}'

wl = Marks()
CTRL, ID, DATA, SCRATCH, UNMAPPED = 0x00, 0x04, 0x08, 0x0C, 0x40
ID_VALUE = 0xA5B00035


async def start(dut):
    """A test's clock (cocotb ends a test's tasks with it) and reset."""
    cocotb.start_soon(Clock(dut.PCLK, 10, 'ns').start())
    with wl.phase('reset'):
        dut.PRESETn.value = 0
        for s in (dut.PSEL, dut.PENABLE, dut.PWRITE, dut.PADDR, dut.PWDATA):
            s.value = 0
        await Timer(25, 'ns')
        dut.PRESETn.value = 1
        await RisingEdge(dut.PCLK)


async def transfer(dut, addr, write, data=0):
    """One APB transfer: SETUP, ACCESS until PREADY -> (PRDATA, PSLVERR, wait states), at the edge that ends it: a check right
    after it sits on that edge, and the next transfer may follow at once."""
    dut.PADDR.value = addr
    dut.PWRITE.value = int(write)
    dut.PWDATA.value = data
    dut.PSEL.value = 1
    await RisingEdge(dut.PCLK)
    dut.PENABLE.value = 1
    waits = -1
    while True:
        await RisingEdge(dut.PCLK)
        waits += 1
        if dut.PREADY.value == 1:
            break
    rdata, err = dut.PRDATA.value.to_unsigned(), int(dut.PSLVERR.value)
    dut.PSEL.value = 0
    dut.PENABLE.value = 0
    return rdata, err, waits


async def write(dut, addr, data):
    return await transfer(dut, addr, True, data)


async def read(dut, addr):
    return await transfer(dut, addr, False)


@wl.test()
async def test_reset_values(dut):
    """Every register reads its reset value."""
    await start(dut)
    with wl.phase('read all'):
        for addr, name, value in ((CTRL, 'CTRL', 0), (ID, 'ID', ID_VALUE), (DATA, 'DATA', 0), (SCRATCH, 'SCRATCH', 0)):
            got, _, _ = await read(dut, addr)
            wl.check(got, value, f'{name} after reset', signal=dut.PRDATA)


@wl.test()
async def test_write_read(dut):
    """What is written to CTRL comes back; ID does not take a write."""
    await start(dut)
    with wl.phase('CTRL'):
        await write(dut, CTRL, 0x12345678)
        got, _, _ = await read(dut, CTRL)
        wl.check(got, 0x12345678, 'CTRL reads back', signal=dut.PRDATA)
    with wl.phase('ID is read only'):
        wl.note('a write the slave must ignore', signal=dut.PWDATA, label='write to ID')
        await write(dut, ID, 0xDEADBEEF)
        got, _, _ = await read(dut, ID)
        wl.check(got, ID_VALUE, 'ID is unchanged', signal=dut.PRDATA)


@wl.test()
async def test_wait_states(dut):
    """A read of DATA is stretched by two wait states, its write is not."""
    await start(dut)
    with wl.phase('write'):
        _, _, waits = await write(dut, DATA, 0xCAFE0001)
        wl.check(waits, 0, 'wait states of the write', signal=dut.PENABLE)
    with wl.phase('read'):
        got, _, waits = await read(dut, DATA)
        wl.check(waits, 2, 'PREADY low for two cycles of ACCESS', signal=dut.PREADY)
        wl.check(got, 0xCAFE0001, 'DATA reads back', signal=dut.PRDATA)


@wl.test()
async def test_slave_error(dut):
    """An unmapped address ends with PSLVERR and changes nothing."""
    await start(dut)
    await write(dut, CTRL, 0x55)
    with wl.phase('unmapped'):
        dut._log.warning('address %#x is not mapped: PSLVERR comes next', UNMAPPED)
        _, err, _ = await write(dut, UNMAPPED, 0xFFFFFFFF)
        wl.check(err, 1, 'PSLVERR on the unmapped write', signal=dut.PSLVERR)
    got, _, _ = await read(dut, CTRL)
    wl.check(got, 0x55, 'CTRL is untouched', signal=dut.PRDATA)


@wl.test(expect_fail=True)
async def test_scratch_walking_one(dut):
    """A single 1 walks through SCRATCH: every bit must hold it (bit 17 does not: the slave's bug)."""
    await start(dut)
    with wl.phase('walking one'):
        for bit in range(32):
            value = 1 << bit
            await write(dut, SCRATCH, value)
            got, _, _ = await read(dut, SCRATCH)
            wl.check(got, value, f'SCRATCH bit {bit}', signal=dut.PRDATA, show='fail')
