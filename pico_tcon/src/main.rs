#![no_std]
#![no_main]

use embassy_executor::Spawner;
use embassy_rp::bind_interrupts;
use embassy_rp::peripherals::{PIO0, PIO1};
use embassy_rp::pio::program::pio_asm;
use embassy_rp::pio::{Config, Direction, InterruptHandler, Pio};

bind_interrupts!(struct Irqs {
    PIO0_IRQ_0 => InterruptHandler<PIO0>;
    PIO1_IRQ_0 => InterruptHandler<PIO1>;
});

#[embassy_executor::main]
async fn main(_spawner: Spawner) {
    let p = embassy_rp::init(Default::default());

    // Configure onboard LED (GP25) as Output
    let _led_pin = embassy_rp::gpio::Output::new(p.PIN_25, embassy_rp::gpio::Level::Low);

    // ── PIO0: SSPL, SOE, GOE ──────────────────────────────────────────────
    let Pio {
        mut common,
        mut sm0, // SSPL
        mut sm1, // SOE
        mut sm2, // GOE
        ..
    } = Pio::new(p.PIO0, Irqs);

    // Inputs from Pi: GP2=SSC, GP3=DE, GP4=HSYNC.
    // Outputs: GP5=SOE, GP6=SSPL, GP8=GOE.
    let _ssc = common.make_pio_pin(p.PIN_2);
    let _de = common.make_pio_pin(p.PIN_3);
    let _hsync = common.make_pio_pin(p.PIN_4);
    let soe_pin = common.make_pio_pin(p.PIN_5);
    let sspl_pin = common.make_pio_pin(p.PIN_6);
    let goe_pin = common.make_pio_pin(p.PIN_8);

    // SSPL: ~1-SSC-clock start pulse at DE rising edge (first active pixel).
    // To eliminate high-frequency pixel clock noise/ringing issues, we wait for
    // the HSYNC rising edge (end of sync pulse, start of back porch), delay using
    // a rock-solid system-clock loop, and wait for a single SSC transition at the end.
    // gpio 4 = HSYNC, gpio 2 = SSC.
    let sspl_prg = pio_asm!(
        ".wrap_target",
        "wait 0 gpio 4",      // wait for HSYNC low
        "wait 1 gpio 4",      // wait for HSYNC high (back porch start)
        "set y, 7",           // 8 outer loops
        "sspl_y:",
        "set x, 7",           // 8 inner loops
        "sspl_x:",
        "jmp x-- sspl_x [4]", // 5 cycles per inner loop. 5 * 8 = 40 cycles.
        "jmp y-- sspl_y",     // 1 cycle. Total = 8 * 41 = 328 system clock cycles (~2.63us)
        "wait 0 gpio 2",      // wait for SSC low
        "wait 1 gpio 2",      // wait for SSC high (align to clock edge)
        "set pins, 1",        // set SSPL high
        "wait 0 gpio 2",
        "wait 1 gpio 2",      // wait 1 SSC clock
        "set pins, 0",        // set SSPL low
        ".wrap",
    );

    // SOE: source output enable. The datasheet specifies that SOE is a line latch strobe,
    // NOT a level, and should emit a brief ~2-clock pulse at the DE falling edge.
    // We add a 1 clock cycle delay (Tld >= 1 clock) before raising SOE.
    // gpio 3 = DE, gpio 2 = SSC.
    let soe_prg = pio_asm!(
        ".wrap_target",
        "wait 1 gpio 3",      // wait for DE high
        "wait 0 gpio 3",      // wait for DE low
        "wait 1 gpio 2",      // wait 1 clock cycle (Tld delay)
        "wait 0 gpio 2",
        "set pins, 1",        // SOE high
        "wait 1 gpio 2",      // clock 1
        "wait 0 gpio 2",
        "wait 1 gpio 2",      // clock 2
        "wait 0 gpio 2",
        "set pins, 0",        // SOE low
        ".wrap",
    );

    // GOE: gate output enable. HIGH blanks the gate outputs; LOW lets the gate
    // follow the scan (selected row on). Idle LOW (enabled); at each HSYNC edge
    // (the gate-clock row advance) emit a brief ~1.5 us HIGH blip to blank the
    // transition so adjacent rows don't overlap. That blanking is what isolates
    // the rows. Datasheet GOE pulse width >=1us. gpio 4 = HSYNC.
    let goe_prg = pio_asm!(
        "set pins, 0",        // idle LOW: gate enabled
        ".wrap_target",
        "wait 1 gpio 4",
        "wait 0 gpio 4",      // HSYNC falling edge = row advance
        "set pins, 1",        // GOE high: blank the transition
        "set x, 31",
    "goe_delay:",
        "jmp x-- goe_delay [5]", // 32 * 6 = 192 system clock cycles ≈ 1.53 us
        "set pins, 0",        // GOE low: re-enable
        ".wrap",
    );

    let loaded_sspl = common.load_program(&sspl_prg.program);
    let loaded_soe = common.load_program(&soe_prg.program);
    let loaded_goe = common.load_program(&goe_prg.program);

    let mut cfg0 = Config::default();
    cfg0.use_program(&loaded_sspl, &[]);
    cfg0.set_set_pins(&[&sspl_pin]);
    sm0.set_config(&cfg0);
    sm0.set_pin_dirs(Direction::Out, &[&sspl_pin]);
    sm0.set_enable(true);

    let mut cfg1 = Config::default();
    cfg1.use_program(&loaded_soe, &[]);
    cfg1.set_set_pins(&[&soe_pin]);
    sm1.set_config(&cfg1);
    sm1.set_pin_dirs(Direction::Out, &[&soe_pin]);
    sm1.set_enable(true);

    let mut cfg2 = Config::default();
    cfg2.use_program(&loaded_goe, &[]);
    cfg2.set_set_pins(&[&goe_pin]);
    sm2.set_config(&cfg2);
    sm2.set_pin_dirs(Direction::Out, &[&goe_pin]);
    sm2.set_enable(true);

    // ── PIO1: GSPU, GSC, POL ──────────────────────────────────────────────
    let Pio {
        common: mut common1,
        sm0: mut gspu_sm,
        sm1: mut gsc_sm,
        sm2: mut pol_sm,
        ..
    } = Pio::new(p.PIO1, Irqs);

    let vsync_pin = common1.make_pio_pin(p.PIN_9);
    let gspu_pin = common1.make_pio_pin(p.PIN_10);
    let gsc_pin = common1.make_pio_pin(p.PIN_11);
    let pol_pin = common1.make_pio_pin(p.PIN_7);

    // GSPU: one clean token per frame. At the frame's VSYNC, skip one HSYNC
    // edge (so GSPU is high a full line before it loads — far exceeds the 200ns
    // setup), then go high across exactly the next HSYNC/GSC edge (token loads
    // at row 0), hold ~1us (>> 300ns hold), then drop before the following edge
    // so no second token. gpio 9 = VSYNC, gpio 4 = HSYNC.
    let gspu_prg = pio_asm!(
        "set pins, 0",        // GSPU idle low
        ".wrap_target",
    "wait_vsync_low:",
        "wait 0 gpio 9",      // wait VSYNC low
        "set x, 30",
    "vsync_low_debounce:",
        "jmp x-- vsync_low_debounce [3]", // wait 1 us
        "jmp pin wait_vsync_low", // if VSYNC is high (noise spike), restart!
        "wait 1 gpio 9",      // VSYNC rising = frame start
        "wait 1 gpio 4",
        "wait 0 gpio 4",      // edge A (GSPU still low -> no token here)
        "set pins, 1",        // GSPU high
        "wait 1 gpio 4",
        "wait 0 gpio 4",      // edge B: token loads (GSPU high, ~1 line setup)
        "set x, 30",
    "gspu_hold:",
        "jmp x-- gspu_hold [3]", // 31 * 4 = 124 system clock cycles ≈ 1.0 us
        "set pins, 0",        // GSPU low before the next edge
        ".wrap",
    );

    // GSC: gate clock with ONE clean advance edge per line, at mid-line. At each
    // HSYNC falling edge (line start) drop GSC low, wait ~half a line (~15.8 us),
    // then raise it — that rising edge advances the gate, and it sits far from
    // HSYNC's edges so GSPU's window spans exactly one of them.
    // gpio 4 = HSYNC.
    let gsc_prg = pio_asm!(
        "set pins, 0",
        ".wrap_target",
        "wait 1 gpio 4",
        "wait 0 gpio 4",      // HSYNC falling = line start
        "set pins, 0",        // GSC low
        "set y, 5",
    "gsc_y:",
        "set x, 31",
    "gsc_x:",
        "jmp x-- gsc_x [1]",  // inner loop
        "jmp y-- gsc_y",      // wait ~2015 system clock cycles ≈ 16.12 us (half line)
        "set pins, 1",        // GSC high: the single advance edge, at mid-line
        ".wrap",
    );

    // POL: toggle every active line on DE falling edge (gpio 3).
    let pol_prg = pio_asm!(
        ".wrap_target",
        "wait 1 gpio 3",      // wait for DE high
        "wait 0 gpio 3",      // wait for DE low
        "set pins, 1",
        "wait 1 gpio 3",
        "wait 0 gpio 3",
        "set pins, 0",
        ".wrap",
    );

    let loaded_gspu = common1.load_program(&gspu_prg.program);
    let loaded_gsc = common1.load_program(&gsc_prg.program);
    let loaded_pol = common1.load_program(&pol_prg.program);

    let mut cfg_g = Config::default();
    cfg_g.use_program(&loaded_gspu, &[]);
    cfg_g.set_set_pins(&[&gspu_pin]);
    cfg_g.set_jmp_pin(&vsync_pin);
    gspu_sm.set_config(&cfg_g);
    gspu_sm.set_pin_dirs(Direction::Out, &[&gspu_pin]);
    gspu_sm.set_enable(true);

    let mut cfg_gsc = Config::default();
    cfg_gsc.use_program(&loaded_gsc, &[]);
    cfg_gsc.set_set_pins(&[&gsc_pin]);
    gsc_sm.set_config(&cfg_gsc);
    gsc_sm.set_pin_dirs(Direction::Out, &[&gsc_pin]);
    gsc_sm.set_enable(true);

    let mut cfg_pol = Config::default();
    cfg_pol.use_program(&loaded_pol, &[]);
    cfg_pol.set_set_pins(&[&pol_pin]);
    pol_sm.set_config(&cfg_pol);
    pol_sm.set_pin_dirs(Direction::Out, &[&pol_pin]);
    pol_sm.set_enable(true);

    loop {
        cortex_m::asm::wfi();
    }
}

#[panic_handler]
fn panic(_info: &core::panic::PanicInfo) -> ! {
    loop {}
}
